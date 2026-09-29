"""Rutas de trabajo colaborativo para aprendices."""

from flask import Blueprint, jsonify, request

from app import db
from app.models.grupo import Grupo, GrupoAprendiz, GrupoMensaje
from app.services.permisos import aprendiz_de_sesion


grupo_aprendiz_bp = Blueprint('grupo_aprendiz', __name__)

MAX_MENSAJES_POR_SOLICITUD = 100


def _obtener_grupo_y_aprendiz(ficha_id):
    """Devuelve la identidad de sesión y un grupo activo al que pertenece."""
    aprendiz = aprendiz_de_sesion(ficha_id)
    if not aprendiz:
        return None, None

    grupo = (
        Grupo.query
        .join(GrupoAprendiz, GrupoAprendiz.grupo_id == Grupo.id)
        .filter(
            Grupo.ficha_id == ficha_id,
            Grupo.activo.is_(True),
            GrupoAprendiz.aprendiz_id == aprendiz.id,
        )
        .order_by(Grupo.id.asc())
        .first()
    )
    return aprendiz, grupo


def _representar_mensaje(mensaje, aprendiz_id):
    """Serializa un mensaje sin delegar el escape del contenido al servidor."""
    return {
        'id': mensaje.id,
        'contenido': mensaje.contenido,
        'autor': mensaje.aprendiz.nombre_completo,
        'creado_en': mensaje.creado_en.isoformat() if mensaje.creado_en else None,
        'propio': mensaje.aprendiz_id == aprendiz_id,
    }


@grupo_aprendiz_bp.route(
    '/aprendiz/<int:ficha_id>/grupo/mensajes',
    methods=['GET', 'POST'],
)
def mensajes(ficha_id):
    """Consulta mensajes incrementales o publica uno para el grupo activo."""
    aprendiz, grupo = _obtener_grupo_y_aprendiz(ficha_id)
    if not aprendiz or not grupo:
        return jsonify({'error': 'No tienes acceso a este grupo.'}), 404

    if request.method == 'GET':
        try:
            despues_id = int(request.args.get('despues_id', '0'))
        except (TypeError, ValueError):
            return jsonify({'error': 'El identificador del último mensaje no es válido.'}), 400
        if despues_id < 0:
            return jsonify({'error': 'El identificador del último mensaje no es válido.'}), 400

        consulta = GrupoMensaje.query.filter_by(grupo_id=grupo.id)
        if despues_id > 0:
            mensajes_grupo = (
                consulta
                .filter(GrupoMensaje.id > despues_id)
                .order_by(GrupoMensaje.id.asc())
                .limit(MAX_MENSAJES_POR_SOLICITUD)
                .all()
            )
        else:
            mensajes_grupo = (
                consulta
                .order_by(GrupoMensaje.id.desc())
                .limit(MAX_MENSAJES_POR_SOLICITUD)
                .all()
            )
            mensajes_grupo.reverse()
        return jsonify({
            'messages': [
                _representar_mensaje(mensaje, aprendiz.id)
                for mensaje in mensajes_grupo
            ],
        })

    datos = request.get_json(silent=True) if request.is_json else request.form
    contenido = (
        datos.get('contenido')
        if datos is not None and hasattr(datos, 'get')
        else None
    )
    if not isinstance(contenido, str):
        return jsonify({'error': 'Escribe un mensaje antes de enviarlo.'}), 400
    contenido = contenido.strip()
    if not contenido or len(contenido) > 1200:
        return jsonify({
            'error': 'El mensaje debe tener entre 1 y 1200 caracteres.',
        }), 400

    mensaje = GrupoMensaje(
        grupo_id=grupo.id,
        aprendiz_id=aprendiz.id,
        contenido=contenido,
    )
    db.session.add(mensaje)
    db.session.commit()
    return jsonify({'message': _representar_mensaje(mensaje, aprendiz.id)}), 201
