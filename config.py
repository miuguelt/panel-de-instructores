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
_secret_key = os.getenv('SECRET_KEY', 'dev-key-change-me')
SECRET_KEY_IS_EPHEMERAL = False
if os.getenv('FLASK_ENV') == 'production' and _secret_key in _INSECURE_SECRETS:
    # No abortar el proceso: una excepcion aqui mata a gunicorn en el arranque y
    # el contenedor entra en bucle de reinicios sin dejar rastro legible. Se
    # degrada a una clave efimera (mas segura que un default conocido) y se
    # registra el fallo de forma muy visible en los logs del contenedor.
    SECRET_KEY_IS_EPHEMERAL = True
    _secret_key = secrets.token_hex(64)
    log.critical(
        'SECRET_KEY insegura o vacia con FLASK_ENV=production. '
        'Se genero una clave EFIMERA: las sesiones se invalidaran en cada reinicio. '
        'Defina SECRET_KEY en Coolify con un valor aleatorio largo y SIN el caracter "$" '
        '(Docker Compose lo expande y vacia el valor).'
    )


def _normalize_db_url(url):
    """La imagen solo trae psycopg2-binary; el esquema psycopg 3 rompe SQLAlchemy."""
    if url.startswith('postgresql+psycopg://'):
        return 'postgresql+psycopg2://' + url[len('postgresql+psycopg://'):]
    return url


_db_url = _normalize_db_url(
    os.getenv('DATABASE_URL') or 'postgresql://adso:adso_pass@127.0.0.1:5434/adso_control'
)


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
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # El pool es por proceso worker. Con gunicorn en modo gthread cada worker
    # atiende GUNICORN_THREADS peticiones a la vez, asi que pool_size debe
    # cubrir esos hilos o los ultimos se quedan esperando hasta pool_timeout.
    # Techo de conexiones = WEB_CONCURRENCY * (pool_size + max_overflow);
    # mantenerlo por debajo de max_connections de PostgreSQL.
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': _env_int('DB_POOL_SIZE', 8, minimum=1),
        'max_overflow': _env_int('DB_MAX_OVERFLOW', 4, minimum=0),
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
    MAX_CONTENT_LENGTH = _env_int('MAX_CONTENT_LENGTH', 50 * 1024 * 1024, minimum=1)
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'zip', 'rar', 'xlsx', 'xls', 'doc', 'docx', 'pptx'}
    SMTP_HOST = os.getenv('SMTP_HOST')
    SMTP_PORT = _env_int('SMTP_PORT', 587, minimum=1, maximum=65535)
    SMTP_USER = os.getenv('SMTP_USER')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
    SMTP_FROM = os.getenv('SMTP_FROM')
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
