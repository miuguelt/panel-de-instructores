import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from statistics import mean

from app import db
from app.models.aprendiz import Aprendiz
from app.models.asistencia import SesionAsistencia
from app.models.aseo import (
    ConfiguracionAseo,
    ContadorAseo,
    IntercambioAseo,
    TurnoAseo,
)
from app.models.ficha import Ficha
from app.models.juicio import JuicioEvaluativo


ESTADOS_ACTIVOS = ('EN', 'EN_FORMACION')
ESTADOS_PRESENTES = ('ASISTE', 'TARDANZA')
ESTADOS_PENDIENTES = ('programado', 'intercambiado')


def aprendices_activos(ficha_id):
    return Aprendiz.query.filter(
        Aprendiz.ficha_id == ficha_id,
        Aprendiz.estado.in_(ESTADOS_ACTIVOS),
    ).order_by(Aprendiz.apellidos, Aprendiz.nombre).all()


def obtener_configuracion(ficha_id, crear=True):
    config = ConfiguracionAseo.query.filter_by(ficha_id=ficha_id).first()
    if not config and crear:
        config = ConfiguracionAseo(ficha_id=ficha_id)
        db.session.add(config)
        db.session.flush()
    return config


def asegurar_contadores(ficha_id):
    existentes = {
        contador.aprendiz_id: contador
        for contador in ContadorAseo.query.filter_by(ficha_id=ficha_id).all()
    }
    for aprendiz in Aprendiz.query.filter_by(ficha_id=ficha_id).all():
        if aprendiz.id not in existentes:
            contador = ContadorAseo(
                aprendiz_id=aprendiz.id,
                ficha_id=ficha_id,
                veces_aseo=0,
            )
            db.session.add(contador)
            existentes[aprendiz.id] = contador
    db.session.flush()
    return existentes


def _ultima_fecha(*fechas):
    validas = [valor for valor in fechas if valor is not None]
    return max(validas) if validas else None


def _registros_presentes(sesion):
    registros = sesion.registros.all()
    if not registros:
        return None
    return {
        registro.aprendiz_id
        for registro in registros
        if registro.estado in ESTADOS_PRESENTES
    }


def _razon_eleccion(contador, programados, promedio, solo_asistentes):
    carga = contador.veces_aseo + programados
    partes = [
        f'Te eligió la cola justa porque tu carga era de {carga}: '
        f'{contador.veces_aseo} turno(s) cumplido(s) y {programados} programado(s).',
        f'El promedio de turnos cumplidos del grupo elegible era {promedio:.1f}.',
    ]
    if contador.ultima_vez_aseo:
        partes.append(
            'En el desempate se priorizó a quien llevaba más tiempo sin hacerlo; '
            f'tu última vez fue el {contador.ultima_vez_aseo.strftime("%d/%m/%Y")}.'
        )
    else:
        partes.append('También tuviste prioridad porque nunca habías cumplido un turno.')
    partes.append(
        'Si hubo empate total, el último criterio fue un sorteo aleatorio entre '
        'personas con la misma carga y antigüedad.'
    )
    if solo_asistentes:
        partes.append('La asistencia registrada para esa sesión te marcaba como presente.')
    return ' '.join(partes)


def _fechas_sesion_existentes(ficha_id, fecha_inicio, fecha_fin):
    return {
        sesion.fecha
        for sesion in SesionAsistencia.query.filter(
            SesionAsistencia.ficha_id == ficha_id,
            SesionAsistencia.fecha.between(fecha_inicio, fecha_fin),
        ).all()
    }


def _crear_sesiones_faltantes(ficha_id, fechas, observacion):
    creadas = 0
    existentes = _fechas_sesion_existentes(
        ficha_id,
        min(fechas) if fechas else date.today(),
        max(fechas) if fechas else date.today(),
    ) if fechas else set()
    for fecha in sorted(set(fechas)):
        if fecha in existentes:
            continue
        if SesionAsistencia.query.filter_by(ficha_id=ficha_id, fecha=fecha).first():
            continue
        db.session.add(SesionAsistencia(
            ficha_id=ficha_id,
            fecha=fecha,
            observaciones=observacion,
        ))
        creadas += 1
    if creadas:
        db.session.flush()
    return creadas


