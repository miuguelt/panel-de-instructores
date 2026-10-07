"""API privada para adaptar la experiencia del panel al aprendiz autenticado."""

from flask import Blueprint, current_app, jsonify, request
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import RequestEntityTooLarge

from app import db
from app.features.experiencia_aprendiz.service import guardar_experiencia, leer_experiencia
from app.features.personalizacion_aprendiz.routes import aprendiz_autorizado, csrf_invalido, problema
from app.features.personalizacion_aprendiz.service import ConflictoPersonalizacion


experiencia_aprendiz_bp = Blueprint('experiencia_aprendiz', __name__, url_prefix='/aprendiz')
experiencia_aprendiz_bp.register_error_handler(CSRFError, csrf_invalido)


@experiencia_aprendiz_bp.route('/<int:ficha_id>/experiencia', methods=['GET', 'POST'])
def preferencias(ficha_id):
    """Lee o guarda la experiencia con contexto de pestaña y revisión persistida."""
    try:
        aprendiz, error = aprendiz_autorizado(ficha_id)
        if error is not None:
            return error
        if request.method == 'GET':
            return jsonify(ok=True, **leer_experiencia(aprendiz.id))
        if request.headers.get('X-Learner-Id') is None:
            raise ValueError('Recarga el panel para identificar la pestaña antes de guardar.')
        if request.content_length and request.content_length > 8192:
            raise ValueError('Las preferencias son demasiado extensas. Recarga el panel.')
        datos = request.get_json(silent=True)
        if not isinstance(datos, dict) or set(datos) != {'preferences', 'revision'}:
            raise ValueError('Envía únicamente las preferencias y la revisión del panel en formato JSON.')
        estado = guardar_experiencia(aprendiz.id, datos['preferences'], datos['revision'], ficha_id)
        return jsonify(ok=True, **estado)
    except ConflictoPersonalizacion as exc:
        return problema(str(exc), 409)
    except ValueError as exc:
        return problema(str(exc), 400)
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.error('No se pudo consultar o guardar la experiencia (%s).', type(exc).__name__)
        return problema('No se pudo confirmar el guardado. Consulta tus preferencias antes de intentarlo de nuevo.', 503)


@experiencia_aprendiz_bp.errorhandler(RequestEntityTooLarge)
def preferencias_demasiado_extensas(_error):
    return problema('Las preferencias superan el tamaño permitido. Recarga el panel.', 413)
