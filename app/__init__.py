import os

from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import Config
from app.helpers import strip_document_id

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
    limiter.init_app(app)

    from app.routes.auth import auth_bp
    from app.routes.instructor import instructor_bp
    from app.routes.aprendiz import aprendiz_bp
    from app.routes.api import api_bp
    from app.routes.ranking import ranking_bp
    from app.routes.aseo import aseo_bp, aseo_aprendiz_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(instructor_bp, url_prefix='/instructor')
    app.register_blueprint(aprendiz_bp, url_prefix='/aprendiz')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(ranking_bp, url_prefix='/instructor')
    app.register_blueprint(aseo_bp, url_prefix='/instructor')
    app.register_blueprint(aseo_aprendiz_bp, url_prefix='/aprendiz')

    from app.routes.seguimiento import seguimiento_bp, aprendiz_seguimiento_bp
    app.register_blueprint(seguimiento_bp, url_prefix='/instructor')
    app.register_blueprint(aprendiz_seguimiento_bp, url_prefix='/aprendiz')

    @app.context_processor
    def inyectar_notificaciones():
        from datetime import datetime
        no_leidas = 0
        if current_user.is_authenticated:
            from app.models.alertas import Notificacion
            no_leidas = Notificacion.query.filter_by(
                destinatario_tipo='instructor',
                destinatario_id=current_user.id,
                leida=False,
            ).count()
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