def _sesiones_para_generacion(ficha_id, fecha_inicio, fecha_fin):
    """Asegura sesiones en el rango (juicios + días hábiles) y las devuelve."""
    ficha = db.session.get(Ficha, ficha_id)
    limite_inicio = fecha_inicio
    limite_fin = fecha_fin
    if ficha and ficha.fecha_inicio:
        limite_inicio = max(limite_inicio, ficha.fecha_inicio)
    if ficha and ficha.fecha_fin:
        limite_fin = min(limite_fin, ficha.fecha_fin)

    fechas_objetivo = set()
    if limite_fin >= limite_inicio:
        actual = limite_inicio
        while actual <= limite_fin:
            if actual.weekday() < 5:
                fechas_objetivo.add(actual)
            actual += timedelta(days=1)

    for (fecha_juicio,) in db.session.query(JuicioEvaluativo.fecha_juicio).filter(
        JuicioEvaluativo.ficha_id == ficha_id,
        JuicioEvaluativo.fecha_juicio.isnot(None),
        JuicioEvaluativo.fecha_juicio >= datetime.combine(fecha_inicio, time.min),
        JuicioEvaluativo.fecha_juicio < datetime.combine(
            fecha_fin + timedelta(days=1), time.min
        ),
    ).distinct().all():
        fecha = (
            fecha_juicio.date()
            if isinstance(fecha_juicio, datetime)
            else fecha_juicio
        )
        if fecha_inicio <= fecha <= fecha_fin:
            fechas_objetivo.add(fecha)

    if fechas_objetivo:
        _crear_sesiones_faltantes(
            ficha_id,
            fechas_objetivo,
            'Creada automáticamente para asignar turnos de aseo.',
        )

    return SesionAsistencia.query.filter(
        SesionAsistencia.ficha_id == ficha_id,
        SesionAsistencia.fecha.between(fecha_inicio, fecha_fin),
    ).order_by(SesionAsistencia.fecha).all()


