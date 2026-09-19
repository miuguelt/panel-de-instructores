import calendar
from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for, session
from flask_login import login_required

from app import db, limiter
from app.models.aprendiz import Aprendiz
from app.models.aseo import ContadorAseo, IntercambioAseo, TurnoAseo
from app.models.asistencia import SesionAsistencia
from app.models.ficha import Ficha
from app.services.aseo import (
    ESTADOS_ACTIVOS,
    ESTADOS_PENDIENTES,
    aceptar_intercambio,
    aprendices_activos,
    asegurar_contadores,
    asignar_o_actualizar_turno,
    completar_turno,
    datos_transparencia,
    generar_turnos,
    obtener_configuracion,
    recalcular_contadores,
    reemplazar_aprendices,
)
from app.services.festivos import (
    es_festivo_colombia,
    nombre_festivo_colombia,
    obtener_festivos_colombia,
)
from app.services.permisos import (
    aprendiz_de_sesion,
    puede_administrar_ficha_como_aprendiz,
    puede_gestionar_ficha,
)


aseo_bp = Blueprint('aseo', __name__, template_folder='../templates/instructor')
aseo_aprendiz_bp = Blueprint(
    'aseo_aprendiz', __name__, template_folder='../templates/aprendiz'
)

MESES = (
    '',
    'Enero',
    'Febrero',
    'Marzo',
    'Abril',
    'Mayo',
    'Junio',
    'Julio',
    'Agosto',
    'Septiembre',
    'Octubre',
    'Noviembre',
    'Diciembre',
)


def _ficha_autorizada(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    return ficha if puede_gestionar_ficha(ficha) else None


def _aprendiz_admin_autorizado(ficha_id):
    """Devuelve el aprendiz de sesión solo si tiene la delegación vigente."""
    if not puede_administrar_ficha_como_aprendiz(ficha_id):
        return None
    return aprendiz_de_sesion(ficha_id)


def _volver_al_panel_aprendiz(ficha_id):
    if session.get('aprendiz_ficha_id') == ficha_id:
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))
    return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))


def _fecha_formulario(valor, nombre):
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise ValueError(f'La {nombre} no es válida.')


def _mes_consulta(valor):
    try:
        return datetime.strptime(valor, '%Y-%m').date().replace(day=1)
    except (TypeError, ValueError):
        return date.today().replace(day=1)


