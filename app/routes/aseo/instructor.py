"""Calendario de aseo que administra el instructor de la ficha."""

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from app import db
from app.models.aprendiz import Aprendiz
from app.services.aseo import (
    completar_turno,
    marcar_no_cumplido,
    obtener_configuracion,
    reabrir_turno,
    reemplazar_aprendices,
)
from app.services.aseo_vista import completados_del_formulario

from . import (
    _actualizar_exclusion,
    _aprendiz_de_la_ficha,
    _contexto_calendario,
    _ficha_autorizada,
    _generar_desde_formulario,
    _guardar_configuracion,
    _turno_de_la_ficha,
    aseo_bp,
)


def _al_calendario(ficha_id, fecha=None):
    return redirect(url_for('aseo.turnos', ficha_id=ficha_id, mes=fecha.strftime('%Y-%m') if fecha else None))


def _turno_autorizado(ficha_id, turno_id):
    return _turno_de_la_ficha(ficha_id, turno_id) if _ficha_autorizada(ficha_id) else None


@aseo_bp.route('/fichas/<int:ficha_id>/turnos-aseo')
@login_required
def turnos(ficha_id):
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    config = obtener_configuracion(ficha_id)
    return render_template('turnos_aseo.html', ficha=ficha, config=config, **_contexto_calendario(ficha_id))


@aseo_bp.route('/fichas/<int:ficha_id>/turnos-aseo/generar', methods=['POST'])
@login_required
def generar(ficha_id):
    if not _ficha_autorizada(ficha_id):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    try:
        inicio, mensaje, categoria = _generar_desde_formulario(ficha_id, generado_por='sistema')
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return _al_calendario(ficha_id)
    flash(mensaje, categoria)
    return _al_calendario(ficha_id, inicio)


@aseo_bp.route('/fichas/<int:ficha_id>/turnos-aseo/<int:turno_id>/cumplir', methods=['POST'])
@login_required
def cumplir(ficha_id, turno_id):
    turno = _turno_autorizado(ficha_id, turno_id)
    if not turno:
        flash('Turno no encontrado.', 'error')
        return redirect(url_for('instructor.dashboard'))
    completado_1, completado_2 = completados_del_formulario(request.form)
    completar_turno(turno, completado_1=completado_1, completado_2=completado_2)
    db.session.commit()
    flash('Turno guardado como cumplido. Los contadores quedaron actualizados.', 'success')
    return _al_calendario(ficha_id, turno.fecha)


@aseo_bp.route('/fichas/<int:ficha_id>/turnos-aseo/<int:turno_id>/no-cumplir', methods=['POST'])
@login_required
def no_cumplir(ficha_id, turno_id):
    turno = _turno_autorizado(ficha_id, turno_id)
    if not turno:
        flash('Turno no encontrado.', 'error')
        return redirect(url_for('instructor.dashboard'))
    marcar_no_cumplido(turno, observacion=request.form.get('observacion', '').strip() or None)
    db.session.commit()
    flash('Turno marcado como no cumplido. Se reprogramó la reposición correspondiente '
          'en la siguiente fecha disponible.', 'info')
    return _al_calendario(ficha_id, turno.fecha)


@aseo_bp.route('/fichas/<int:ficha_id>/turnos-aseo/<int:turno_id>/reabrir', methods=['POST'])
@login_required
def reabrir(ficha_id, turno_id):
    turno = _turno_autorizado(ficha_id, turno_id)
    if not turno:
        flash('Turno no encontrado.', 'error')
        return redirect(url_for('instructor.dashboard'))
    reabrir_turno(turno)
    db.session.commit()
    flash('Turno reabierto y restablecido a estado programado.', 'success')
    return _al_calendario(ficha_id, turno.fecha)


@aseo_bp.route('/fichas/<int:ficha_id>/turnos-aseo/<int:turno_id>/editar', methods=['POST'])
@login_required
def editar(ficha_id, turno_id):
    turno = _turno_autorizado(ficha_id, turno_id)
    if not turno:
        flash('Turno no encontrado.', 'error')
        return redirect(url_for('instructor.dashboard'))
    aprendiz_1 = _aprendiz_de_la_ficha(ficha_id, 'aprendiz_1_id')
    aprendiz_2 = _aprendiz_de_la_ficha(ficha_id, 'aprendiz_2_id')
    if not aprendiz_1 or not aprendiz_2:
        flash('Selecciona dos aprendices válidos.', 'error')
        return _al_calendario(ficha_id)
    try:
        reemplazar_aprendices(turno, aprendiz_1, aprendiz_2, request.form.get('observacion', '').strip())
        db.session.commit()
        flash('Asignación manual guardada. La cola futura tendrá en cuenta el cambio.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return _al_calendario(ficha_id, turno.fecha)


@aseo_bp.route('/fichas/<int:ficha_id>/turnos-aseo/config', methods=['POST'])
@login_required
def configurar(ficha_id):
    if not _ficha_autorizada(ficha_id):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    try:
        _guardar_configuracion(ficha_id)
        flash('Configuración de turnos actualizada.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    return _al_calendario(ficha_id)


@aseo_bp.route('/fichas/<int:ficha_id>/turnos-aseo/exclusion/<int:aprendiz_id>', methods=['POST'])
@login_required
def excluir(ficha_id, aprendiz_id):
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not _ficha_autorizada(ficha_id) or not aprendiz or aprendiz.ficha_id != ficha_id:
        flash('Aprendiz no encontrado.', 'error')
        return redirect(url_for('instructor.dashboard'))
    try:
        if not _actualizar_exclusion(ficha_id, aprendiz):
            flash('No se pudo cargar la disponibilidad de este aprendiz.', 'error')
    except ValueError as exc:
        flash(str(exc), 'error')
    return _al_calendario(ficha_id)