def generar_turnos(
    ficha_id,
    fecha_inicio,
    fecha_fin,
    generado_por='sistema',
    rng=None,
):
    """Genera turnos para sesiones del rango. Crea sesiones si faltan."""
    if fecha_fin < fecha_inicio:
        raise ValueError('La fecha final no puede ser anterior a la inicial.')

    config = obtener_configuracion(ficha_id)
    contadores = asegurar_contadores(ficha_id)
    activos = aprendices_activos(ficha_id)
    sesiones = _sesiones_para_generacion(ficha_id, fecha_inicio, fecha_fin)

    existentes = {
        turno.fecha: turno
        for turno in TurnoAseo.query.filter(
            TurnoAseo.ficha_id == ficha_id,
            TurnoAseo.fecha.between(fecha_inicio, fecha_fin),
        ).all()
    }
    cargas_programadas = defaultdict(int)
    ultima_programada = {}
    for turno in TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
    ).all():
        for aprendiz_id in (turno.aprendiz_1_id, turno.aprendiz_2_id):
            cargas_programadas[aprendiz_id] += 1
            ultima_programada[aprendiz_id] = _ultima_fecha(
                ultima_programada.get(aprendiz_id), turno.fecha
            )

    aleatorio = rng or random.SystemRandom()
    creados = []
    omitidos_existentes = 0
    sin_candidatos = []

    for sesion in sesiones:
        if sesion.fecha in existentes:
            omitidos_existentes += 1
            continue

        presentes = _registros_presentes(sesion) if config.excluir_ausentes else None
        candidatos = []
        for aprendiz in activos:
            contador = contadores[aprendiz.id]
            if contador.excluido_hasta and contador.excluido_hasta >= sesion.fecha:
                continue
            if presentes is not None and aprendiz.id not in presentes:
                continue
            candidatos.append(aprendiz)

        if len(candidatos) < 2:
            sin_candidatos.append(sesion.fecha)
            continue

        promedio = mean(
            contadores[aprendiz.id].veces_aseo for aprendiz in candidatos
        )
        elegidos = []
        razones = []
        disponibles = list(candidatos)

        for _ in range(2):
            cargas = {
                aprendiz.id: (
                    contadores[aprendiz.id].veces_aseo
                    + cargas_programadas[aprendiz.id]
                )
                for aprendiz in disponibles
            }
            carga_minima = min(cargas.values())
            empatados_carga = [
                aprendiz
                for aprendiz in disponibles
                if cargas[aprendiz.id] == carga_minima
            ]
            fechas = {
                aprendiz.id: _ultima_fecha(
                    contadores[aprendiz.id].ultima_vez_aseo,
                    ultima_programada.get(aprendiz.id),
                )
                for aprendiz in empatados_carga
            }
            fecha_mas_antigua = min(
                (valor or date.min) for valor in fechas.values()
            )
            empatados = [
                aprendiz
                for aprendiz in empatados_carga
                if (fechas[aprendiz.id] or date.min) == fecha_mas_antigua
            ]
            elegido = aleatorio.choice(empatados)
            contador = contadores[elegido.id]
            razones.append(
                _razon_eleccion(
                    contador,
                    cargas_programadas[elegido.id],
                    promedio,
                    presentes is not None,
                )
            )
            elegidos.append(elegido)
            disponibles.remove(elegido)
            cargas_programadas[elegido.id] += 1
            ultima_programada[elegido.id] = sesion.fecha

        turno = TurnoAseo(
            ficha_id=ficha_id,
            fecha=sesion.fecha,
            aprendiz_1_id=elegidos[0].id,
            aprendiz_2_id=elegidos[1].id,
            estado='programado',
            generado_por=generado_por,
            auditoria_1=razones[0],
            auditoria_2=razones[1],
        )
        db.session.add(turno)
        creados.append(turno)

    db.session.flush()
    return {
        'creados': creados,
        'sesiones': len(sesiones),
        'omitidos_existentes': omitidos_existentes,
        'sin_candidatos': sin_candidatos,
    }


def _cargas_programadas(ficha_id):
    cargas = defaultdict(int)
    ultima = {}
    for turno in TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
    ).all():
        for aprendiz_id in (turno.aprendiz_1_id, turno.aprendiz_2_id):
            cargas[aprendiz_id] += 1
            ultima[aprendiz_id] = _ultima_fecha(
                ultima.get(aprendiz_id), turno.fecha
            )
    return cargas, ultima


def _elegir_por_cola_justa(candidatos, contadores, cargas_prog, ultima_prog, rng=None):
    if not candidatos:
        return None
    aleatorio = rng or random.SystemRandom()
    cargas = {
        aprendiz.id: contadores[aprendiz.id].veces_aseo + cargas_prog[aprendiz.id]
        for aprendiz in candidatos
    }
    carga_minima = min(cargas.values())
    empatados_carga = [
        aprendiz for aprendiz in candidatos if cargas[aprendiz.id] == carga_minima
    ]
    fechas = {
        aprendiz.id: _ultima_fecha(
            contadores[aprendiz.id].ultima_vez_aseo,
            ultima_prog.get(aprendiz.id),
        )
        for aprendiz in empatados_carga
    }
    fecha_mas_antigua = min((valor or date.min) for valor in fechas.values())
    empatados = [
        aprendiz
        for aprendiz in empatados_carga
        if (fechas[aprendiz.id] or date.min) == fecha_mas_antigua
    ]
    return aleatorio.choice(empatados)


def _presentes_en_fecha(ficha_id, fecha):
    sesion = SesionAsistencia.query.filter_by(
        ficha_id=ficha_id, fecha=fecha
    ).first()
    if not sesion:
        return None
    registros = sesion.registros.all()
    if not registros:
        return None
    return {
        registro.aprendiz_id
        for registro in registros
        if registro.estado in ESTADOS_PRESENTES
    }


