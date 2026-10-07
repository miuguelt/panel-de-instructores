"""Rutas privadas de personalización, identificadas solo por la sesión del aprendiz."""

from flask import Blueprint, Response, current_app, jsonify, request, url_for
from flask_wtf.csrf import CSRFError
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import RequestEntityTooLarge

from app import db
from app.services.permisos import aprendiz_de_sesion
from app.features.personalizacion_aprendiz.service import (
    ConflictoPersonalizacion, FotoDemasiadoGrande, guardar_personalizacion,
    normalizar_foto, obtener_personalizacion, preferencias_publicas,
    validar_preferencias, validar_revision,
)


personalizacion_aprendiz_bp = Blueprint('personalizacion_aprendiz', __name__, url_prefix='/aprendiz')


def problema(detalle, estado):
    """Errores verificables por el cliente sin exponer detalles internos de la base de datos."""
    titulos = {400: 'Revisa la personalización', 401: 'Inicia sesión de nuevo',
               403: 'Acceso no disponible', 404: 'Foto no disponible',
               409: 'Las preferencias cambiaron', 413: 'La foto es demasiado grande',
               503: 'No se pudo guardar o consultar el panel'}
    respuesta = jsonify(ok=False, error=detalle, detail=detalle, title=titulos[estado],
                        status=estado, type='about:blank', instance=request.path)
    respuesta.status_code = estado
    respuesta.mimetype = 'application/problem+json'
    respuesta.headers['Cache-Control'] = 'private, no-store, max-age=0'
    return respuesta


def respuesta_preferencias(registro, ficha_id):
    """El cliente recibe la revisión persistida y una URL privada de foto."""
    revision = registro.revision if registro else 0
    return jsonify(
        ok=True, preferences=preferencias_publicas(registro), revision=revision,
        configured=registro is not None,
        photoUrl=(url_for('personalizacion_aprendiz.foto', ficha_id=ficha_id, v=revision,
                          learner=registro.aprendiz_id)
                  if registro and registro.foto else None),
    )


def aprendiz_autorizado(ficha_id):
    """La identidad proviene de la sesión y debe corresponder a un aprendiz activo."""
    aprendiz = aprendiz_de_sesion(ficha_id)
    if aprendiz is None:
        return None, problema('Tu sesión no está disponible para esta ficha. Inicia sesión de nuevo.', 401)
    if not aprendiz.activo:
        return None, problema('Tu acceso está deshabilitado. Consulta con tu instructor.', 403)
    error = validar_contexto_aprendiz(aprendiz.id, request.headers.get('X-Learner-Id'))
    if error is not None:
        return None, error
    return aprendiz, None


def validar_contexto_aprendiz(aprendiz_id, esperado):
    """Detecta una pestaña antigua sin usar el ID esperado para decidir la identidad."""
    if esperado is None:
        return None
    if (not esperado.isascii() or not esperado.isdigit() or len(esperado) > 20
            or int(esperado) < 1):
        return problema('El contexto del panel no es válido. Recarga la página.', 400)
    if int(esperado) != aprendiz_id:
        return problema('La sesión cambió de aprendiz. Recarga el panel antes de continuar.', 401)
    return None


@personalizacion_aprendiz_bp.route('/<int:ficha_id>/personalizacion', methods=['GET', 'POST'])
def preferencias(ficha_id):
    """Lee o guarda el panel completo con control de concurrencia y validación estricta."""
    try:
        aprendiz, error = aprendiz_autorizado(ficha_id)
        if error is not None:
            return error
        if request.method == 'GET':
            return respuesta_preferencias(obtener_personalizacion(aprendiz.id), ficha_id)
        permitidos = {'preferences', 'revision', 'remove_photo', 'csrf_token'}
        if request.is_json or set(request.form) - permitidos or set(request.files) - {'photo'}:
            raise ValueError('Envía únicamente las opciones de personalización del panel.')
        if any(len(request.form.getlist(campo)) != 1 for campo in request.form):
            raise ValueError('Cada opción del formulario debe enviarse una sola vez.')
        if len(request.files.getlist('photo')) > 1:
            raise ValueError('Selecciona una sola foto para tu perfil.')
        preferencias_nuevas = validar_preferencias(request.form.get('preferences'))
        revision = validar_revision(request.form.get('revision'))
        quitar = request.form.get('remove_photo', 'false')
        if quitar not in ('true', 'false'):
            raise ValueError('La solicitud para quitar la foto no es válida.')
        archivo = request.files.get('photo')
        if archivo is not None and quitar == 'true':
            raise ValueError('Elige subir una foto o quitar la actual en un solo guardado.')
        foto_nueva = normalizar_foto(archivo) if archivo is not None else None
        registro = guardar_personalizacion(
            aprendiz.id, preferencias_nuevas, revision, foto_nueva, quitar == 'true',
        )
        return respuesta_preferencias(registro, ficha_id)
    except ConflictoPersonalizacion as exc:
        return problema(str(exc), 409)
    except FotoDemasiadoGrande as exc:
        return problema(str(exc), 413)
    except ValueError as exc:
        return problema(str(exc), 400)
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.error('No se pudo consultar o guardar la personalización (%s).', type(exc).__name__)
        return problema('No se pudo confirmar el guardado. Vuelve a consultar tus preferencias antes de intentarlo de nuevo.', 503)


@personalizacion_aprendiz_bp.get('/<int:ficha_id>/personalizacion/foto')
def foto(ficha_id):
    """Sirve exclusivamente la foto del aprendiz autenticado, sin caché compartida."""
    try:
        aprendiz, error = aprendiz_autorizado(ficha_id)
        if error is not None:
            return error
        error = validar_contexto_aprendiz(aprendiz.id, request.args.get('learner'))
        if error is not None:
            return error
        registro = obtener_personalizacion(aprendiz.id)
        if registro is None or not registro.foto:
            return problema('Todavía no tienes una foto guardada en tu panel.', 404)
        respuesta = Response(registro.foto, mimetype='image/jpeg')
        respuesta.headers['Cache-Control'] = 'private, no-store, max-age=0'
        respuesta.headers['X-Content-Type-Options'] = 'nosniff'
        return respuesta
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.error('No se pudo consultar la foto del aprendiz (%s).', type(exc).__name__)
        return problema('No se pudo consultar tu foto. Vuelve a intentarlo.', 503)


@personalizacion_aprendiz_bp.errorhandler(CSRFError)
def csrf_invalido(_error):
    return problema('La sesión del formulario expiró. Recarga el panel y vuelve a intentarlo.', 400)


@personalizacion_aprendiz_bp.errorhandler(RequestEntityTooLarge)
def carga_demasiado_grande(_error):
    return problema('La foto supera el tamaño permitido. Elige una imagen de hasta 2 MiB.', 413)
