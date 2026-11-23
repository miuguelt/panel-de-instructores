"""Acciones de aseo del aprendiz con delegación vigente para administrar la ficha."""

from datetime import date

from flask import flash, redirect, request, url_for

from app import db, limiter
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.services.aseo import (
    ESTADOS_ACTIVOS,
    asignar_o_actualizar_turno,
    completar_turno,
    marcar_no_cumplido,
    reabrir_turno,
    reemplazar_aprendices,
)
from app.services.aseo_vista import completados_del_formulario, fecha_formulario

from . import (
    _actualizar_exclusion,
    _aprendiz_admin_autorizado,
    _aprendiz_de_la_ficha,
    _generar_desde_formulario,
    _guardar_configuracion,
    _turno_de_la_ficha,
    _volver_al_panel_aprendiz,
    aseo_aprendiz_bp,
)


def _origen_actor(actor):
    return 'aprendiz_admin' if actor.rol_administrativo else 'aprendiz'


def _etiqueta_actor(actor):
    if actor.rol_administrativo:
        return f'el aprendiz administrador {actor.nombre_completo}'
    return f'el aprendiz {actor.nombre_completo}'


def _a_la_gestion(ficha_id, mes=None):
    return redirect(url_for('aseo_aprendiz.gestionar', ficha_id=ficha_id, mes=mes))


def _volver_segun_origen(ficha_id, fecha):
    """Regresa a la página desde la que se hizo la acción: panel, transparencia o gestión."""
    origen = request.form.get('origen') or request.args.get('origen')
    mes = fecha.strftime('%Y-%m')
    if origen == 'panel':
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))
    if origen == 'transparencia':
        return redirect(url_for('aseo_aprendiz.transparencia', ficha_id=ficha_id, mes=mes))
    return _a_la_gestion(ficha_id, mes)