def _proxima_fecha_disponible(ficha_id, despues_de):
    sesion = SesionAsistencia.query.filter(
        SesionAsistencia.ficha_id == ficha_id,
        SesionAsistencia.fecha > despues_de,
    ).order_by(SesionAsistencia.fecha).first()
    if sesion:
        return sesion.fecha

    ficha = db.session.get(Ficha, ficha_id)
    limite = (
        ficha.fecha_fin
        if ficha and ficha.fecha_fin
        else despues_de + timedelta(days=60)
    )
    candidata = despues_de + timedelta(days=1)
    while candidata <= limite:
        if candidata.weekday() < 5:
            if not SesionAsistencia.query.filter_by(
                ficha_id=ficha_id, fecha=candidata
            ).first():
                db.session.add(SesionAsistencia(
                    ficha_id=ficha_id,
                    fecha=candidata,
                    observaciones='Sesión creada para reponer turno de aseo.',
                ))
                db.session.flush()
            return candidata
        candidata += timedelta(days=1)
    return None


def _programar_reposicion(ficha_id, aprendiz, desde_fecha):
    """Guarda el próximo turno del ausente para equilibrar la cola justa."""
    if TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.fecha > desde_fecha,
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
        db.or_(
            TurnoAseo.aprendiz_1_id == aprendiz.id,
            TurnoAseo.aprendiz_2_id == aprendiz.id,
        ),
    ).first():
        return None

    fecha = _proxima_fecha_disponible(ficha_id, desde_fecha)
    if not fecha:
        return None

    contadores = asegurar_contadores(ficha_id)
    cargas_prog, ultima_prog = _cargas_programadas(ficha_id)
    auditoria = (
        f'Reposición inmediata: no cumplió el turno del '
        f'{desde_fecha.strftime("%d/%m/%Y")} por inasistencia y se le '
        f'asignó el siguiente cupo disponible ({fecha.strftime("%d/%m/%Y")}) '
        'para mantener la misma cantidad de turnos en el grupo.'
    )
    turno = TurnoAseo.query.filter_by(ficha_id=ficha_id, fecha=fecha).first()
    if turno and turno.estado in ESTADOS_PENDIENTES:
        if turno.incluye(aprendiz.id):
            return turno
        sale = max(
            (turno.aprendiz_1, turno.aprendiz_2),
            key=lambda item: (
                contadores[item.id].veces_aseo + cargas_prog[item.id],
                contadores[item.id].ultima_vez_aseo or date.min,
                item.id,
            ),
        )
        _reemplazar_en_turno(turno, sale.id, aprendiz.id, auditoria)
        nota = (
            f'Reposición de {aprendiz.nombre_completo} por ausencia el '
            f'{desde_fecha.strftime("%d/%m/%Y")}.'
        )
        turno.observacion = (
            f'{turno.observacion} {nota}'.strip() if turno.observacion else nota
        )
        db.session.flush()
        return turno

    activos = [
        item for item in aprendices_activos(ficha_id) if item.id != aprendiz.id
    ]
    if not activos:
        return None
    companero = _elegir_por_cola_justa(
        activos, contadores, cargas_prog, ultima_prog
    )
    turno = TurnoAseo(
        ficha_id=ficha_id,
        fecha=fecha,
        aprendiz_1_id=aprendiz.id,
        aprendiz_2_id=companero.id,
        estado='programado',
        generado_por='sistema',
        auditoria_1=auditoria,
        auditoria_2=_razon_eleccion(
            contadores[companero.id],
            cargas_prog[companero.id],
            mean(contadores[a.id].veces_aseo for a in activos) if activos else 0,
            False,
        ),
        observacion=(
            f'Reposición automática de {aprendiz.nombre_completo} por ausencia '
            f'el {desde_fecha.strftime("%d/%m/%Y")}.'
        ),
    )
    db.session.add(turno)
    db.session.flush()
    return turno


