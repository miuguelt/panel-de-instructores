import os
from dotenv import load_dotenv

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
if os.getenv('FLASK_ENV') == 'production' and _secret_key in _INSECURE_SECRETS:
    raise RuntimeError(
        'SECRET_KEY insegura o vacia con FLASK_ENV=production. '
        'Defina SECRET_KEY con un valor aleatorio largo.'
    )


# Priority: DATABASE_URL_B64 > DATABASE_URL_FILE > Docker secret > DATABASE_URL
_db_url = None

_b64 = os.getenv('DATABASE_URL_B64')
if _b64:
    import base64
    _b64_padded = _b64 + '=' * ((4 - len(_b64) % 4) % 4)
    _db_url = base64.b64decode(_b64_padded).decode()

if not _db_url:
    _db_url_file = os.getenv('DATABASE_URL_FILE')
    if _db_url_file and os.path.isfile(_db_url_file):
        with open(_db_url_file) as _f:
            _db_url = _f.read().strip()

if not _db_url:
    for _secret in ('/run/secrets/DATABASE_URL', '/run/secrets/db_url'):
        if os.path.isfile(_secret):
            with open(_secret) as _f:
                _db_url = _f.read().strip()
            break

if not _db_url:
    _db_url = os.getenv('DATABASE_URL')

if not _db_url:
    _db_url = 'postgresql://adso:adso_pass@127.0.0.1:5434/adso_control'


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
