"""Authorized group view and private template projection for learner panels."""

from flask import Blueprint, abort, current_app, render_template, request, session
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


@tyt_bp.before_app_request
def revisar_avisos_al_entrar():
    if request.method != 'GET' or request.endpoint not in (
        'instructor.dashboard', 'tyt.detalle', 'aprendiz.panel',
        'instructor.estadisticas', 'instructor.alertas',
    ):
        return
    try:
        fichas = _fichas_autorizadas()
        for ficha in fichas:
            actualizar_avisos(ficha)
        # Commit before the route loads its ORM objects, never while rendering.
        if fichas:
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
        seguimiento = obtener_seguimiento(ficha)
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