def _turno_delegado(ficha_id, turno_id):
    """(actor, turno) si el aprendiz tiene la delegación y el turno es de su ficha."""
    actor = _aprendiz_admin_autorizado(ficha_id)
    turno = _turno_de_la_ficha(ficha_id, turno_id)
    return (actor, turno) if actor and turno else (None, None)


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/generar', methods=['POST'])
@limiter.limit('20 per minute')
def generar_como_aprendiz(ficha_id):
    actor = _aprendiz_admin_autorizado(ficha_id)
    if not db.session.get(Ficha, ficha_id) or not actor:
        flash('No tienes permiso para generar turnos de aseo en esta ficha.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)
    try:
        inicio, mensaje, categoria = _generar_desde_formulario(ficha_id, generado_por=_origen_actor(actor))
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return _a_la_gestion(ficha_id)
    flash(mensaje, categoria)
    return _volver_segun_origen(ficha_id, inicio)


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/<int:turno_id>/cumplir', methods=['POST'])
@limiter.limit('30 per minute')
def cumplir_como_aprendiz(ficha_id, turno_id):
    actor, turno = _turno_delegado(ficha_id, turno_id)
    if not turno:
        flash('No tienes permiso para marcar ese turno.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)
    completado_1, completado_2 = completados_del_formulario(request.form)
    completar_turno(turno, completado_1=completado_1, completado_2=completado_2)
    db.session.commit()
    flash('Turno de aseo marcado como cumplido.', 'success')
    return _volver_segun_origen(ficha_id, turno.fecha)


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/<int:turno_id>/no-cumplir', methods=['POST'])
@limiter.limit('30 per minute')
def no_cumplir_como_aprendiz(ficha_id, turno_id):
    actor, turno = _turno_delegado(ficha_id, turno_id)
    if not turno:
        flash('No tienes permiso para marcar ese turno.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)
    marcar_no_cumplido(turno, observacion=request.form.get('observacion', '').strip() or None)
    db.session.commit()
    flash('Turno marcado como no cumplido. Se reprogramó la reposición.', 'info')
    return _volver_segun_origen(ficha_id, turno.fecha)


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/<int:turno_id>/reabrir', methods=['POST'])
@limiter.limit('30 per minute')
def reabrir_como_aprendiz(ficha_id, turno_id):
    actor, turno = _turno_delegado(ficha_id, turno_id)
    if not turno:
        flash('No tienes permiso para modificar ese turno.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)
    reabrir_turno(turno)
    db.session.commit()
    flash('Turno reabierto y restablecido a estado programado.', 'success')
    return _volver_segun_origen(ficha_id, turno.fecha)


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/<int:turno_id>/editar', methods=['POST'])
@limiter.limit('30 per minute')
def editar_como_aprendiz(ficha_id, turno_id):
    actor, turno = _turno_delegado(ficha_id, turno_id)
    if not turno:
        flash('No tienes permiso para editar ese turno.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)
    aprendiz_1 = _aprendiz_de_la_ficha(ficha_id, 'aprendiz_1_id')
    aprendiz_2 = _aprendiz_de_la_ficha(ficha_id, 'aprendiz_2_id')
    if not aprendiz_1 or not aprendiz_2:
        flash('Selecciona dos aprendices válidos de esta ficha.', 'error')
        return _a_la_gestion(ficha_id)
    try:
        reemplazar_aprendices(
            turno,
            aprendiz_1,
            aprendiz_2,
            request.form.get('observacion', '').strip(),
            origen=_origen_actor(actor),
            actor_label=_etiqueta_actor(actor),
        )
        db.session.commit()
        flash('La asignación del turno fue actualizada.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _a_la_gestion(ficha_id, turno.fecha.strftime('%Y-%m'))


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/asignar', methods=['POST'])
@limiter.limit('30 per minute')
def asignar_como_aprendiz(ficha_id):
    actor = _aprendiz_admin_autorizado(ficha_id)
    if not db.session.get(Ficha, ficha_id) or not actor:
        flash('No tienes permiso para asignar turnos de aseo.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)
    try:
        fecha = fecha_formulario(request.form.get('fecha'), 'fecha')
        asignar_o_actualizar_turno(
            ficha_id=ficha_id,
            fecha=fecha,
            aprendiz_1_id=request.form.get('aprendiz_1_id', type=int),
            aprendiz_2_id=request.form.get('aprendiz_2_id', type=int),
            observacion=request.form.get('observacion', '').strip(),
            origen=_origen_actor(actor),
            actor_label=_etiqueta_actor(actor),
        )
        db.session.commit()
        flash(f'Turno asignado para el {fecha.strftime("%d/%m/%Y")}.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _a_la_gestion(ficha_id, request.form.get('fecha', '')[:7] or date.today().strftime('%Y-%m'))


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/config', methods=['POST'])
@limiter.limit('30 per minute')
def configurar_como_aprendiz(ficha_id):
    if not db.session.get(Ficha, ficha_id) or not _aprendiz_admin_autorizado(ficha_id):
        flash('Debes pertenecer a esta ficha para configurar los turnos de aseo.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)
    try:
        _guardar_configuracion(ficha_id)
        flash('Configuración de turnos de aseo actualizada.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    return _a_la_gestion(ficha_id)


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/exclusion/<int:aprendiz_id>', methods=['POST'])
@limiter.limit('30 per minute')
def excluir_como_aprendiz(ficha_id, aprendiz_id):
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if (
        not db.session.get(Ficha, ficha_id)
        or not _aprendiz_admin_autorizado(ficha_id)
        or not aprendiz
        or aprendiz.ficha_id != ficha_id
        or aprendiz.estado not in ESTADOS_ACTIVOS
        or not aprendiz.activo
    ):
        flash('Aprendiz no encontrado o no tienes permiso para esta ficha.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)
    try:
        if not _actualizar_exclusion(ficha_id, aprendiz):
            flash('No se pudo cargar la disponibilidad de este aprendiz.', 'error')
            return _a_la_gestion(ficha_id)
    except ValueError as exc:
        flash(str(exc), 'error')
        return _a_la_gestion(ficha_id)
    return _a_la_gestion(ficha_id, request.args.get('mes') or date.today().strftime('%Y-%m'))