def _mover_mes(fecha, delta):
    indice = fecha.year * 12 + fecha.month - 1 + delta
    return date(indice // 12, indice % 12 + 1, 1)


@aseo_bp.route('/fichas/<int:ficha_id>/turnos-aseo')
@login_required
def turnos(ficha_id):
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    mes = _mes_consulta(request.args.get('mes'))
    ultimo_dia = calendar.monthrange(mes.year, mes.month)[1]
    fin_mes = mes.replace(day=ultimo_dia)
    semanas = calendar.Calendar(firstweekday=0).monthdatescalendar(
        mes.year, mes.month
    )
    turnos_mes = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.fecha.between(mes, fin_mes),
    ).order_by(TurnoAseo.fecha).all()
    turnos_por_fecha = {turno.fecha: turno for turno in turnos_mes}
    sesiones_mes = {
        sesion.fecha
        for sesion in SesionAsistencia.query.filter(
            SesionAsistencia.ficha_id == ficha_id,
            SesionAsistencia.fecha.between(mes, fin_mes),
        ).all()
    }

    config = obtener_configuracion(ficha_id)
    recalcular_contadores(ficha_id)
    db.session.commit()
    contadores = {
        contador.aprendiz_id: contador
        for contador in ContadorAseo.query.filter_by(ficha_id=ficha_id).all()
    }
    aprendices = aprendices_activos(ficha_id)
    proximos = {}
    for turno in TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.fecha >= date.today(),
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
    ).order_by(TurnoAseo.fecha).all():
        for aprendiz_id in (turno.aprendiz_1_id, turno.aprendiz_2_id):
            proximos.setdefault(aprendiz_id, turno.fecha)

    equidad = [
        {
            'aprendiz': aprendiz,
            'contador': contadores[aprendiz.id],
            'proxima': proximos.get(aprendiz.id),
        }
        for aprendiz in aprendices
    ]
    orden = request.args.get('orden', 'veces')
    if orden == 'nombre':
        equidad.sort(
            key=lambda fila: (
                fila['aprendiz'].apellidos.lower(),
                fila['aprendiz'].nombre.lower(),
            )
        )
    elif orden == 'ultima':
        equidad.sort(
            key=lambda fila: fila['contador'].ultima_vez_aseo or date.min
        )
    elif orden == 'proxima':
        equidad.sort(key=lambda fila: fila['proxima'] or date.max)
    else:
        equidad.sort(
            key=lambda fila: (
                fila['contador'].veces_aseo,
                fila['contador'].ultima_vez_aseo or date.min,
            )
        )

    festivos_dict = obtener_festivos_colombia(mes.year)
    festivos_mes = {f: nom for f, nom in festivos_dict.items() if mes <= f <= fin_mes}

    return render_template(
        'turnos_aseo.html',
        ficha=ficha,
        config=config,
        aprendices=aprendices,
        equidad=equidad,
        orden=orden,
        mes=mes,
        nombre_mes=f'{MESES[mes.month]} {mes.year}',
        mes_anterior=_mover_mes(mes, -1).strftime('%Y-%m'),
        mes_siguiente=_mover_mes(mes, 1).strftime('%Y-%m'),
        semanas=semanas,
        turnos_por_fecha=turnos_por_fecha,
        sesiones_mes=sesiones_mes,
        festivos_mes=festivos_mes,
        hoy=date.today(),
        fecha_inicio_default=mes,
        fecha_fin_default=fin_mes,
        total_cumplidos=sum(1 for turno in turnos_mes if turno.estado == 'cumplido'),
        total_programados=sum(
            1 for turno in turnos_mes if turno.estado in ESTADOS_PENDIENTES
        ),
    )