def _reemplazar_ausentes_del_dia(turno, presentes):
    """Si falta alguien del turno, pone un suplente presente y agenda reposición."""
    if not presentes:
        return []

    contadores = asegurar_contadores(turno.ficha_id)
    cargas_prog, ultima_prog = _cargas_programadas(turno.ficha_id)
    activos = aprendices_activos(turno.ficha_id)
    ausentes_repuestos = []

    for slot in (1, 2):
        actual_id = turno.aprendiz_1_id if slot == 1 else turno.aprendiz_2_id
        if actual_id in presentes:
            continue

        ocupados = {turno.aprendiz_1_id, turno.aprendiz_2_id}
        candidatos = [
            aprendiz
            for aprendiz in activos
            if aprendiz.id in presentes and aprendiz.id not in ocupados
        ]
        if not candidatos:
            continue

        suplente = _elegir_por_cola_justa(
            candidatos, contadores, cargas_prog, ultima_prog
        )
        ausente = db.session.get(Aprendiz, actual_id)
        auditoria = (
            f'Suplencia por inasistencia: {ausente.nombre_completo} no asistió el '
            f'{turno.fecha.strftime("%d/%m/%Y")}. Entró {suplente.nombre_completo} '
            f'por cola justa (carga '
            f'{contadores[suplente.id].veces_aseo + cargas_prog[suplente.id]}).'
        )
        if slot == 1:
            turno.aprendiz_1_id = suplente.id
            turno.auditoria_1 = auditoria
        else:
            turno.aprendiz_2_id = suplente.id
            turno.auditoria_2 = auditoria
        turno.generado_por = 'sistema'
        cargas_prog[suplente.id] += 1
        cargas_prog[actual_id] = max(0, cargas_prog[actual_id] - 1)
        ultima_prog[suplente.id] = turno.fecha
        ausentes_repuestos.append(ausente)
        nota = (
            f'Suplente por ausencia de {ausente.nombre_completo} el '
            f'{turno.fecha.strftime("%d/%m/%Y")}.'
        )
        turno.observacion = (
            f'{turno.observacion} {nota}'.strip() if turno.observacion else nota
        )

    for ausente in ausentes_repuestos:
        _programar_reposicion(turno.ficha_id, ausente, turno.fecha)

    if ausentes_repuestos:
        db.session.flush()
    return ausentes_repuestos


def ajustar_turno_por_asistencia(ficha_id, fecha_sesion):
    """Ajusta el turno del día: crea, repone ausentes y recalcula contadores."""
    config = obtener_configuracion(ficha_id)
    presentes = _presentes_en_fecha(ficha_id, fecha_sesion)
    turno = TurnoAseo.query.filter_by(
        ficha_id=ficha_id, fecha=fecha_sesion
    ).first()

    if not turno:
        resultado = generar_turnos(ficha_id, fecha_sesion, fecha_sesion)
        return resultado['creados'][0] if resultado['creados'] else None

    if (
        turno.estado in ESTADOS_PENDIENTES
        and presentes is not None
        and config.excluir_ausentes
    ):
        _reemplazar_ausentes_del_dia(turno, presentes)

    if turno.estado == 'cumplido' and presentes is not None:
        completado_1_nuevo = turno.aprendiz_1_id in presentes
        completado_2_nuevo = turno.aprendiz_2_id in presentes
        if (
            turno.completado_1 != completado_1_nuevo
            or turno.completado_2 != completado_2_nuevo
        ):
            turno.completado_1 = completado_1_nuevo
            turno.completado_2 = completado_2_nuevo
            recalcular_contadores(ficha_id)

    return turno


