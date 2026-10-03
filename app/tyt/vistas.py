"""Authorized group view and private template projection for learner panels."""

from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    has_request_context,
    render_template,
    request,
    session,
)
from flask_login import current_user, login_required
from sqlalchemy import or_

from app import db
from app.models.ficha import Ficha
from app.models.ficha_instructor import FichaInstructor
from app.models.aprendiz import Aprendiz
from app.services.permisos import puede_gestionar_ficha
from app.tyt.avisos import actualizar_avisos
from app.tyt.consulta import obtener_seguimiento


tyt_bp = Blueprint('tyt', __name__)


_SEGUIMIENTO_TYT_AUSENTE = object()


def _obtener_seguimiento_solicitud(ficha):
    """Comparte el informe TyT entre el aviso previo y el render de la página."""
    if not has_request_context():
        return obtener_seguimiento(ficha)

    seguimientos = getattr(g, '_seguimientos_tyt', None)
    if seguimientos is None:
        seguimientos = {}
        g._seguimientos_tyt = seguimientos

    seguimiento = seguimientos.get(ficha.id, _SEGUIMIENTO_TYT_AUSENTE)
    if seguimiento is _SEGUIMIENTO_TYT_AUSENTE:
        try:
            seguimiento = obtener_seguimiento(ficha)
        except Exception as exc:
            # Evita repetir la misma consulta pesada si también se intenta
            # dibujar la tarjeta después de que el cálculo haya fallado.
            seguimientos[ficha.id] = exc
            raise
        seguimientos[ficha.id] = seguimiento

    if isinstance(seguimiento, Exception):
        raise seguimiento
    return seguimiento


@tyt_bp.before_app_request
def revisar_avisos_al_entrar():
    if request.method != 'GET' or request.endpoint not in (
        'instructor.dashboard', 'tyt.detalle', 'aprendiz.panel',
        'instructor.estadisticas', 'instructor.alertas',
    ):
        return
    try:
        fichas = _fichas_autorizadas()
        hubo_cambios = False
        for ficha in fichas:
            hubo_cambios = actualizar_avisos(ficha) or hubo_cambios
        # Confirma antes de que la ruta cargue sus objetos ORM, solo si hubo
        # avisos nuevos; las visitas sin cambios no necesitan una escritura.
        if hubo_cambios:
            db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('No se pudieron actualizar los avisos TyT al entrar.')


def _fichas_autorizadas():
    if request.endpoint == 'instructor.dashboard' and current_user.is_authenticated:
        consulta = Ficha.query
        if not current_user.es_admin:
            consulta = consulta.outerjoin(FichaInstructor).filter(or_(
                Ficha.instructor_id == current_user.id,
                FichaInstructor.instructor_id == current_user.id,
            ))
        return consulta.distinct().all()
    ficha_id = (request.view_args or {}).get('ficha_id')
    ficha = db.session.get(Ficha, ficha_id) if ficha_id else None
    if request.endpoint == 'aprendiz.panel':
        documento = session.get('aprendiz_documento')
        if ficha and documento and session.get('aprendiz_ficha_id') == ficha_id:
            if Aprendiz.query.filter_by(ficha_id=ficha_id, documento=documento).first():
                return [ficha]
        return []
    return [ficha] if puede_gestionar_ficha(ficha) else []


@tyt_bp.app_template_global()
def progreso_tyt(ficha, aprendiz=None):
    if aprendiz is not None:
        autorizado = (aprendiz.ficha_id == ficha.id
                      and session.get('aprendiz_ficha_id') == ficha.id
                      and session.get('aprendiz_documento') == aprendiz.documento)
    else:
        autorizado = puede_gestionar_ficha(ficha)
    if not autorizado:
        return None
    try:
        seguimiento = _obtener_seguimiento_solicitud(ficha)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('No se pudo cargar el seguimiento TyT de la ficha %s.', ficha.id)
        return {'error': True}
    if aprendiz is not None:
        propia = next((a for a in seguimiento['aprendices'] if a['id'] == aprendiz.id), None)
        return {'personal': True, 'propia': propia, 'tiempo': seguimiento['tiempo'],
                'calendario': seguimiento['calendario'],
                'total_resultados': seguimiento['total_resultados'],
                'meta_resultados': seguimiento['meta_resultados']}
    return seguimiento


@tyt_bp.route('/fichas/<int:ficha_id>/seguimiento-tyt')
@login_required
def detalle(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if ficha is None:
        abort(404)
    if not puede_gestionar_ficha(ficha):
        abort(403)
    seguimiento = progreso_tyt(ficha)
    return render_template('tyt/detalle.html', ficha=ficha, tyt=seguimiento)