@aseo_bp.route('/fichas/<int:ficha_id>/turnos-aseo/generar', methods=['POST'])
@login_required
def generar(ficha_id):
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    try:
        inicio = _fecha_formulario(request.form.get('fecha_inicio'), 'fecha inicial')
        fin = _fecha_formulario(request.form.get('fecha_fin'), 'fecha final')
        recalcular = request.form.get('recalcular', 'on') in ('on', 'true', '1')
        respetar_manuales = request.form.get('respetar_manuales', 'on') in ('on', 'true', '1')
        resultado = generar_turnos(
            ficha_id,
            inicio,
            fin,
            recalcular_existentes=recalcular,
            respetar_manuales=respetar_manuales,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return redirect(url_for('aseo.turnos', ficha_id=ficha_id))

    creados = len(resultado['creados'])
    recalculados = len(resultado.get('recalculados', []))
    cumplidos = resultado.get('cumplidos_conservados', 0)
    manuales = resultado.get('omitidos_manuales', 0)

    partes = []
    if creados:
        partes.append(f'{creados} nuevo(s)')
    if recalculados:
        partes.append(f'{recalculados} pendiente(s) recalculado(s)')
    if cumplidos:
        partes.append(f'{cumplidos} cumplido(s) conservado(s)')
    if manuales:
        partes.append(f'{manuales} manual(es) conservado(s)')

    if partes:
        mensaje = f'Cálculo de turnos completado ({", ".join(partes)}) para {resultado["sesiones"]} sesión(es).'
    else:
        mensaje = f'No se requirieron cambios en las {resultado["sesiones"]} sesiones evaluadas.'

    if resultado['sin_candidatos']:
        mensaje += (
            f' {len(resultado["sin_candidatos"])} sesión(es) no tenían dos '
            'aprendices elegibles.'
        )
    flash(mensaje, 'success' if (creados or recalculados) else 'info')
    return redirect(
        url_for('aseo.turnos', ficha_id=ficha_id, mes=inicio.strftime('%Y-%m'))
    )


@aseo_bp.route(
    '/fichas/<int:ficha_id>/turnos-aseo/<int:turno_id>/cumplir',
    methods=['POST'],
)
@login_required
def cumplir(ficha_id, turno_id):
    ficha = _ficha_autorizada(ficha_id)
    turno = db.session.get(TurnoAseo, turno_id)
    if not ficha or not turno or turno.ficha_id != ficha_id:
        flash('Turno no encontrado.', 'error')
        return redirect(url_for('instructor.dashboard'))
    completar_turno(turno)
    db.session.commit()
    flash('Turno marcado como cumplido. Los contadores quedaron actualizados.', 'success')
    return redirect(
        url_for('aseo.turnos', ficha_id=ficha_id, mes=turno.fecha.strftime('%Y-%m'))
    )


@aseo_bp.route(
    '/fichas/<int:ficha_id>/turnos-aseo/<int:turno_id>/editar',
    methods=['POST'],
)
@login_required
def editar(ficha_id, turno_id):
    ficha = _ficha_autorizada(ficha_id)
    turno = db.session.get(TurnoAseo, turno_id)
    aprendiz_1 = db.session.get(Aprendiz, request.form.get('aprendiz_1_id', type=int))
    aprendiz_2 = db.session.get(Aprendiz, request.form.get('aprendiz_2_id', type=int))
    if not ficha or not turno or turno.ficha_id != ficha_id:
        flash('Turno no encontrado.', 'error')
        return redirect(url_for('instructor.dashboard'))
    if not aprendiz_1 or not aprendiz_2:
        flash('Selecciona dos aprendices válidos.', 'error')
        return redirect(url_for('aseo.turnos', ficha_id=ficha_id))
    try:
        reemplazar_aprendices(
            turno,
            aprendiz_1,
            aprendiz_2,
            request.form.get('observacion', '').strip(),
        )
        db.session.commit()
        flash('Asignación manual guardada. La cola futura tendrá en cuenta el cambio.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(
        url_for('aseo.turnos', ficha_id=ficha_id, mes=turno.fecha.strftime('%Y-%m'))
    )


@aseo_bp.route('/fichas/<int:ficha_id>/turnos-aseo/config', methods=['POST'])
@login_required
def configurar(ficha_id):
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    config = obtener_configuracion(ficha_id)
    config.excluir_ausentes = request.form.get('excluir_ausentes') == 'on'
    try:
        config.aviso_horas = max(
            0, min(720, int(request.form.get('aviso_horas', 24)))
        )
    except (TypeError, ValueError):
        flash('Las horas de aviso deben ser un número entero.', 'error')
        return redirect(url_for('aseo.turnos', ficha_id=ficha_id))
    db.session.commit()
    flash('Configuración de turnos actualizada.', 'success')
    return redirect(url_for('aseo.turnos', ficha_id=ficha_id))


@aseo_bp.route(
    '/fichas/<int:ficha_id>/turnos-aseo/exclusion/<int:aprendiz_id>',
    methods=['POST'],
)
@login_required
def excluir(ficha_id, aprendiz_id):
    ficha = _ficha_autorizada(ficha_id)
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not ficha or not aprendiz or aprendiz.ficha_id != ficha_id:
        flash('Aprendiz no encontrado.', 'error')
        return redirect(url_for('instructor.dashboard'))
    contador = ContadorAseo.query.filter_by(
        ficha_id=ficha_id, aprendiz_id=aprendiz_id
    ).first()
    if not contador:
        asegurar_contadores(ficha_id)
        contador = ContadorAseo.query.filter_by(
            ficha_id=ficha_id, aprendiz_id=aprendiz_id
        ).first()

    hasta = request.form.get('excluido_hasta', '').strip()
    if hasta:
        try:
            contador.excluido_hasta = _fecha_formulario(hasta, 'fecha de exclusión')
        except ValueError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('aseo.turnos', ficha_id=ficha_id))
        contador.motivo_exclusion = request.form.get('motivo', '').strip() or None
        flash(
            f'{aprendiz.nombre_completo} quedó excluido temporalmente sin perder su contador.',
            'success',
        )
    else:
        contador.excluido_hasta = None
        contador.motivo_exclusion = None
        flash(f'{aprendiz.nombre_completo} volvió a la cola justa.', 'success')
    db.session.commit()
    return redirect(url_for('aseo.turnos', ficha_id=ficha_id))


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/gestionar')
@limiter.limit('60 per minute')
def gestionar(ficha_id):
    actor = _aprendiz_admin_autorizado(ficha_id)
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha or not actor:
        flash('Esta herramienta solo está disponible para el aprendiz administrador.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)

    mes = _mes_consulta(request.args.get('mes'))
    fin_mes = mes.replace(day=calendar.monthrange(mes.year, mes.month)[1])
    turnos = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.fecha.between(mes, fin_mes),
    ).order_by(TurnoAseo.fecha).all()
    festivos_dict = obtener_festivos_colombia(mes.year)
    festivos_mes = {f: nom for f, nom in festivos_dict.items() if mes <= f <= fin_mes}

    return render_template(
        'aprendiz/gestion_aseo.html',
        ficha=ficha,
        actor=actor,
        aprendices=aprendices_activos(ficha_id),
        turnos=turnos,
        mes=mes,
        nombre_mes=f'{MESES[mes.month]} {mes.year}',
        mes_anterior=_mover_mes(mes, -1).strftime('%Y-%m'),
        mes_siguiente=_mover_mes(mes, 1).strftime('%Y-%m'),
        hoy=date.today(),
        fecha_inicio_default=mes,
        fecha_fin_default=fin_mes,
        festivos_mes=festivos_mes,
    )


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/generar', methods=['POST'])
@limiter.limit('20 per minute')
def generar_como_aprendiz(ficha_id):
    actor = _aprendiz_admin_autorizado(ficha_id)
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha or not actor:
        flash('No tienes permiso para generar turnos de aseo.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)
    try:
        inicio = _fecha_formulario(request.form.get('fecha_inicio'), 'fecha inicial')
        fin = _fecha_formulario(request.form.get('fecha_fin'), 'fecha final')
        resultado = generar_turnos(
            ficha_id,
            inicio,
            fin,
            generado_por='aprendiz_admin',
            recalcular_existentes=request.form.get('recalcular', 'on') in ('on', 'true', '1'),
            respetar_manuales=True,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return redirect(url_for('aseo_aprendiz.gestionar', ficha_id=ficha_id))

    total = len(resultado['creados']) + len(resultado.get('recalculados', []))
    if total:
        flash(f'Se generaron o actualizaron {total} turno(s) de aseo (omitiendo festivos).', 'success')
    else:
        flash('No hubo cambios en los turnos del rango seleccionado.', 'info')
    return redirect(url_for(
        'aseo_aprendiz.gestionar', ficha_id=ficha_id, mes=inicio.strftime('%Y-%m')
    ))


@aseo_aprendiz_bp.route(
    '/<int:ficha_id>/turnos-aseo/<int:turno_id>/cumplir', methods=['POST']
)
@limiter.limit('30 per minute')
def cumplir_como_aprendiz(ficha_id, turno_id):
    actor = _aprendiz_admin_autorizado(ficha_id)
    turno = db.session.get(TurnoAseo, turno_id)
    if not actor or not turno or turno.ficha_id != ficha_id:
        flash('No tienes permiso para marcar ese turno.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)

    completado_1 = None
    completado_2 = None
    if 'completado_1' in request.form or 'completado_2' in request.form:
        completado_1 = request.form.get('completado_1') in ('on', 'true', '1')
        completado_2 = request.form.get('completado_2') in ('on', 'true', '1')

    completar_turno(turno, completado_1=completado_1, completado_2=completado_2)
    db.session.commit()
    flash('Turno de aseo marcado como cumplido.', 'success')

    origen = request.form.get('origen') or request.args.get('origen')
    if origen == 'panel':
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))
    return redirect(url_for(
        'aseo_aprendiz.gestionar', ficha_id=ficha_id, mes=turno.fecha.strftime('%Y-%m')
    ))


@aseo_aprendiz_bp.route(
    '/<int:ficha_id>/turnos-aseo/<int:turno_id>/editar', methods=['POST']
)
@limiter.limit('30 per minute')
def editar_como_aprendiz(ficha_id, turno_id):
    actor = _aprendiz_admin_autorizado(ficha_id)
    turno = db.session.get(TurnoAseo, turno_id)
    aprendiz_1 = Aprendiz.query.filter_by(
        id=request.form.get('aprendiz_1_id', type=int), ficha_id=ficha_id
    ).first()
    aprendiz_2 = Aprendiz.query.filter_by(
        id=request.form.get('aprendiz_2_id', type=int), ficha_id=ficha_id
    ).first()
    if not actor or not turno or turno.ficha_id != ficha_id:
        flash('No tienes permiso para editar ese turno.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)
    if not aprendiz_1 or not aprendiz_2:
        flash('Selecciona dos aprendices válidos de esta ficha.', 'error')
        return redirect(url_for('aseo_aprendiz.gestionar', ficha_id=ficha_id))
    try:
        reemplazar_aprendices(
            turno,
            aprendiz_1,
            aprendiz_2,
            request.form.get('observacion', '').strip(),
            origen='aprendiz_admin',
            actor_label=f'el aprendiz administrador {actor.nombre_completo}',
        )
        db.session.commit()
        flash('La asignación del turno fue actualizada.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for(
        'aseo_aprendiz.gestionar', ficha_id=ficha_id, mes=turno.fecha.strftime('%Y-%m')
    ))


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo/asignar', methods=['POST'])
@limiter.limit('30 per minute')
def asignar_como_aprendiz(ficha_id):
    actor = _aprendiz_admin_autorizado(ficha_id)
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha or not actor:
        flash('No tienes permiso para asignar turnos de aseo.', 'error')
        return _volver_al_panel_aprendiz(ficha_id)

    try:
        fecha = _fecha_formulario(request.form.get('fecha'), 'fecha')
        aprendiz_1_id = request.form.get('aprendiz_1_id', type=int)
        aprendiz_2_id = request.form.get('aprendiz_2_id', type=int)
        observacion = request.form.get('observacion', '').strip()
        asignar_o_actualizar_turno(
            ficha_id=ficha_id,
            fecha=fecha,
            aprendiz_1_id=aprendiz_1_id,
            aprendiz_2_id=aprendiz_2_id,
            observacion=observacion,
            origen='aprendiz_admin',
            actor_label=f'el aprendiz administrador {actor.nombre_completo}',
        )
        db.session.commit()
        flash(f'Turno asignado para el {fecha.strftime("%d/%m/%Y")}.', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')

    mes_redir = request.form.get('fecha', '')[:7] or date.today().strftime('%Y-%m')
    return redirect(url_for('aseo_aprendiz.gestionar', ficha_id=ficha_id, mes=mes_redir))


@aseo_aprendiz_bp.route(
    '/<int:ficha_id>/turnos-aseo/<int:turno_id>/intercambiar',
    methods=['POST'],
)
@limiter.limit('10 per minute')
def proponer_intercambio(ficha_id, turno_id):
    documento = (
        request.form.get('documento')
        or session.get('aprendiz_documento', '')
    ).strip()
    aprendiz = Aprendiz.query.filter_by(
        ficha_id=ficha_id, documento=documento
    ).first()
    turno = db.session.get(TurnoAseo, turno_id)
    receptor = db.session.get(
        Aprendiz, request.form.get('aprendiz_recibe_id', type=int)
    )
    if (
        not aprendiz
        or not turno
        or turno.ficha_id != ficha_id
        or not turno.incluye(aprendiz.id)
    ):
        flash('No pudimos validar ese turno para tu documento.', 'error')
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))
    if turno.estado not in ESTADOS_PENDIENTES or turno.fecha < date.today():
        flash('Este turno ya no admite solicitudes de intercambio.', 'error')
        return redirect(
            url_for('aprendiz.panel', ficha_id=ficha_id)
        )
    if (
        not receptor
        or receptor.ficha_id != ficha_id
        or receptor.estado not in ESTADOS_ACTIVOS
        or receptor.id == aprendiz.id
        or turno.incluye(receptor.id)
    ):
        flash('Selecciona un aprendiz activo que no esté en este turno.', 'error')
        return redirect(
            url_for('aprendiz.panel', ficha_id=ficha_id)
        )
    pendiente = IntercambioAseo.query.filter_by(
        turno_id=turno.id,
        aprendiz_solicita_id=aprendiz.id,
        estado='pendiente',
    ).first()
    if pendiente:
        flash('Ya tienes una solicitud pendiente para este turno.', 'info')
    else:
        db.session.add(
            IntercambioAseo(
                turno_id=turno.id,
                aprendiz_solicita_id=aprendiz.id,
                aprendiz_recibe_id=receptor.id,
                confirma_solicita=True,
            )
        )
        db.session.commit()
        flash(
            f'Solicitud enviada a {receptor.nombre_completo}. '
            'El cambio solo se aplicará si la acepta.',
            'success',
        )
    return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))


