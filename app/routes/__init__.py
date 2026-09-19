"""Register independent route groups while preserving startup diagnostics."""

from importlib import import_module


def registrar_rutas(app):
    rutas = (
        ('auth', 'auth_bp', None), ('api', 'api_bp', '/api'),
        ('instructor', 'instructor_bp', '/instructor'),
        ('planeacion', 'planeacion_bp', '/instructor'),
        ('ranking', 'ranking_bp', '/instructor'), ('aseo', 'aseo_bp', '/instructor'),
        ('seguimiento', 'seguimiento_bp', '/instructor'),
        ('aprendiz', 'aprendiz_bp', '/aprendiz'),
        ('aseo', 'aseo_aprendiz_bp', '/aprendiz'),
        ('seguimiento', 'aprendiz_seguimiento_bp', '/aprendiz'),
        ('app.tyt.vistas', 'tyt_bp', '/instructor'),
    )
    for modulo, nombre, prefijo in rutas:
        ruta = modulo if modulo.startswith('app.') else f'app.routes.{modulo}'
        try:
            app.register_blueprint(getattr(import_module(ruta), nombre), url_prefix=prefijo)
        except Exception as exc:
            app.config['STARTUP_ERRORS'].append(f'{ruta}: {type(exc).__name__}: {exc}')
            app.logger.exception('Fallo al registrar blueprints de %s', ruta)
