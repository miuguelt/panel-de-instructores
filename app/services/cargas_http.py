"""Respuestas de carga que conservan los mensajes y evitan redirecciones XHR."""

from urllib.parse import urlsplit

from flask import g, jsonify, request, session, url_for


def es_carga_xhr():
    """Identifica una carga sin leer ni consumir su cuerpo multipart."""
    return (request.method == 'POST' and request.mimetype == 'multipart/form-data'
            and request.headers.get('X-Requested-With') == 'XMLHttpRequest')


def registrar_respuestas_carga(app):
    """Adapta los formularios existentes al contrato de progreso del navegador."""
    @app.before_request
    def recordar_mensajes():
        if es_carga_xhr():
            g.carga_mensajes_previos = len(session.get('_flashes', []))

    @app.after_request
    def responder_carga(respuesta):
        if not es_carga_xhr():
            return respuesta
        mensajes = list(session.get('_flashes', []))
        anteriores = getattr(g, 'carga_mensajes_previos', 0)
        nuevos = mensajes[anteriores:]
        if respuesta.is_json:
            if respuesta.status_code >= 400 and nuevos:
                # El cliente ya muestra este error; no debe reaparecer después
                # de que la persona corrija el archivo y complete la carga.
                session['_flashes'] = mensajes[:anteriores]
            respuesta.headers.setdefault('Cache-Control', 'private, no-store')
            return respuesta
        errores = [texto for categoria, texto in nuevos if categoria in {'error', 'danger'}]
        estado = respuesta.status_code
        destino = respuesta.headers.get('Location', '')
        if estado in {301, 302, 303, 307, 308}:
            requiere_sesion = urlsplit(destino).path == url_for('auth.login')
            if errores or requiere_sesion:
                session['_flashes'] = mensajes[:anteriores]
                resultado = jsonify(ok=False, message=(
                    'Tu sesión expiró. Inicia sesión de nuevo antes de cargar el archivo.'
                    if requiere_sesion else ' '.join(texto for _, texto in nuevos)
                ), reload=requiere_sesion)
                resultado.status_code = 401 if requiere_sesion else 422
            else:
                # El GET de destino consumirá los mensajes una sola vez.
                resultado = jsonify(ok=True, message=' '.join(texto for _, texto in nuevos), redirect=destino)
        elif estado >= 400:
            mensajes_http = {
                400: 'No se pudo leer la carga. Recarga el formulario y selecciona nuevamente el archivo.',
                401: 'Tu sesión expiró. Inicia sesión de nuevo antes de cargar el archivo.',
                403: 'No tienes permiso para cargar archivos en esta sección. Revisa tu sesión o consulta con tu instructor.',
                404: 'El destino de la carga ya no está disponible. Recarga la página y selecciona la actividad.',
                413: 'La carga supera el límite permitido. Reduce el tamaño del archivo e inténtalo de nuevo.',
                429: 'Hay demasiados intentos seguidos. Espera un minuto y vuelve a intentarlo.',
                503: 'El servicio de carga no está disponible. Comprueba si el archivo quedó registrado antes de volver a intentarlo.',
            }
            resultado = jsonify(ok=False, message=mensajes_http.get(estado,
                'No se pudo confirmar la carga. Revisa si el archivo quedó registrado antes de volver a intentarlo.'))
            resultado.status_code = estado
            if respuesta.headers.get('Retry-After'):
                resultado.headers['Retry-After'] = respuesta.headers['Retry-After']
        else:
            return respuesta
        resultado.headers['Cache-Control'] = 'private, no-store'
        return resultado

