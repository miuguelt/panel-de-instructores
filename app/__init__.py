import logging
import os

from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFError, CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import Config, SECRET_KEY_IS_EPHEMERAL
from app.helpers import strip_document_id

log = logging.getLogger(__name__)

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()
# Se inicializa con memory:// hasta que _probe_redis() confirme que Redis
# responde correctamente (incluyendo autenticacion). Esto evita que un Redis
# caido o mal configurado tumbe cada request con AuthenticationError.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri='memory://',
)


def _encode_redis_url(redis_url: str) -> str:
    """URL-encodea el password en una redis:// URL para soportar caracteres especiales.

    urlparse falla si el password contiene '/' porque lo confunde con el path.
    Se usa regex para extraer y recodificar el password de forma segura antes
    de que cualquier parser de URL lo procese.
    """
    import re
    from urllib.parse import quote
    # Captura: scheme://[usuario:]password@host[:port][/db]
    # El password puede contener cualquier char antes del primer '@'
    pattern = r'^(rediss?://)([^:@]*):([^@]+)@(.+)$'
    match = re.match(pattern, redis_url)
    if match:
        scheme_prefix = match.group(1)
        username = match.group(2)
        password = match.group(3)
        rest = match.group(4)   # host:port/db
        if any(c in password for c in '/@=+#?&'):
            encoded = quote(password, safe='')
            user_part = f'{username}:{encoded}' if username else f':{encoded}'
            return f'{scheme_prefix}{user_part}@{rest}'
    return redis_url


def _sanitize_storage_uri(storage_uri: str) -> str:
    """Enmascara las credenciales de una URI de storage antes de exponerla.

    'LIMITER_BACKEND' se publica en /health, que responde sin autenticacion y
    queda accesible tras el proxy. Devolver la URI cruda filtraria la password
    de Redis a cualquiera que consulte el endpoint. Los valores sin credenciales
    ('memory://', 'deshabilitado') se devuelven intactos.
    """
    if not storage_uri or '://' not in storage_uri:
        return storage_uri
    scheme, rest = storage_uri.split('://', 1)
    if '@' not in rest:
        return storage_uri
    host = rest.rsplit('@', 1)[1]
    return f'{scheme}://****@{host}'


def _probe_redis(redis_url: str) -> str:
    """Verifica que Redis responde correctamente (incluyendo AUTH).

    Retorna la URL (con password codificado si aplica) si la conexión es exitosa,
    o 'memory://' si Redis no está disponible o las credenciales son inválidas.
    Nunca lanza excepciones al caller.
    """
    if not redis_url:
        log.info('REDIS_URL no configurada. Rate limiter usara memory://')
        return 'memory://'

    # Coolify/Compose a veces dejan comillas o espacios pegados al valor de la
    # variable (copy-paste, interpolacion de .env). Esto rompe el parseo del
    # scheme en redis-py con "Redis URL must specify one of the following
    # schemes" aunque la URL "se vea bien" a simple vista. Se limpia solo y se
    # deja constancia en el log en vez de tumbar el rate limiter en silencio.
    cleaned_url = redis_url.strip().strip('"').strip("'")
    if cleaned_url != redis_url:
        log.warning(
            'REDIS_URL traia comillas o espacios sobrantes (longitud original=%d, '
            'primeros 12 chars=%r). Se limpio automaticamente.',
            len(redis_url), redis_url[:12],
        )

    if not cleaned_url.startswith(('redis://', 'rediss://', 'unix://')):
        log.warning(
            'REDIS_URL no inicia con un scheme valido (redis://, rediss://, unix://). '
            'Primeros 12 caracteres recibidos (repr): %r. Revisa el valor en Coolify '
            '(comillas extra, "$" sin escapar, o variable mal referenciada). '
            'Rate limiter usara memory://.',
            cleaned_url[:12],
        )
        return 'memory://'

    # Codifica chars especiales en el password antes de parsear la URL
    safe_url = _encode_redis_url(cleaned_url)
    try:
        import redis as _redis
        # Timeout corto: no bloquear el arranque
        client = _redis.from_url(safe_url, socket_connect_timeout=3, socket_timeout=3)
        client.ping()
        client.close()
        log.info('Redis disponible: %s. Rate limiter activo.', safe_url.split('@')[-1])
        return safe_url
    except Exception as exc:
        log.warning(
            'Redis no disponible (%s: %s). Host/puerto intentados: %s. Rate limiter usara memory://',
            type(exc).__name__, exc, safe_url.split('@')[-1],
        )
        return 'memory://'