@aseo_aprendiz_bp.route(
    '/<int:ficha_id>/intercambios/<int:intercambio_id>/responder',
    methods=['POST'],
)
@limiter.limit('10 per minute')
def responder_intercambio(ficha_id, intercambio_id):
    documento = (
        request.form.get('documento')
        or session.get('aprendiz_documento', '')
    ).strip()
    aprendiz = Aprendiz.query.filter_by(
        ficha_id=ficha_id, documento=documento
    ).first()
    intercambio = db.session.get(IntercambioAseo, intercambio_id)
    if (
        not aprendiz
        or not intercambio
        or intercambio.turno.ficha_id != ficha_id
        or intercambio.aprendiz_recibe_id != aprendiz.id
    ):
        flash('No pudimos validar esta solicitud para tu documento.', 'error')
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))
    if intercambio.estado != 'pendiente':
        flash('Esta solicitud ya fue respondida.', 'info')
        return redirect(
            url_for('aprendiz.panel', ficha_id=ficha_id)
        )

    if request.form.get('accion') == 'aceptar':
        try:
            aceptar_intercambio(intercambio)
            db.session.commit()
            flash(
                'Intercambio confirmado por ambos. El calendario ya fue actualizado.',
                'success',
            )
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
    else:
        intercambio.estado = 'rechazado'
        intercambio.confirma_recibe = False
        intercambio.respondido_en = datetime.utcnow()
        db.session.commit()
        flash('Solicitud de intercambio rechazada.', 'info')
    return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))


