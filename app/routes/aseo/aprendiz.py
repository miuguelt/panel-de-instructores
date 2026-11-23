"""Páginas de aseo del aprendiz: calendario, gestión e intercambios de turno."""

from datetime import date, datetime

from flask import flash, redirect, render_template, request, url_for

from app import db, limiter
from app.models.aprendiz import Aprendiz
from app.models.aseo import IntercambioAseo, TurnoAseo
from app.models.ficha import Ficha
from app.services.aseo import ESTADOS_ACTIVOS, ESTADOS_PENDIENTES, aceptar_intercambio, obtener_configuracion
from app.services.permisos import aprendiz_de_sesion

from . import (
    _aprendiz_admin_autorizado,
    _aprendiz_autorizado,
    _contexto_calendario,
    _volver_al_panel_aprendiz,
    aseo_aprendiz_bp,
)


def _al_panel(ficha_id):
    return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))


def _a_la_vista(ficha_id):
    return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/gestionar')
@limiter.limit('60 per minute')
def gestionar(ficha_id):
    actor = _aprendiz_autorizado(ficha_id)
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha or not actor:
        flash('Debes pertenecer a esta ficha para gestionar los turnos de aseo.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)
    config = obtener_configuracion(ficha_id)
    return render_template(
        'aprendiz/gestion_aseo.html',
        ficha=ficha,
        actor=actor,
        puede_gestionar_aseo=_aprendiz_admin_autorizado(ficha_id) is not None,
        config=config,
        **_contexto_calendario(ficha_id),
    )


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo')
@limiter.limit('60 per minute')
def transparencia(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return _a_la_vista(ficha_id)
    # Solo quien pertenece a la ficha ve nombres e historial de aseo del grupo.
    aprendiz = aprendiz_de_sesion(ficha_id)
    if not aprendiz:
        flash('Ingresa con tu documento para ver los turnos de aseo de tu ficha.', 'error')
        return _a_la_vista(ficha_id)
    return render_template(
        'aprendiz/transparencia_aseo.html',
        ficha=ficha,
        aprendiz=aprendiz,
        documento=aprendiz.documento,
        puede_gestionar_aseo=_aprendiz_admin_autorizado(ficha_id) is not None,
        **_contexto_calendario(ficha_id),
    )


def _receptor_valido(receptor, ficha_id, solicitante, turno):
    return (
        receptor
        and receptor.ficha_id == ficha_id
        and receptor.estado in ESTADOS_ACTIVOS
        and receptor.activo
        and receptor.id != solicitante.id
        and not turno.incluye(receptor.id)
    )


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/<int:turno_id>/intercambiar', methods=['POST'])
@limiter.limit('10 per minute')
def proponer_intercambio(ficha_id, turno_id):
    aprendiz = _aprendiz_autorizado(ficha_id)
    turno = db.session.get(TurnoAseo, turno_id)
    if not aprendiz or not turno or turno.ficha_id != ficha_id or not turno.incluye(aprendiz.id):
        flash('No pudimos validar ese turno para tu documento.', 'error')
        return _a_la_vista(ficha_id)
    if turno.estado not in ESTADOS_PENDIENTES or turno.fecha < date.today():
        flash('Este turno ya no admite solicitudes de intercambio.', 'error')
        return _al_panel(ficha_id)
    receptor = db.session.get(Aprendiz, request.form.get('aprendiz_recibe_id', type=int))
    if not _receptor_valido(receptor, ficha_id, aprendiz, turno):
        flash('Selecciona un aprendiz activo que no esté en este turno.', 'error')
        return _al_panel(ficha_id)
    pendiente = IntercambioAseo.query.filter_by(
        turno_id=turno.id, aprendiz_solicita_id=aprendiz.id, estado='pendiente'
    ).first()
    if pendiente:
        flash('Ya tienes una solicitud pendiente para este turno.', 'info')
    else:
        db.session.add(IntercambioAseo(
            turno_id=turno.id,
            aprendiz_solicita_id=aprendiz.id,
            aprendiz_recibe_id=receptor.id,
            confirma_solicita=True,
        ))
        db.session.commit()
        flash(f'Solicitud enviada a {receptor.nombre_completo}. '
              'El cambio solo se aplicará si la acepta.', 'success')
    return _al_panel(ficha_id)


@aseo_aprendiz_bp.route('/<int:ficha_id>/intercambios/<int:intercambio_id>/responder', methods=['POST'])
@limiter.limit('10 per minute')
def responder_intercambio(ficha_id, intercambio_id):
    aprendiz = _aprendiz_autorizado(ficha_id)
    intercambio = db.session.get(IntercambioAseo, intercambio_id)
    if (
        not aprendiz
        or not intercambio
        or intercambio.turno.ficha_id != ficha_id
        or intercambio.aprendiz_recibe_id != aprendiz.id
    ):
        flash('No pudimos validar esta solicitud para tu documento.', 'error')
        return _a_la_vista(ficha_id)
    if intercambio.estado != 'pendiente':
        flash('Esta solicitud ya fue respondida.', 'info')
        return _al_panel(ficha_id)

    if request.form.get('accion') == 'aceptar':
        try:
            aceptar_intercambio(intercambio)
            db.session.commit()
            flash('Intercambio confirmado por ambos. El calendario ya fue actualizado.', 'success')
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
    else:
        intercambio.estado = 'rechazado'
        intercambio.confirma_recibe = False
        intercambio.respondido_en = datetime.utcnow()
        db.session.commit()
        flash('Solicitud de intercambio rechazada.', 'info')
    return _al_panel(ficha_id)