def recalcular_contadores(ficha_id):
    contadores = asegurar_contadores(ficha_id)
    for contador in contadores.values():
        contador.veces_aseo = 0
        contador.ultima_vez_aseo = None

    turnos = TurnoAseo.query.filter_by(
        ficha_id=ficha_id, estado='cumplido'
    ).order_by(TurnoAseo.fecha, TurnoAseo.id).all()
    for turno in turnos:
        pares = [
            (turno.aprendiz_1_id, turno.completado_1),
            (turno.aprendiz_2_id, turno.completado_2),
        ]
        for aprendiz_id, completado in pares:
            if not completado:
                continue
            contador = contadores.get(aprendiz_id)
            if contador:
                contador.veces_aseo += 1
                contador.ultima_vez_aseo = _ultima_fecha(
                    contador.ultima_vez_aseo, turno.fecha
                )
    db.session.flush()
    return contadores


def completar_turno(turno):
    config = obtener_configuracion(turno.ficha_id)
    presentes = _presentes_en_fecha(turno.ficha_id, turno.fecha)
    if (
        turno.estado in ESTADOS_PENDIENTES
        and presentes is not None
        and config.excluir_ausentes
    ):
        _reemplazar_ausentes_del_dia(turno, presentes)

    turno.estado = 'cumplido'
    turno.completado_en = datetime.utcnow()

    presentes = _presentes_en_fecha(turno.ficha_id, turno.fecha)
    if presentes is not None:
        turno.completado_1 = turno.aprendiz_1_id in presentes
        turno.completado_2 = turno.aprendiz_2_id in presentes
    else:
        turno.completado_1 = True
        turno.completado_2 = True

    recalcular_contadores(turno.ficha_id)


def reemplazar_aprendices(turno, aprendiz_1, aprendiz_2, observacion=None):
    if aprendiz_1.id == aprendiz_2.id:
        raise ValueError('Un turno necesita dos aprendices diferentes.')
    if (
        aprendiz_1.ficha_id != turno.ficha_id
        or aprendiz_2.ficha_id != turno.ficha_id
    ):
        raise ValueError('Los aprendices deben pertenecer a la misma ficha.')

    turno.aprendiz_1_id = aprendiz_1.id
    turno.aprendiz_2_id = aprendiz_2.id
    turno.generado_por = 'instructor'
    turno.auditoria_1 = (
        f'Asignacion manual realizada por el instructor para '
        f'{aprendiz_1.nombre_completo}.'
    )
    turno.auditoria_2 = (
        f'Asignacion manual realizada por el instructor para '
        f'{aprendiz_2.nombre_completo}.'
    )
    turno.observacion = observacion or 'Ajuste manual del instructor.'
    if turno.estado != 'cumplido':
        turno.estado = 'programado'
        turno.completado_1 = None
        turno.completado_2 = None
    else:
        recalcular_contadores(turno.ficha_id)


def _reemplazar_en_turno(turno, sale_id, entra_id, auditoria):
    if turno.aprendiz_1_id == sale_id:
        if turno.aprendiz_2_id == entra_id:
            raise ValueError('El aprendiz ya está asignado en ese turno.')
        turno.aprendiz_1_id = entra_id
        turno.auditoria_1 = auditoria
    elif turno.aprendiz_2_id == sale_id:
        if turno.aprendiz_1_id == entra_id:
            raise ValueError('El aprendiz ya está asignado en ese turno.')
        turno.aprendiz_2_id = entra_id
        turno.auditoria_2 = auditoria
    else:
        raise ValueError('El aprendiz solicitante ya no pertenece al turno.')
    turno.estado = 'intercambiado'


def aceptar_intercambio(intercambio):
    if intercambio.estado != 'pendiente':
        raise ValueError('Esta solicitud ya fue respondida.')
    turno = intercambio.turno
    if turno.estado not in ESTADOS_PENDIENTES:
        raise ValueError('El turno ya no admite intercambios.')

    solicitante_id = intercambio.aprendiz_solicita_id
    receptor_id = intercambio.aprendiz_recibe_id
    auditoria = (
        'Asignación actualizada por un intercambio confirmado por ambos '
        f'aprendices el {date.today().strftime("%d/%m/%Y")}.'
    )

    turno_reciproco = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == turno.ficha_id,
        TurnoAseo.id != turno.id,
        TurnoAseo.fecha >= date.today(),
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
        db.or_(
            TurnoAseo.aprendiz_1_id == receptor_id,
            TurnoAseo.aprendiz_2_id == receptor_id,
        ),
    ).order_by(TurnoAseo.fecha).first()

    _reemplazar_en_turno(turno, solicitante_id, receptor_id, auditoria)
    if turno_reciproco and not turno_reciproco.incluye(solicitante_id):
        _reemplazar_en_turno(
            turno_reciproco, receptor_id, solicitante_id, auditoria
        )
        intercambio.turno_reciproco_id = turno_reciproco.id

    intercambio.estado = 'aceptado'
    intercambio.confirma_recibe = True
    intercambio.respondido_en = datetime.utcnow()
    recalcular_contadores(turno.ficha_id)


