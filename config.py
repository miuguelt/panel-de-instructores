import logging
import os
import secrets

from dotenv import load_dotenv

# Handler a stdout antes de cualquier validacion: sin esto los fallos de arranque
# no aparecen en `docker logs` y el contenedor parece morir en silencio.
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO').upper(),
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
)
log = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# The project .env is authoritative for native Windows development. Keeping
# process variables intact also allows Docker/WSGI deployments to inject their
# own DATABASE_URL when the project .env is intentionally not mounted.
load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)


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


class Config:
    SECRET_KEY = _secret_key
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 5,
        'max_overflow': 5,
        'pool_recycle': 300,
        'pool_pre_ping': True,
        'pool_timeout': 10,
    }
    _upload_folder = os.getenv('UPLOAD_FOLDER', 'uploads')
    UPLOAD_FOLDER = (
        _upload_folder
        if os.path.isabs(_upload_folder)
        else os.path.join(BASE_DIR, _upload_folder)
    )
    MAX_CONTENT_LENGTH = int(os.getenv('MAX_CONTENT_LENGTH', 50 * 1024 * 1024))
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'zip', 'rar', 'xlsx', 'xls', 'doc', 'docx', 'pptx'}
    SMTP_HOST = os.getenv('SMTP_HOST')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USER = os.getenv('SMTP_USER')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
    SMTP_FROM = os.getenv('SMTP_FROM')
    TEMPLATES_AUTO_RELOAD = True
    SEND_FILE_MAX_AGE_DEFAULT = 0