@aseo_aprendiz_bp.route('/<int:ficha_id>/turnos-aseo')
@limiter.limit('60 per minute')
def transparencia(ficha_id):
    documento = session.get('aprendiz_documento', '') or request.args.get('documento', '').strip()
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))

    aprendiz = None
    if documento:
        aprendiz = Aprendiz.query.filter_by(
            documento=documento, ficha_id=ficha_id
        ).first()

    mes = _mes_consulta(request.args.get('mes'))
    nombre_mes = f'{MESES[mes.month]} {mes.year}'
    mes_anterior = _mover_mes(mes, -1).strftime('%Y-%m')
    mes_siguiente = _mover_mes(mes, 1).strftime('%Y-%m')

    datos = datos_transparencia(ficha_id, mes)

    orden = request.args.get('orden', 'veces')
    if orden == 'nombre':
        datos['equidad'].sort(
            key=lambda fila: (
                fila['aprendiz'].apellidos.lower(),
                fila['aprendiz'].nombre.lower(),
            )
        )
    elif orden == 'ultima':
        datos['equidad'].sort(
            key=lambda fila: fila['contador'].ultima_vez_aseo or date.min
        )
    elif orden == 'proxima':
        datos['equidad'].sort(
            key=lambda fila: fila['proxima'] or date.max
        )

    db.session.commit()
    return render_template(
        'aprendiz/transparencia_aseo.html',
        ficha=ficha,
        aprendiz=aprendiz,
        documento=documento,
        equidad=datos['equidad'],
        orden=orden,
        mes=mes,
        nombre_mes=nombre_mes,
        mes_anterior=mes_anterior,
        mes_siguiente=mes_siguiente,
        semanas=datos['semanas'],
        turnos_por_fecha=datos['turnos_por_fecha'],
        sesiones_mes=datos['sesiones_mes'],
        festivos_mes=datos.get('festivos_mes', {}),
        hoy=date.today(),
        total_cumplidos=datos['total_cumplidos'],
        total_programados=datos['total_programados'],
    )