def resumen_aprendiz(ficha_id, aprendiz):
    hoy = date.today()
    config = obtener_configuracion(ficha_id)
    contadores = asegurar_contadores(ficha_id)
    activos = aprendices_activos(ficha_id)
    contador = contadores[aprendiz.id]

    ultimos = TurnoAseo.query.filter_by(
        ficha_id=ficha_id, estado='cumplido'
    ).order_by(TurnoAseo.fecha.desc()).limit(4).all()
    siguientes = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.fecha >= hoy,
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
    ).order_by(TurnoAseo.fecha).limit(3).all()
    turno_propio = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.fecha >= hoy,
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
        db.or_(
            TurnoAseo.aprendiz_1_id == aprendiz.id,
            TurnoAseo.aprendiz_2_id == aprendiz.id,
        ),
    ).order_by(TurnoAseo.fecha).first()

    auditoria = None
    if turno_propio:
        auditoria = (
            turno_propio.auditoria_1
            if turno_propio.aprendiz_1_id == aprendiz.id
            else turno_propio.auditoria_2
        )
    promedio = mean(
        contadores[item.id].veces_aseo for item in activos
    ) if activos else 0
    visible = False
    if turno_propio:
        inicio_turno = datetime.combine(turno_propio.fecha, time.min)
        horas_faltantes = (inicio_turno - datetime.now()).total_seconds() / 3600
        visible = horas_faltantes <= config.aviso_horas

    entrantes = IntercambioAseo.query.filter_by(
        aprendiz_recibe_id=aprendiz.id, estado='pendiente'
    ).order_by(IntercambioAseo.creado_en.desc()).all()
    candidatos = [
        item for item in activos
        if item.id != aprendiz.id
        and (not turno_propio or not turno_propio.incluye(item.id))
    ]
    return {
        'hoy': hoy,
        'config': config,
        'contador': contador,
        'promedio': promedio,
        'ultimos': ultimos,
        'siguientes': siguientes,
        'turno_propio': turno_propio,
        'auditoria': auditoria,
        'aviso_visible': visible,
        'intercambios_entrantes': entrantes,
        'candidatos_intercambio': candidatos,
    }


def datos_transparencia(ficha_id, mes=None):
    if mes is None:
        mes = date.today().replace(day=1)
    import calendar as cal
    ultimo_dia = cal.monthrange(mes.year, mes.month)[1]
    fin_mes = mes.replace(day=ultimo_dia)

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

    contadores = asegurar_contadores(ficha_id)
    activos = aprendices_activos(ficha_id)
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
        for aprendiz in activos
    ]
    equidad.sort(
        key=lambda fila: (
            fila['contador'].veces_aseo,
            fila['contador'].ultima_vez_aseo or date.min,
        )
    )

    semanas = cal.Calendar(firstweekday=0).monthdatescalendar(mes.year, mes.month)

    return {
        'turnos_por_fecha': turnos_por_fecha,
        'sesiones_mes': sesiones_mes,
        'equidad': equidad,
        'semanas': semanas,
        'mes': mes,
        'total_cumplidos': sum(1 for t in turnos_mes if t.estado == 'cumplido'),
        'total_programados': sum(1 for t in turnos_mes if t.estado in ESTADOS_PENDIENTES),
    }