STATIC_MAX_AGE = 31536000  # 1 año: la URL cambia cuando cambia el archivo


def _preparar_uploads(app):
    """Crea la carpeta de subidas y comprueba que el proceso pueda escribir.

    En Coolify `uploads` es un volumen montado en /app/uploads. Si el volumen
    se monta con otro owner, el contenedor corre como `adso` y no puede
    escribir: cada subida fallaba con un error genérico y el diagnóstico
    requería entrar al contenedor. Aquí se detecta en el arranque y queda en
    el log y en /health.
    """
    carpeta = app.config.get('UPLOAD_FOLDER')
    estado = {'ruta': carpeta, 'escribible': False, 'detalle': ''}
    try:
        os.makedirs(carpeta, exist_ok=True)
        testigo = os.path.join(carpeta, '.escritura')
        with open(testigo, 'wb') as handle:
            handle.write(b'ok')
        os.remove(testigo)
        estado['escribible'] = True
        log.info('Carpeta de subidas lista y escribible: %s', carpeta)
    except OSError as exc:
        estado['detalle'] = f'{type(exc).__name__}: {exc}'
        log.error(
            'La carpeta de subidas %s NO es escribible (%s). Las cargas de '
            'evidencias y materiales fallarán. Revisa el volumen en Coolify.',
            carpeta, estado['detalle'],
        )
    app.config['UPLOADS_ESTADO'] = estado


def _inventario_uploads(carpeta, tope=5000):
    """Cuenta archivos del volumen y detecta los que quedaron en 0 bytes.

    Un archivo de 0 bytes significa que la subida se cortó y la BD guardó una
    referencia inservible: aparece en la interfaz pero se descarga vacío.
    """
    resumen = {'archivos': 0, 'vacios': 0, 'parciales': 0, 'bytes': 0, 'truncado': False}
    if not carpeta or not os.path.isdir(carpeta):
        return resumen
    try:
        for raiz, _dirs, nombres in os.walk(carpeta):
            for nombre in nombres:
                if resumen['archivos'] >= tope:
                    resumen['truncado'] = True
                    return resumen
                if nombre.endswith('.part'):
                    resumen['parciales'] += 1
                    continue
                try:
                    tamano = os.path.getsize(os.path.join(raiz, nombre))
                except OSError:
                    continue
                resumen['archivos'] += 1
                resumen['bytes'] += tamano
                if tamano == 0:
                    resumen['vacios'] += 1
    except OSError as exc:
        resumen['error'] = f'{type(exc).__name__}: {exc}'
    return resumen


