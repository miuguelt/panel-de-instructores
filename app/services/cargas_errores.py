"""Contrato público de errores de carga, sin detalles internos del servidor."""

from flask import jsonify


class ErrorCarga(Exception):
    def __init__(self, codigo, mensaje, status=422, accion='reintentar', guardado=False):
        super().__init__(mensaje)
        self.codigo = codigo
        self.status = status
        self.accion = accion
        self.guardado = guardado


def respuesta_error(error):
    respuesta = jsonify(ok=False, code=error.codigo, message=str(error), accion=error.accion,
                        guardado=error.guardado, reload=error.status == 401 or error.accion == 'recargar_formulario')
    respuesta.status_code = error.status
    respuesta.headers['Cache-Control'] = 'private, no-store'
    if error.codigo == 'carga_ocupada':
        respuesta.headers['Retry-After'] = '1'
    return respuesta
