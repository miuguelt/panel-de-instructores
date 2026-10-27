from datetime import timedelta
import logging
import os
import secrets

from dotenv import load_dotenv

# Handler a stdout antes de cualquier validacion: sin esto los fallos de arranque
# no aparecen en `docker logs` y el contenedor parece morir en silencio.
# Coolify puede entregar una variable declarada pero vacía. Nunca se debe pasar
# ese valor directamente a logging.basicConfig(), porque logging lo interpreta
# como un nivel desconocido y mata app + worker antes de cargar Flask.
_log_level_received = os.getenv('LOG_LEVEL')
_log_level = (_log_level_received or 'INFO').strip().upper() or 'INFO'
_valid_log_levels = {'CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'NOTSET'}
if _log_level not in _valid_log_levels:
    _log_level = 'INFO'
logging.basicConfig(
    level=_log_level,
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
)
log = logging.getLogger(__name__)
if _log_level_received is not None and not _log_level_received.strip():
    log.warning('LOG_LEVEL llegó vacío desde el entorno; se usará INFO.')
elif _log_level_received and _log_level_received.strip().upper() not in _valid_log_levels:
    log.warning(
        'LOG_LEVEL=%r no es válido; se usará INFO. Valores válidos: %s.',
        _log_level_received,
        ', '.join(sorted(_valid_log_levels)),
    )

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# override=False: environment variables set by Coolify/Docker always win over .env.
# .env is only used as a fallback for local Windows development when the variable
# is not already defined in the process environment.
load_dotenv(os.path.join(BASE_DIR, '.env'), override=False)


_INSECURE_SECRETS = {
    '', 'dev-key-change-me',
    'cambiar-esta-clave-en-produccion',
    'cambiar-esta-clave-en-produccion-usar-valor-aleatorio-largo',
}


def _obtener_o_persistir_secret_key(base_dir):
    """
    Obtiene la clave secreta desde el entorno o la persiste en almacenamiento local
    para garantizar que las sesiones no se invaliden en cada reinicio del proceso/contenedor.
    """
    env_secret = (os.getenv('SECRET_KEY') or '').strip()
    if env_secret and env_secret not in _INSECURE_SECRETS:
        return env_secret, False

    # Fallback persistente en almacenamiento local
    archivo_clave = os.getenv('SECRET_KEY_FILE') or os.path.join(base_dir, 'instance', '.secret_key')
    try:
        if os.path.isfile(archivo_clave):
            with open(archivo_clave, 'r', encoding='utf-8') as f:
                clave_guardada = f.read().strip()
                if len(clave_guardada) >= 32 and clave_guardada not in _INSECURE_SECRETS:
                    return clave_guardada, True
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        log.warning('No se pudo leer la clave secreta persistente desde %s (%s). Se regenerará.', archivo_clave, exc)

    # Generar nueva clave de 128 caracteres (64 bytes hex)
    nueva_clave = secrets.token_hex(64)
    tmp_file = f'{archivo_clave}.tmp.{os.getpid()}.{secrets.token_hex(4)}'
    try:
        directorio_clave = os.path.dirname(archivo_clave)
        if directorio_clave:
            os.makedirs(directorio_clave, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = 0o600
        fd = os.open(tmp_file, flags, mode)
        with open(fd, 'w', encoding='utf-8') as f:
            f.write(nueva_clave)
        os.replace(tmp_file, archivo_clave)
    except OSError as exc:
        log.warning('No se pudo guardar la clave secreta persistente en %s (%s).', archivo_clave, exc)
        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except OSError:
            pass

    return nueva_clave, True


_secret_key, SECRET_KEY_IS_EPHEMERAL = _obtener_o_persistir_secret_key(BASE_DIR)
if SECRET_KEY_IS_EPHEMERAL:
    # No abortar el proceso: una excepcion aqui mata a gunicorn en el arranque y
    # el contenedor entra en bucle de reinicios sin dejar rastro legible. Se
    # degrada a una clave efimera (mas segura que un default conocido) y se
    # registra el fallo de forma muy visible en los logs del contenedor.
    log.critical(
        'SECRET_KEY insegura o vacia. '
        'Se genero una clave EFIMERA: las sesiones se invalidaran en cada reinicio. '
        'Defina SECRET_KEY en Coolify con un valor aleatorio largo y SIN el caracter "$" '
        '(Docker Compose lo expande y vacia el valor).'
    )


def _normalize_db_url(url):
    """Normaliza esquemas PostgreSQL para SQLAlchemy y el driver psycopg2."""
    if not url:
        return url
    if url.startswith('postgres://'):
        return 'postgresql+psycopg2://' + url[len('postgres://'):]
    if url.startswith('postgresql+psycopg://'):
        return 'postgresql+psycopg2://' + url[len('postgresql+psycopg://'):]
    return url


_db_url = _normalize_db_url((os.getenv('DATABASE_URL') or '').strip())


def _env_int(name, default, minimum=None, maximum=None):
    """Lee un entero de entorno tolerando valores vacíos o inválidos."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        log.warning('%s=%r no es un entero válido; se usará %r.', name, raw, default)
        return default
    if minimum is not None and value < minimum:
        log.warning('%s=%r es menor que %r; se usará %r.', name, value, minimum, default)
        return default
    if maximum is not None and value > maximum:
        log.warning('%s=%r es mayor que %r; se usará %r.', name, value, maximum, default)
        return default
    return value


class Config:
    SECRET_KEY = _secret_key
    SECRET_KEY_IS_EPHEMERAL = SECRET_KEY_IS_EPHEMERAL

    # Directivas de sesión para persistencia prolongada (1 año = 365 días)
    PERMANENT_SESSION_LIFETIME = timedelta(days=365)
    SESSION_COOKIE_NAME = 'session'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = (
        (os.getenv('FLASK_ENV') == 'production')
        or (os.getenv('SESSION_COOKIE_SECURE', '').lower() in ('1', 'true', 'yes'))
        or (os.getenv('PUBLIC_BASE_URL', '').startswith('https://'))
    )
    REMEMBER_COOKIE_DURATION = timedelta(days=365)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE

    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    HTTP_SLOW_REQUEST_MS = _env_int('HTTP_SLOW_REQUEST_MS', 1000, minimum=0)
    # El pool es por proceso worker. Los valores por defecto están pensados para
    # una instancia pequeña de Coolify: 2 procesos x 4 hilos y hasta 6
    # conexiones por proceso (12 en total). Se pueden ampliar por entorno si
    # PostgreSQL tiene capacidad suficiente.
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': _env_int('DB_POOL_SIZE', 4, minimum=1),
        'max_overflow': _env_int('DB_MAX_OVERFLOW', 2, minimum=0),
        'pool_recycle': 300,
        'pool_pre_ping': True,
        'pool_timeout': 10,
    }
    _upload_folder = os.getenv('UPLOAD_FOLDER') or 'uploads'
    UPLOAD_FOLDER = (
        _upload_folder
        if os.path.isabs(_upload_folder)
        else os.path.join(BASE_DIR, _upload_folder)
    )
    # `MAX_CONTENT_LENGTH` conserva su contrato de despliegue como límite por
    # archivo. Flask limita el cuerpo multipart completo, que incluye campos y
    # separadores además del archivo, por eso se reserva 1 MiB adicional.
    MAX_UPLOAD_BYTES = _env_int(
        'MAX_CONTENT_LENGTH', 50 * 1024 * 1024, minimum=1
    )
    MAX_CONTENT_LENGTH = MAX_UPLOAD_BYTES + 1024 * 1024
    MAX_RESUMABLE_UPLOAD_BYTES = _env_int('MAX_RESUMABLE_UPLOAD_BYTES', 2 * 1024**3, minimum=1)
    CARGAS_BLOQUE_BYTES = 4 * 1024**2
    CARGAS_RESERVA_BYTES = 2 * 1024**3
    CARGAS_RESERVA_PORCENTAJE = 0.10
    CARGAS_REANUDABLES_ENABLED = os.getenv('CARGAS_REANUDABLES_ENABLED', 'false').lower() == 'true'
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'zip', 'rar', '7z', 'xlsx', 'xls', 'doc', 'docx', 'ppt', 'pptx'}
    SMTP_HOST = os.getenv('SMTP_HOST')
    SMTP_PORT = _env_int('SMTP_PORT', 587, minimum=1, maximum=65535)
    SMTP_USER = os.getenv('SMTP_USER')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
    SMTP_FROM = os.getenv('SMTP_FROM')
    # Dominio HTTPS canónico para construir enlaces de correo sin confiar en Host.
    PUBLIC_BASE_URL = (os.getenv('PUBLIC_BASE_URL') or '').strip().rstrip('/')
    # Sin limite de tiempo propio: el token sigue firmado con SECRET_KEY y atado
    # a la sesion, pero deja de caducar a la hora. Una pestana abierta durante la
    # jornada (el caso normal en el aula) ya no rechaza el POST del aprendiz.
    WTF_CSRF_TIME_LIMIT = (
        _env_int('WTF_CSRF_TIME_LIMIT', None, minimum=0)
        if os.getenv('WTF_CSRF_TIME_LIMIT') and os.getenv('WTF_CSRF_TIME_LIMIT').strip()
        else None
    )
    # En produccion las plantillas no cambian mientras el contenedor vive, y
    # auto_reload obliga a Jinja a hacer un stat() por plantilla heredada en
    # cada render. En local se mantiene activo para no reiniciar al editar.
    TEMPLATES_AUTO_RELOAD = os.getenv('FLASK_ENV') != 'production'
    # Politica por defecto para send_file/send_from_directory (uploads,
    # reportes generados): sin cache. Subir la caducidad aqui tambien alargaria
    # la de los archivos subidos y los reportes descargables. Los archivos de
    # /static/ se sirven con caducidad larga desde _registrar_cache_estaticos(),
    # que ademas versiona su URL.
    SEND_FILE_MAX_AGE_DEFAULT = 0
    # En produccion el XLS se procesa en el servicio worker de Compose. En
    # local/tests se conserva el flujo sincrono para no exigir Redis.
    IMPORTACIONES_ASINCRONAS = (
        (os.getenv('IMPORTACIONES_ASINCRONAS') or ('true' if os.getenv('FLASK_ENV') == 'production' else 'false'))
        .strip().lower() in ('1', 'true', 'yes', 'on')
    )
    IMPORT_QUEUE_NAME = os.getenv('IMPORT_QUEUE_NAME') or 'adso:importaciones'
    # Las claves privadas solo llegan desde el gestor de secretos del entorno.
    # Push queda apagado hasta que la institución revise el tratamiento de datos.
    WEB_PUSH_ENABLED = (os.getenv('WEB_PUSH_ENABLED') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    VAPID_PUBLIC_KEY = (os.getenv('VAPID_PUBLIC_KEY') or '').strip()
    VAPID_PRIVATE_KEY = (os.getenv('VAPID_PRIVATE_KEY') or '').strip()
    VAPID_SUBJECT = (os.getenv('VAPID_SUBJECT') or '').strip()