def _registrar_cache_estaticos(app):
    """Sirve /static/ con caducidad larga y cache-busting por mtime.

    El fingerprint se calcula una sola vez por archivo y se memoriza: en
    produccion los estaticos no cambian mientras el contenedor vive, y hacer un
    stat() por cada url_for anularia parte del ahorro. En debug no se memoriza
    para que editar el CSS se refleje sin reiniciar.
    """
    versiones = {}

    def _version(filename):
        if not app.static_folder:
            return ''
        ruta = os.path.join(app.static_folder, filename)
        try:
            return str(int(os.stat(ruta).st_mtime))
        except OSError:
            # Nombre inexistente o path traversal: se devuelve la URL sin ?v=
            # en vez de romper el render de la plantilla.
            return ''

    @app.url_defaults
    def _agregar_version(endpoint, values):
        if endpoint != 'static' or 'v' in values:
            return
        filename = values.get('filename')
        if not filename:
            return
        if app.debug:
            version = _version(filename)
        else:
            version = versiones.get(filename)
            if version is None:
                version = _version(filename)
                versiones[filename] = version
        if version:
            values['v'] = version

    @app.after_request
    def _cachear_estaticos(response):
        # Solo el endpoint 'static': las descargas de uploads y los reportes
        # generados siguen con la politica por defecto.
        if request.endpoint == 'static' and response.status_code < 400:
            response.headers['Cache-Control'] = (
                f'public, max-age={STATIC_MAX_AGE}, immutable'
            )
        return response


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    # Register filters before importing blueprints so every template compilation
    # sees the complete Jinja environment, including during app initialization.
    app.add_template_filter(strip_document_id, 'strip_document_id')

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Debes iniciar sesion para acceder a esta pagina.'
    migrate.init_app(app, db)
    csrf.init_app(app)

    # --- Compresion de respuestas ---
    # Varias vistas de instructor renderizan HTML de cientos de KB (juicios
    # supera 1 MB), que viaja sin comprimir en cada peticion. gzip lo reduce
    # ~20x y libera al worker mucho antes. Si el paquete falta, la app sigue.
    try:
        from flask_compress import Compress
        app.config.setdefault('COMPRESS_MIMETYPES', [
            'text/html', 'text/css', 'text/javascript',
            'application/javascript', 'application/json',
        ])
        app.config.setdefault('COMPRESS_LEVEL', 6)
        app.config.setdefault('COMPRESS_MIN_SIZE', 1024)
        Compress(app)
    except Exception:
        log.warning('Flask-Compress no disponible. Respuestas sin comprimir.')

    # --- Cache de archivos estaticos ---
    # Cada navegacion volvia a descargar styles.css (150 KB) y table-filters.js
    # porque SEND_FILE_MAX_AGE_DEFAULT=0 emite `Cache-Control: no-cache`: el
    # navegador revalida en cada clic y el worker gasta I/O en devolver bytes
    # identicos. Se sirve con caducidad larga y se invalida por contenido: cada
    # url_for('static') lleva ?v=<mtime>, que cambia solo al editar el archivo.
    _registrar_cache_estaticos(app)

    # --- Almacenamiento de archivos ---
    _preparar_uploads(app)

    # --- Rate limiting con fallback graceful a memoria ---
    # Sondea Redis antes de configurarlo: si la AUTH falla, el limiter opera
    # en memoria y ningun request devuelve 500 por culpa de Redis.
    _redis_url = os.getenv('REDIS_URL', '')
    _storage_uri = _probe_redis(_redis_url)
    # Solo la version enmascarada llega a la config: /health la publica sin auth.
    app.config['LIMITER_BACKEND'] = _sanitize_storage_uri(_storage_uri)
    limiter._storage_uri = _storage_uri
    try:
        limiter.init_app(app)
        # Captura errores de Redis en runtime (auth rotada, timeout, etc.)
        # Deshabilita el limiter y deja pasar el request en vez de devolver 500.
        # Se registra sobre RedisError y NO sobre Exception: un handler generico
        # se aplica tambien a las HTTPException (404, 400, CSRFError...), y el
        # `raise exc` final las convertia en 500.
        import redis.exceptions as _redis_exc

        @app.errorhandler(_redis_exc.RedisError)
        def _handle_limiter_runtime_error(exc):
            log.warning(
                'Redis fallo en runtime (%s). Deshabilitando rate-limit y continuando.',
                type(exc).__name__,
            )
            limiter.enabled = False
            app.config['LIMITER_BACKEND'] = 'deshabilitado (fallo en runtime)'
            # Re-ejecuta el request sin rate limiting
            from flask import request as _req
            return app.view_functions[_req.endpoint](**_req.view_args or {})

    except Exception:
        log.exception(
            'Rate limiter no pudo inicializarse con %s. Operando sin rate-limit.',
            _sanitize_storage_uri(_storage_uri),
        )
        limiter.enabled = False
        app.config['LIMITER_BACKEND'] = 'deshabilitado'

    # Registro tolerante a fallos: un import roto en un modulo de rutas no debe
    # impedir que el proceso arranque. Sin esto gunicorn muere en el boot y el
    # traceback se pierde entre reinicios del contenedor.
    app.config['STARTUP_ERRORS'] = []

    def _register(module_path, *blueprints, url_prefix=None):
        try:
            module = __import__(module_path, fromlist=blueprints)
            for name in blueprints:
                app.register_blueprint(getattr(module, name), url_prefix=url_prefix)
        except Exception as exc:
            detalle = f'{module_path}: {type(exc).__name__}: {exc}'
            app.config['STARTUP_ERRORS'].append(detalle)
            log.exception('Fallo al registrar blueprints de %s', module_path)

    _register('app.routes.auth', 'auth_bp')
    _register('app.routes.api', 'api_bp', url_prefix='/api')
    _register('app.routes.instructor', 'instructor_bp', url_prefix='/instructor')
    _register('app.routes.ranking', 'ranking_bp', url_prefix='/instructor')
    _register('app.routes.aseo', 'aseo_bp', url_prefix='/instructor')
    _register('app.routes.seguimiento', 'seguimiento_bp', url_prefix='/instructor')
    _register('app.routes.aprendiz', 'aprendiz_bp', url_prefix='/aprendiz')
    _register('app.routes.aseo', 'aseo_aprendiz_bp', url_prefix='/aprendiz')
    _register('app.routes.seguimiento', 'aprendiz_seguimiento_bp', url_prefix='/aprendiz')

    if app.config['STARTUP_ERRORS']:
        log.critical(
            'La aplicacion arranco en modo DEGRADADO. Rutas no disponibles: %s',
            ' | '.join(app.config['STARTUP_ERRORS']),
        )

    @app.context_processor
    def inyectar_notificaciones():
        from datetime import datetime
        no_leidas = 0
        if current_user.is_authenticated:
            # La BD puede estar caida o sin migrar: el contador es accesorio y no
            # justifica un 500 en cada plantilla renderizada.
            try:
                from app.models.alertas import Notificacion
                no_leidas = Notificacion.query.filter_by(
                    destinatario_tipo='instructor',
                    destinatario_id=current_user.id,
                    leida=False,
                ).count()
            except Exception:
                log.warning('No se pudo contar notificaciones; se muestra 0.', exc_info=True)
                db.session.rollback()
        # `max_upload_bytes` y no `config.MAX_CONTENT_LENGTH`: varias vistas
        # pasan a la plantilla una variable local llamada `config` (la
        # configuracion de alertas, ranking o aseo de la ficha) que tapa el
        # objeto global de Flask y romperia el render de base.html.
        return {
            'notificaciones_no_leidas': no_leidas,
            'datetime': datetime,
            'max_upload_bytes': app.config.get('MAX_CONTENT_LENGTH') or 0,
        }

    @app.template_filter('tipo_competencia')
    def filtro_tipo_competencia(nombre):
        from app.services.importacion_ficha import clasificar_competencia
        return clasificar_competencia(nombre)

    @app.template_filter('format_size')
    def format_size_filter(bytes_val):
        if not bytes_val or bytes_val < 0:
            return '0 B'
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        val = float(bytes_val)
        while val >= 1024 and i < len(units) - 1:
            val /= 1024
            i += 1
        return f'{val:.1f} {units[i]}'

    @app.route('/health')
    def health():
        """Health check de Coolify y del HEALTHCHECK de Docker.

        Siempre responde 200 mientras el proceso viva: si devolviera 503 con la
        BD caida, Coolify mataria el contenedor y el diagnostico se perderia.
        El detalle del fallo va en el cuerpo.
        """
        from flask import jsonify
        uploads = dict(app.config.get('UPLOADS_ESTADO') or {})
        estado = {
            'status': 'ok',
            'database': 'connected',
            'rate_limiter': app.config.get('LIMITER_BACKEND'),
            'secret_key': 'efimera (revisar SECRET_KEY)' if SECRET_KEY_IS_EPHEMERAL else 'ok',
            'uploads': uploads,
            'startup_errors': app.config.get('STARTUP_ERRORS', []),
        }
        try:
            with db.engine.connect():
                pass
        except Exception as exc:
            estado['status'] = 'degraded'
            estado['database'] = f'{type(exc).__name__}: {exc}'
            log.error('Health check: sin conexion a la base de datos.', exc_info=True)

        # Inventario bajo demanda: recorrer el volumen en cada latido del
        # healthcheck de Docker seria I/O gratuito cada 30 s.
        if request.args.get('uploads') == '1':
            uploads.update(_inventario_uploads(app.config.get('UPLOAD_FOLDER')))
            estado['uploads'] = uploads

        if estado['startup_errors'] or SECRET_KEY_IS_EPHEMERAL or not uploads.get('escribible'):
            estado['status'] = 'degraded'
        return jsonify(estado), 200

    @app.route('/')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))

    @app.errorhandler(404)
    def pagina_no_encontrada(_error):
        return render_template(
            'errors/error.html',
            codigo=404,
            titulo='Página no encontrada',
            mensaje='El enlace puede estar incompleto o el recurso ya no está disponible.',
        ), 404

    @app.errorhandler(CSRFError)
    def token_csrf_invalido(error):
        """Token expirado o sesion perdida: reintentar, no un 500.

        Se devuelve al formulario original con un GET, que emite un token nuevo,
        en vez de mostrar un error tecnico al aprendiz.
        """
        from flask import flash, redirect, request
        log.info('CSRF rechazado en %s: %s', request.path, error.description)
        flash(
            'La sesión del formulario expiró. Vuelve a intentarlo.',
            'error',
        )
        if request.method == 'POST':
            return redirect(request.path)
        return render_template(
            'errors/error.html',
            codigo=400,
            titulo='Sesión expirada',
            mensaje='Vuelve a cargar la página e inténtalo de nuevo.',
        ), 400

    @app.errorhandler(413)
    def archivo_demasiado_grande(_error):
        limite_mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
        return render_template(
            'errors/error.html',
            codigo=413,
            titulo='El archivo es demasiado grande',
            mensaje=f'El tamaño máximo permitido es de {limite_mb} MB.',
        ), 413

    return app
