"""API de recepción privada: cada solicitud vuelve a verificar permisos."""

from flask import Blueprint, current_app, jsonify, request

from app import db, limiter
from app.services.cargas_bloqueos import bloquear
from app.services.cargas_errores import ErrorCarga, respuesta_error
from app.services.cargas_transferencia import (
    cancelar_carga, consultar_carga, estado_carga, iniciar_carga, recibir_bloque,
)

cargas_bp = Blueprint('cargas', __name__)


@cargas_bp.before_request
def comprobar_disponibilidad():
    if not current_app.config.get('CARGAS_REANUDABLES_ENABLED'):
        raise ErrorCarga('cargas_no_disponibles', 'La carga reanudable todavía no está habilitada.', 503)


@cargas_bp.errorhandler(ErrorCarga)
def error_carga(error):
    db.session.rollback()
    return respuesta_error(error)


@cargas_bp.errorhandler(OSError)
def error_disco(error):
    db.session.rollback()
    current_app.logger.exception('No se pudo escribir un bloque de carga.')
    return respuesta_error(ErrorCarga('fallo_almacenamiento', 'El servidor no pudo guardar el bloque. Conservamos el avance confirmado; intente continuar.', 507))


@cargas_bp.route('/cargas', methods=['POST'])
@limiter.limit('30 per minute')
def iniciar():
    carga = iniciar_carga(request.get_json(silent=True), request.headers.get('Idempotency-Key'))
    respuesta = jsonify(estado_carga(carga))
    respuesta.status_code = 201
    respuesta.headers['Cache-Control'] = 'private, no-store'
    return respuesta


@cargas_bp.route('/cargas/<identificador>', methods=['GET', 'PATCH', 'DELETE'])
@limiter.limit('600 per minute')
def transferir(identificador):
    if len(identificador) != 32 or any(c not in '0123456789abcdef' for c in identificador):
        raise ErrorCarga('carga_no_encontrada', 'No encontramos esta carga.', 404)
    with bloquear(identificador):
        carga = consultar_carga(identificador)
        if request.method == 'PATCH':
            if request.mimetype != 'application/octet-stream':
                raise ErrorCarga('bloque_invalido', 'El bloque no tiene el formato esperado.')
            try:
                offset = int(request.headers.get('Upload-Offset', ''))
            except ValueError as exc:
                raise ErrorCarga('desfase', 'No se recibió la posición del bloque.', 409, 'consultar') from exc
            carga = recibir_bloque(carga, request.stream, offset,
                request.headers.get('X-Chunk-SHA256'), request.content_length)
        if request.method == 'DELETE':
            resultado = cancelar_carga(carga)
        else:
            resultado = estado_carga(carga)
        respuesta = jsonify(resultado)
        respuesta.headers['Cache-Control'] = 'private, no-store'
        return respuesta


@cargas_bp.route('/cargas/<identificador>/reintentar', methods=['POST'])
@limiter.limit('10 per minute')
def reintentar(identificador):
    from app.services.cargas_trabajos import reintentar_envio
    carga = consultar_carga(identificador)
    with bloquear('trabajo-' + carga.envio_id if carga.envio_id else carga.id):
        return jsonify(reintentar_envio(carga)), 202
