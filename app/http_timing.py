"""Mide trabajo HTTP y SQL sin registrar consultas, credenciales ni datos personales."""

from time import perf_counter
from weakref import ref

from flask import current_app, g, has_request_context, request
from sqlalchemy import event


def registrar_tiempos_http(app, db):
    """Instala medición por petición y por motor; las descargas conservan su flujo."""
    aplicacion = ref(app)

    @app.before_request
    def iniciar_peticion():
        if request.endpoint != 'static':
            g.http_timing = {'inicio': perf_counter(), 'sql_ms': 0.0, 'consultas': 0}

    def antes_sql(conn, cursor, statement, parameters, context, executemany):
        if has_request_context() and current_app._get_current_object() is aplicacion():
            tiempos = getattr(g, 'http_timing', None)
            if tiempos is not None:
                context.http_sql_inicio = perf_counter()
                tiempos['consultas'] += 1

    def despues_sql(conn, cursor, statement, parameters, context, executemany):
        inicio = getattr(context, 'http_sql_inicio', None)
        if inicio is not None and has_request_context() and current_app._get_current_object() is aplicacion():
            tiempos = getattr(g, 'http_timing', None)
            if tiempos is not None:
                tiempos['sql_ms'] += (perf_counter() - inicio) * 1000

    with app.app_context():
        event.listen(db.engine, 'before_cursor_execute', antes_sql)
        event.listen(db.engine, 'after_cursor_execute', despues_sql)

    @app.after_request
    def finalizar_peticion(response):
        tiempos = getattr(g, 'http_timing', None)
        if tiempos is None or request.endpoint == 'static':
            return response
        total_ms = (perf_counter() - tiempos['inicio']) * 1000
        response.headers.add('Server-Timing', (
            f'app;dur={total_ms:.2f}, sql;dur={tiempos["sql_ms"]:.2f}, '
            f'sql_queries;desc="{tiempos["consultas"]}"'
        ))
        if total_ms >= app.config['HTTP_SLOW_REQUEST_MS']:
            app.logger.warning(
                'HTTP lento method=%s route=%s status=%s total_ms=%.2f sql_ms=%.2f sql_queries=%s bytes=%s',
                request.method, request.url_rule.rule if request.url_rule else '(sin ruta)',
                response.status_code, total_ms, tiempos['sql_ms'], tiempos['consultas'],
                response.content_length if not response.is_streamed else 'stream',
            )
        return response
