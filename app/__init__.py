import logging
import os

from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import Config, SECRET_KEY_IS_EPHEMERAL
from app.helpers import strip_document_id

log = logging.getLogger(__name__)

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.getenv('REDIS_URL', 'redis://127.0.0.1:6380/1'),
)


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

    # Redis es un servicio secundario: si el backend de rate limiting no arranca,
    # la app degrada a limitador en memoria en vez de tumbar el worker.
    app.config['LIMITER_BACKEND'] = os.getenv('REDIS_URL', 'redis://127.0.0.1:6380/1')
    try:
        limiter.init_app(app)
    except Exception:
        log.exception(
            'No se pudo inicializar el rate limiter con %s. Degradando a memory://',
            app.config['LIMITER_BACKEND'],
        )
        limiter._storage_uri = 'memory://'
        app.config['LIMITER_BACKEND'] = 'memory:// (degradado)'
        try:
            limiter.init_app(app)
        except Exception:
            log.exception('Rate limiter deshabilitado tras fallo del fallback en memoria.')
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
        return {'notificaciones_no_leidas': no_leidas, 'datetime': datetime}

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
        estado = {
            'status': 'ok',
            'database': 'connected',
            'rate_limiter': app.config.get('LIMITER_BACKEND'),
            'secret_key': 'efimera (revisar SECRET_KEY)' if SECRET_KEY_IS_EPHEMERAL else 'ok',
            'startup_errors': app.config.get('STARTUP_ERRORS', []),
        }
        try:
            with db.engine.connect():
                pass
        except Exception as exc:
            estado['status'] = 'degraded'
            estado['database'] = f'{type(exc).__name__}: {exc}'
            log.error('Health check: sin conexion a la base de datos.', exc_info=True)
        if estado['startup_errors'] or SECRET_KEY_IS_EPHEMERAL:
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
