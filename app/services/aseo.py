from collections import defaultdict
from datetime import date, datetime, time, timedelta
from statistics import mean

from app import db
from app.models.aprendiz import ESTADOS_EN_FORMACION, Aprendiz
from app.models.asistencia import SesionAsistencia
from app.models.aseo import (
    ConfiguracionAseo,
    ContadorAseo,
    IntercambioAseo,
    TurnoAseo,
)
from app.models.ficha import Ficha
from app.models.juicio import JuicioEvaluativo
from app.services.aseo_cola import (
    elegir_por_cola_justa as _elegir_por_cola_justa,
    razon_eleccion as _razon_eleccion,
)
from app.services.aseo_motor_puro import calcular_turnos_token_bucket
from app.services.aseo_calendario import DIAS_LABORALES, normalizar_dias_semana
from app.services.aseo_limpieza import eliminar_turnos_fuera_del_calendario
from app.services.festivos import (
    es_dia_habil,
    es_festivo_colombia,
    nombre_festivo_colombia,
    obtener_festivos_colombia,
)


ESTADOS_ACTIVOS = ESTADOS_EN_FORMACION
ESTADOS_PRESENTES = ('ASISTE', 'TARDANZA')
ESTADOS_PENDIENTES = ('programado', 'intercambiado')
ORIGENES_MANUALES = ('instructor', 'aprendiz', 'aprendiz_admin', 'manual')


def aprendices_activos(ficha_id):
    return Aprendiz.query_en_formacion(ficha_id).order_by(
        Aprendiz.apellidos, Aprendiz.nombre
    ).all()


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
    for aprendiz in Aprendiz.query_en_formacion(ficha_id).all():
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


def _obtener_historial_parejas(ficha_id):
    """Retorna un dict con el conteo de veces que dos aprendices han compartido turno."""
    parejas = defaultdict(int)
    turnos = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.aprendiz_1_id.isnot(None),
        TurnoAseo.aprendiz_2_id.isnot(None),
    ).all()
    for t in turnos:
        if t.aprendiz_1_id and t.aprendiz_2_id and t.aprendiz_1_id != t.aprendiz_2_id:
            clave = tuple(sorted((t.aprendiz_1_id, t.aprendiz_2_id)))
            parejas[clave] += 1
    return parejas


def _cargas_totales(
    ficha_id,
    activos,
    contadores,
    excluir_desde=None,
    excluir_hasta=None,
):
    """Carga total por aprendiz: cumplidos + turnos pendientes de todo el horizonte.

    Es la única medida de equidad del calendario. Incluye los pendientes anteriores
    y posteriores a la ventana que se está calculando, porque un turno ya programado
    consume el mismo cupo que uno cumplido: si solo se contaran los cumplidos, quien
    ya tiene aseos asignados volvería a quedar primero en la cola.

    Los pendientes dentro de la ventana ``[excluir_desde, excluir_hasta]`` se omiten
    porque esa ventana se redistribuye (o se ingiere como turno fijo en el motor).
    """
    cargas = {
        aprendiz.id: contadores[aprendiz.id].veces_aseo for aprendiz in activos
    }
    ultimas = {
        aprendiz.id: contadores[aprendiz.id].ultima_vez_aseo for aprendiz in activos
    }
    for turno in TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
    ).all():
        if (
            excluir_desde is not None
            and turno.fecha >= excluir_desde
            and (excluir_hasta is None or turno.fecha <= excluir_hasta)
        ):
            continue
        for aprendiz_id in (turno.aprendiz_1_id, turno.aprendiz_2_id):
            if aprendiz_id not in cargas:
                continue
            cargas[aprendiz_id] += 1
            ultimas[aprendiz_id] = _ultima_fecha(
                ultimas[aprendiz_id], turno.fecha
            )
    return cargas, ultimas


def _es_turno_reposicion(turno):
    """True si el turno nació como reposición de una inasistencia."""
    return bool(turno.observacion and 'Reposición' in turno.observacion)


def _sembrar_descanso_anterior(ficha_id, fecha_inicio):
    """Pareja y fecha del turno inmediatamente anterior al tramo que se calcula.

    Evita que un recálculo parcial repita en su primera sesión a quienes ya
    hicieron aseo en la última sesión del tramo previo. Se ignora cuando el
    turno anterior quedó a más de tres días (puente o fin de semana largo).
    """
    anterior = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.fecha < fecha_inicio,
    ).order_by(TurnoAseo.fecha.desc()).first()
    if not anterior or (fecha_inicio - anterior.fecha) > timedelta(days=3):
        return None, None
    return {anterior.aprendiz_1_id, anterior.aprendiz_2_id}, anterior.fecha


def cargas_pendientes(ficha_id):
    """Turnos pendientes (programados o intercambiados) por aprendiz en todo el horizonte."""
    pendientes = defaultdict(int)
    for turno in TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
    ).all():
        for aprendiz_id in (turno.aprendiz_1_id, turno.aprendiz_2_id):
            pendientes[aprendiz_id] += 1
    return pendientes


def resumen_equidad(ficha_id):
    """Foto de la equidad del calendario usando la carga total (cumplidos + programados).

    Retorna el detalle por aprendiz y la diferencia entre quien más y quien menos
    turnos suma, que es el indicador que persigue el botón "Calcular turnos".
    """
    activos = aprendices_activos(ficha_id)
    contadores = recalcular_contadores(ficha_id)
    pendientes = cargas_pendientes(ficha_id)
    filas = [
        {
            'aprendiz': aprendiz,
            'cumplidos': contadores[aprendiz.id].veces_aseo,
            'programados': pendientes.get(aprendiz.id, 0),
            'total': contadores[aprendiz.id].veces_aseo
            + pendientes.get(aprendiz.id, 0),
        }
        for aprendiz in activos
    ]
    totales = [fila['total'] for fila in filas]
    return {
        'filas': filas,
        'delta': (max(totales) - min(totales)) if totales else 0,
        'minimo': min(totales) if totales else 0,
        'maximo': max(totales) if totales else 0,
        'promedio': mean(totales) if totales else 0,
        'pendientes': sum(pendientes.values()),
    }


def _registros_presentes(sesion):
    registros = sesion.registros.all()
    if not registros:
        return None
    return {
        registro.aprendiz_id
        for registro in registros
        if registro.estado in ESTADOS_PRESENTES
    }


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


def _sesiones_para_generacion(ficha_id, fecha_inicio, fecha_fin, dias_semana=DIAS_LABORALES):
    """Asegura sesiones en el rango (juicios + días hábiles) y las devuelve sin festivos."""
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
            if actual.weekday() in dias_semana and not es_festivo_colombia(actual):
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
        if (
            fecha_inicio <= fecha <= fecha_fin
            and fecha.weekday() in dias_semana
            and not es_festivo_colombia(fecha)
        ):
            fechas_objetivo.add(fecha)

    if fechas_objetivo:
        _crear_sesiones_faltantes(
            ficha_id,
            fechas_objetivo,
            'Creada automáticamente para asignar turnos de aseo.',
        )

    sesiones_todas = SesionAsistencia.query.filter(
        SesionAsistencia.ficha_id == ficha_id,
        SesionAsistencia.fecha.between(fecha_inicio, fecha_fin),
    ).order_by(SesionAsistencia.fecha).all()

    sesiones_unicas = {}
    for sesion in sesiones_todas:
        if (
            sesion.fecha.weekday() in dias_semana
            and not es_festivo_colombia(sesion.fecha)
            and sesion.fecha not in sesiones_unicas
        ):
            sesiones_unicas[sesion.fecha] = sesion

    return [sesiones_unicas[f] for f in sorted(sesiones_unicas)]


def generar_turnos(
    ficha_id,
    fecha_inicio,
    fecha_fin,
    generado_por='sistema',
    rng=None,
    recalcular_existentes=True,
    respetar_manuales=True,
    proteger_pasados=True,
    dias_semana=None,
):
    """Genera y recalcula turnos para sesiones del rango equilibrando cargas y evitando repeticiones.

    - Conserva siempre intactos los turnos cumplidos (históricos).
    - Equilibra con la carga total: turnos cumplidos + turnos pendientes de todo el
      horizonte. Un pendiente de otro mes consume cupo igual que uno del rango, así
      que la cola nunca vuelve a elegir primero a quien ya tiene más aseos asignados.
    - Si recalcular_existentes=True, recalcula cronológicamente los turnos
      pendientes/programados para equilibrar las cargas y rotar parejas sin repeticiones consecutivas.
    - Si respetar_manuales=True, conserva asignaciones manuales en días permitidos.
    - Si proteger_pasados=True, conserva pendientes pasados en días permitidos.
    - Elimina pendientes en festivos o días no seleccionados antes de recalcular.
    """
    if fecha_fin < fecha_inicio:
        raise ValueError('La fecha final no puede ser anterior a la inicial.')

    dias_semana = normalizar_dias_semana(dias_semana)

    config = obtener_configuracion(ficha_id)
    contadores = recalcular_contadores(ficha_id)
    activos = aprendices_activos(ficha_id)
    sesiones = _sesiones_para_generacion(
        ficha_id, fecha_inicio, fecha_fin, dias_semana=dias_semana,
    )

    existentes = {
        turno.fecha: turno
        for turno in TurnoAseo.query.filter(
            TurnoAseo.ficha_id == ficha_id,
            TurnoAseo.fecha.between(fecha_inicio, fecha_fin),
        ).all()
    }

    eliminados = eliminar_turnos_fuera_del_calendario(existentes, dias_semana, ESTADOS_PENDIENTES)
    historial_parejas = _obtener_historial_parejas(ficha_id)
    hoy = date.today()

    turnos_fijos = {}
    cumplidos_conservados = 0
    omitidos_manuales = 0

    for fecha, turno in existentes.items():
        es_cumplido = turno.estado in ('cumplido', 'no_cumplido')
        es_manual = respetar_manuales and turno.generado_por in ORIGENES_MANUALES
        es_pasado = proteger_pasados and fecha < hoy
        no_recalc = not recalcular_existentes and turno.estado in ESTADOS_PENDIENTES

        if es_cumplido or es_manual or es_pasado or no_recalc:
            turnos_fijos[fecha] = {
                'id': turno.id,
                'aprendiz_1_id': turno.aprendiz_1_id,
                'aprendiz_2_id': turno.aprendiz_2_id,
                'estado': turno.estado,
                'es_manual': es_manual,
                'auditoria_1': turno.auditoria_1,
                'auditoria_2': turno.auditoria_2,
                'incrementar_carga': (turno.estado in ESTADOS_PENDIENTES),
            }

    cargas_iniciales, ultimas_fechas_iniciales = _cargas_totales(
        ficha_id,
        activos,
        contadores,
        excluir_desde=fecha_inicio,
        excluir_hasta=fecha_fin,
    )

    excluidos_hasta = {
        aprendiz.id: contadores[aprendiz.id].excluido_hasta
        for aprendiz in activos
        if contadores[aprendiz.id].excluido_hasta
    }

    ausentes_por_fecha = {}
    if config.excluir_ausentes:
        for sesion in sesiones:
            presentes = _registros_presentes(sesion)
            if presentes is not None:
                ausentes_por_fecha[sesion.fecha] = presentes

    vecino_pareja, vecino_fecha = _sembrar_descanso_anterior(ficha_id, fecha_inicio)

    resultado_motor = calcular_turnos_token_bucket(
        aprendiz_ids=[a.id for a in activos],
        sesiones_fechas=[s.fecha for s in sesiones],
        turnos_fijos=turnos_fijos,
        cargas_iniciales=cargas_iniciales,
        ultimas_fechas_iniciales=ultimas_fechas_iniciales,
        historial_parejas_inicial=historial_parejas,
        ausentes_por_fecha=ausentes_por_fecha,
        excluidos_hasta=excluidos_hasta,
        veces_cumplidas_iniciales={a.id: contadores[a.id].veces_aseo for a in activos},
        ultima_pareja_ids=vecino_pareja,
        ultima_fecha_asignada=vecino_fecha,
        rng=rng,
    )

    aprendices_por_id = {a.id: a for a in activos}
    cargas_programadas_locales = defaultdict(int)
    for a_id, val in cargas_iniciales.items():
        cargas_programadas_locales[a_id] = val - contadores[a_id].veces_aseo

    creados = []
    recalculados = []
    promedio = mean(contadores[a.id].veces_aseo for a in activos) if activos else 0

    for asig in resultado_motor['asignaciones']:
        sesion_fecha = asig['fecha']
        turno_existente = existentes.get(sesion_fecha)
        if asig['es_fijo']:
            if turno_existente and turno_existente.estado == 'cumplido':
                cumplidos_conservados += 1
            else:
                omitidos_manuales += 1
            continue

        a1_id = asig['aprendiz_1_id']
        a2_id = asig['aprendiz_2_id']
        elegido_1 = aprendices_por_id.get(a1_id)
        elegido_2 = aprendices_por_id.get(a2_id)
        if not elegido_1 or not elegido_2:
            continue

        pareja_clave = tuple(sorted((a1_id, a2_id)))
        veces_juntos_previa = historial_parejas.get(pareja_clave, 0)
        historial_parejas[pareja_clave] = veces_juntos_previa + 1

        razon_1 = _razon_eleccion(
            contadores[a1_id],
            cargas_programadas_locales[a1_id],
            promedio,
            sesion_fecha in ausentes_por_fecha,
            companero_nombre=elegido_2.nombre,
            veces_juntos=veces_juntos_previa,
        )
        razon_2 = _razon_eleccion(
            contadores[a2_id],
            cargas_programadas_locales[a2_id],
            promedio,
            sesion_fecha in ausentes_por_fecha,
            companero_nombre=elegido_1.nombre,
            veces_juntos=veces_juntos_previa,
        )

        cargas_programadas_locales[a1_id] += 1
        cargas_programadas_locales[a2_id] += 1

        if turno_existente:
            turno_existente.aprendiz_1_id = a1_id
            turno_existente.aprendiz_2_id = a2_id
            turno_existente.estado = 'programado'
            turno_existente.generado_por = generado_por
            turno_existente.auditoria_1 = razon_1
            turno_existente.auditoria_2 = razon_2
            turno_existente.completado_1 = None
            turno_existente.completado_2 = None
            turno_existente.completado_en = None
            for intercambio in turno_existente.intercambios:
                if intercambio.estado == 'pendiente':
                    intercambio.estado = 'rechazado'
                    intercambio.respondido_en = datetime.utcnow()
            recalculados.append(turno_existente)
        else:
            turno = TurnoAseo(
                ficha_id=ficha_id,
                fecha=sesion_fecha,
                aprendiz_1_id=a1_id,
                aprendiz_2_id=a2_id,
                estado='programado',
                generado_por=generado_por,
                auditoria_1=razon_1,
                auditoria_2=razon_2,
            )
            db.session.add(turno)
            creados.append(turno)

    db.session.flush()
    return {
        'creados': creados,
        'recalculados': recalculados,
        'eliminados': eliminados,
        'sesiones': len(sesiones),
        'omitidos_existentes': cumplidos_conservados + omitidos_manuales,
        'cumplidos_conservados': cumplidos_conservados,
        'omitidos_manuales': omitidos_manuales,
        'sin_candidatos': resultado_motor['sin_candidatos'],
    }


def rebalancear_turnos_pendientes(
    ficha_id,
    fecha_inicio=None,
    fecha_fin=None,
    respetar_manuales=True,
    generado_por='sistema',
    rng=None,
):
    """Redistribuye las parejas de los turnos ya programados para restaurar la equidad.

    No crea ni elimina turnos: solo decide quién hace cada aseo pendiente existente
    usando la carga total (cumplidos + programados de todo el horizonte). Lo usa el
    botón "Calcular turnos" con la opción de equilibrar todo el calendario, para que
    el reparto sea justo sobre el total y no solo sobre el rango visible.

    - Solo toca turnos pendientes desde hoy (o ``fecha_inicio``) en adelante.
    - Respeta asignaciones manuales, reposiciones e intercambios aceptados.
    - Nunca asigna a quien está excluido o marcado ausente para esa sesión.
    """
    hoy = date.today()
    desde = fecha_inicio or hoy
    if desde < hoy:
        desde = hoy
    consulta = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
        TurnoAseo.fecha >= desde,
    )
    if fecha_fin is not None:
        consulta = consulta.filter(TurnoAseo.fecha <= fecha_fin)
    turnos = consulta.order_by(TurnoAseo.fecha).all()
    if not turnos:
        return []

    activos = aprendices_activos(ficha_id)
    if len(activos) < 2:
        return []

    contadores = recalcular_contadores(ficha_id)
    ultima_fecha = turnos[-1].fecha
    cargas_iniciales, ultimas_fechas_iniciales = _cargas_totales(
        ficha_id,
        activos,
        contadores,
        excluir_desde=desde,
        excluir_hasta=ultima_fecha,
    )
    historial_parejas = _obtener_historial_parejas(ficha_id)
    excluidos_hasta = {
        aprendiz.id: contadores[aprendiz.id].excluido_hasta
        for aprendiz in activos
        if contadores[aprendiz.id].excluido_hasta
    }

    config = obtener_configuracion(ficha_id)
    ausentes_por_fecha = {}
    if config.excluir_ausentes:
        for turno in turnos:
            presentes = _presentes_en_fecha(ficha_id, turno.fecha)
            if presentes is not None:
                ausentes_por_fecha[turno.fecha] = presentes

    turnos_fijos = {}
    for turno in turnos:
        es_manual = respetar_manuales and turno.generado_por in ORIGENES_MANUALES
        es_intercambio = turno.estado == 'intercambiado'
        es_reposicion = _es_turno_reposicion(turno)
        if es_manual or es_intercambio or es_reposicion:
            turnos_fijos[turno.fecha] = {
                'id': turno.id,
                'aprendiz_1_id': turno.aprendiz_1_id,
                'aprendiz_2_id': turno.aprendiz_2_id,
                'estado': turno.estado,
                'es_manual': es_manual or es_reposicion,
                'auditoria_1': turno.auditoria_1,
                'auditoria_2': turno.auditoria_2,
                'incrementar_carga': True,
            }

    vecino_pareja, vecino_fecha = _sembrar_descanso_anterior(ficha_id, desde)
    resultado_motor = calcular_turnos_token_bucket(
        aprendiz_ids=[a.id for a in activos],
        sesiones_fechas=[t.fecha for t in turnos],
        turnos_fijos=turnos_fijos,
        cargas_iniciales=cargas_iniciales,
        ultimas_fechas_iniciales=ultimas_fechas_iniciales,
        historial_parejas_inicial=historial_parejas,
        ausentes_por_fecha=ausentes_por_fecha,
        excluidos_hasta=excluidos_hasta,
        veces_cumplidas_iniciales={
            a.id: contadores[a.id].veces_aseo for a in activos
        },
        ultima_pareja_ids=vecino_pareja,
        ultima_fecha_asignada=vecino_fecha,
        rng=rng,
    )

    aprendices_por_id = {a.id: a for a in activos}
    turnos_por_fecha = {turno.fecha: turno for turno in turnos}
    programados_locales = {
        a.id: cargas_iniciales[a.id] - contadores[a.id].veces_aseo for a in activos
    }
    promedio = mean(contadores[a.id].veces_aseo for a in activos)
    rebalanceados = []

    for asig in resultado_motor['asignaciones']:
        turno = turnos_por_fecha.get(asig['fecha'])
        if turno is None or asig['es_fijo']:
            continue
        a1_id = asig['aprendiz_1_id']
        a2_id = asig['aprendiz_2_id']
        elegido_1 = aprendices_por_id.get(a1_id)
        elegido_2 = aprendices_por_id.get(a2_id)
        if not elegido_1 or not elegido_2:
            continue

        pareja_clave = tuple(sorted((a1_id, a2_id)))
        veces_juntos = historial_parejas.get(pareja_clave, 0)
        historial_parejas[pareja_clave] = veces_juntos + 1

        if (turno.aprendiz_1_id, turno.aprendiz_2_id) != (a1_id, a2_id):
            turno.aprendiz_1_id = a1_id
            turno.aprendiz_2_id = a2_id
            turno.generado_por = generado_por
            turno.auditoria_1 = 'Recálculo por equidad total. ' + _razon_eleccion(
                contadores[a1_id],
                programados_locales[a1_id],
                promedio,
                asig['fecha'] in ausentes_por_fecha,
                companero_nombre=elegido_2.nombre,
                veces_juntos=veces_juntos,
            )
            turno.auditoria_2 = 'Recálculo por equidad total. ' + _razon_eleccion(
                contadores[a2_id],
                programados_locales[a2_id],
                promedio,
                asig['fecha'] in ausentes_por_fecha,
                companero_nombre=elegido_1.nombre,
                veces_juntos=veces_juntos,
            )
            rebalanceados.append(turno)

        programados_locales[a1_id] += 1
        programados_locales[a2_id] += 1

    db.session.flush()
    return rebalanceados


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


def _presentes_en_fecha(ficha_id, fecha):
    from app.models.asistencia import RegistroAsistencia
    registros = (
        RegistroAsistencia.query
        .join(SesionAsistencia, RegistroAsistencia.sesion_id == SesionAsistencia.id)
        .filter(
            SesionAsistencia.ficha_id == ficha_id,
            SesionAsistencia.fecha == fecha,
        )
        .all()
    )
    if not registros:
        return None
    return {
        registro.aprendiz_id
        for registro in registros
        if registro.estado in ESTADOS_PRESENTES
    }


def _proxima_fecha_disponible(ficha_id, despues_de):
    turnos_existentes = {
        t.fecha
        for t in TurnoAseo.query.filter(
            TurnoAseo.ficha_id == ficha_id,
            TurnoAseo.fecha > despues_de,
        ).all()
    }
    sesiones = SesionAsistencia.query.filter(
        SesionAsistencia.ficha_id == ficha_id,
        SesionAsistencia.fecha > despues_de,
    ).order_by(SesionAsistencia.fecha).all()
    for s in sesiones:
        if es_dia_habil(s.fecha) and s.fecha not in turnos_existentes:
            return s.fecha

    ficha = db.session.get(Ficha, ficha_id)
    limite = (
        ficha.fecha_fin
        if ficha and ficha.fecha_fin
        else despues_de + timedelta(days=60)
    )
    candidata = despues_de + timedelta(days=1)
    while candidata <= limite:
        if es_dia_habil(candidata) and candidata not in turnos_existentes:
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


def _programar_reposicion(ficha_id, aprendiz, desde_fecha, forzar=False):
    """Devuelve al ausente el cupo que no cumplió, sin desalojar turnos ajenos.

    Por defecto solo repone cuando su carga total quedó por debajo de la de sus
    compañeros: si otra persona ya cubrió el turno y él mantiene sus pendientes,
    no se le agenda otro (evita sobrecompensar y duplicar reposiciones).
    ``forzar=True`` se usa cuando el turno no lo cubrió nadie (no cumplido).
    """
    if not aprendiz or not aprendiz.activo or aprendiz.estado not in ESTADOS_ACTIVOS:
        return None

    # Una sola reposición por inasistencia: guardar dos veces el mismo turno (o
    # repetir el "no cumplió") no debe duplicar el cupo compensado de esa fecha.
    fecha_ausencia = desde_fecha.strftime('%d/%m/%Y')
    reposiciones_previas = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
        TurnoAseo.observacion.like('%Reposición%'),
        db.or_(
            TurnoAseo.aprendiz_1_id == aprendiz.id,
            TurnoAseo.aprendiz_2_id == aprendiz.id,
        ),
    ).all()
    for reposicion in reposiciones_previas:
        if fecha_ausencia in (reposicion.observacion or ''):
            return reposicion

    companeros = [
        item for item in aprendices_activos(ficha_id) if item.id != aprendiz.id
    ]
    if not companeros:
        return None

    contadores = asegurar_contadores(ficha_id)
    cargas_prog, ultima_prog = _cargas_programadas(ficha_id)
    cargas_totales = {
        item.id: contadores[item.id].veces_aseo + cargas_prog.get(item.id, 0)
        for item in companeros
    }
    cargas_totales[aprendiz.id] = (
        contadores[aprendiz.id].veces_aseo + cargas_prog.get(aprendiz.id, 0)
    )
    if not forzar and cargas_totales[aprendiz.id] >= max(cargas_totales.values()):
        return None

    fecha = _proxima_fecha_disponible(ficha_id, desde_fecha)
    if not fecha:
        return None

    historial_parejas = _obtener_historial_parejas(ficha_id)
    auditoria = (
        f'Reposición inmediata: no cumplió el turno del '
        f'{desde_fecha.strftime("%d/%m/%Y")} por inasistencia y se le '
        f'asignó el siguiente cupo disponible ({fecha.strftime("%d/%m/%Y")}) '
        'para mantener la misma cantidad de turnos en el grupo.'
    )
    turno = TurnoAseo.query.filter_by(ficha_id=ficha_id, fecha=fecha).first()
    if turno:
        return turno if (turno.estado in ESTADOS_PENDIENTES and turno.incluye(aprendiz.id)) else None

    activos = companeros
    companero = _elegir_por_cola_justa(
        activos,
        contadores,
        cargas_prog,
        ultima_prog,
        companero_id=aprendiz.id,
        historial_parejas=historial_parejas,
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
            companero_nombre=aprendiz.nombre,
            veces_juntos=historial_parejas.get(tuple(sorted((aprendiz.id, companero.id))), 0),
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
    historial_parejas = _obtener_historial_parejas(turno.ficha_id)
    activos = aprendices_activos(turno.ficha_id)
    ausentes_repuestos = []

    for slot in (1, 2):
        actual_id = turno.aprendiz_1_id if slot == 1 else turno.aprendiz_2_id
        otro_id = turno.aprendiz_2_id if slot == 1 else turno.aprendiz_1_id
        if not actual_id or actual_id in presentes:
            continue

        ocupados = {turno.aprendiz_1_id, turno.aprendiz_2_id}
        candidatos = [
            aprendiz
            for aprendiz in activos
            if (
                aprendiz.id in presentes
                and aprendiz.id not in ocupados
                and not (
                    contadores[aprendiz.id].excluido_hasta
                    and contadores[aprendiz.id].excluido_hasta >= turno.fecha
                )
            )
        ]
        if not candidatos:
            continue

        suplente = _elegir_por_cola_justa(
            candidatos,
            contadores,
            cargas_prog,
            ultima_prog,
            companero_id=otro_id,
            historial_parejas=historial_parejas,
        )
        ausente = db.session.get(Aprendiz, actual_id)
        if not ausente:
            continue
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
    """Ajusta el turno del día: crea, repone ausentes y recalcula contadores.

    Cuando alguien no asiste se sustituye por la persona presente con menor carga
    total y se le reserva su reposición en el siguiente cupo libre. Así la ausencia
    no altera el total de turnos de nadie ni desaloja los turnos ya publicados de
    los demás; el botón "Calcular turnos" puede reequilibrar todo el calendario.
    """
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
            if not completado_1_nuevo and turno.aprendiz_1:
                _programar_reposicion(
                    ficha_id, turno.aprendiz_1, turno.fecha, forzar=True
                )
            if not completado_2_nuevo and turno.aprendiz_2:
                _programar_reposicion(
                    ficha_id, turno.aprendiz_2, turno.fecha, forzar=True
                )

    return turno


def verificar_ausencias_en_turnos(ficha_id, fecha_inicio, fecha_fin):
    """Revisa si turnos pendientes en el rango tienen ausencias confirmadas y sustituye ausentes."""
    config = obtener_configuracion(ficha_id)
    if not config.excluir_ausentes:
        return []

    turnos = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.fecha.between(fecha_inicio, fecha_fin),
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
    ).order_by(TurnoAseo.fecha).all()

    sustituidos = []
    for turno in turnos:
        presentes = _presentes_en_fecha(ficha_id, turno.fecha)
        if presentes is not None:
            if (turno.aprendiz_1_id and turno.aprendiz_1_id not in presentes) or (
                turno.aprendiz_2_id and turno.aprendiz_2_id not in presentes
            ):
                repuestos = _reemplazar_ausentes_del_dia(turno, presentes)
                if repuestos:
                    sustituidos.append(turno)

    if sustituidos:
        db.session.flush()
    return sustituidos


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
            # Si completado es explícitamente False (ausente confirmado), no cuenta.
            # Si es True o None (compatibilidad histórica o marcado cumplido directo), cuenta como cumplido.
            if completado is False:
                continue
            contador = contadores.get(aprendiz_id)
            if contador:
                contador.veces_aseo += 1
                contador.ultima_vez_aseo = _ultima_fecha(
                    contador.ultima_vez_aseo, turno.fecha
                )
    db.session.flush()
    return contadores


def completar_turno(turno, completado_1=None, completado_2=None):
    config = obtener_configuracion(turno.ficha_id)
    presentes = _presentes_en_fecha(turno.ficha_id, turno.fecha)
    if (
        turno.estado in ESTADOS_PENDIENTES
        and presentes is not None
        and config.excluir_ausentes
    ):
        _reemplazar_ausentes_del_dia(turno, presentes)

    if completado_1 is False and completado_2 is False:
        return marcar_no_cumplido(turno, aprendiz_1_no_cumplio=True, aprendiz_2_no_cumplio=True)

    turno.estado = 'cumplido'
    turno.completado_en = datetime.utcnow()

    if completado_1 is not None and completado_2 is not None:
        turno.completado_1 = bool(completado_1)
        turno.completado_2 = bool(completado_2)
    else:
        presentes = _presentes_en_fecha(turno.ficha_id, turno.fecha)
        if presentes is not None:
            turno.completado_1 = turno.aprendiz_1_id in presentes
            turno.completado_2 = turno.aprendiz_2_id in presentes
        else:
            turno.completado_1 = True
            turno.completado_2 = True

    recalcular_contadores(turno.ficha_id)

    if turno.completado_1 is False and turno.aprendiz_1:
        _programar_reposicion(
            turno.ficha_id, turno.aprendiz_1, turno.fecha, forzar=True
        )
    if turno.completado_2 is False and turno.aprendiz_2:
        _programar_reposicion(
            turno.ficha_id, turno.aprendiz_2, turno.fecha, forzar=True
        )

    db.session.flush()
    return turno


def marcar_no_cumplido(
    turno,
    aprendiz_1_no_cumplio=True,
    aprendiz_2_no_cumplio=True,
    observacion=None,
):
    """Marca un turno de aseo como no cumplido y agenda reposición para quienes no cumplieron."""
    turno.estado = 'no_cumplido'
    turno.completado_1 = not bool(aprendiz_1_no_cumplio)
    turno.completado_2 = not bool(aprendiz_2_no_cumplio)
    turno.completado_en = datetime.utcnow()
    if observacion:
        nota = f'Marcado como no cumplido: {observacion.strip()}'
        turno.observacion = f'{turno.observacion} {nota}'.strip() if turno.observacion else nota

    recalcular_contadores(turno.ficha_id)

    if aprendiz_1_no_cumplio and turno.aprendiz_1:
        _programar_reposicion(
            turno.ficha_id, turno.aprendiz_1, turno.fecha, forzar=True
        )
    if aprendiz_2_no_cumplio and turno.aprendiz_2:
        _programar_reposicion(
            turno.ficha_id, turno.aprendiz_2, turno.fecha, forzar=True
        )

    db.session.flush()
    return turno


def reabrir_turno(turno):
    """Restablece un turno cumplido o no cumplido a su estado programado inicial."""
    turno.estado = 'programado'
    turno.completado_1 = None
    turno.completado_2 = None
    turno.completado_en = None
    recalcular_contadores(turno.ficha_id)
    db.session.flush()
    return turno


def asignar_o_actualizar_turno(
    ficha_id,
    fecha,
    aprendiz_1_id,
    aprendiz_2_id,
    observacion=None,
    origen='aprendiz_admin',
    actor_label=None,
):
    """Crea o actualiza un turno de aseo para una fecha específica asegurando validaciones y días hábiles."""
    if aprendiz_1_id == aprendiz_2_id:
        raise ValueError('Un turno necesita dos aprendices diferentes.')

    aprendiz_1 = db.session.get(Aprendiz, aprendiz_1_id)
    aprendiz_2 = db.session.get(Aprendiz, aprendiz_2_id)
    if not aprendiz_1 or not aprendiz_2:
        raise ValueError('Selecciona dos aprendices válidos.')
    if aprendiz_1.ficha_id != ficha_id or aprendiz_2.ficha_id != ficha_id:
        raise ValueError('Los aprendices deben pertenecer a la misma ficha.')
    if aprendiz_1.estado not in ESTADOS_ACTIVOS or not aprendiz_1.activo:
        raise ValueError(f'{aprendiz_1.nombre_completo} no está en formación activa en esta ficha.')
    if aprendiz_2.estado not in ESTADOS_ACTIVOS or not aprendiz_2.activo:
        raise ValueError(f'{aprendiz_2.nombre_completo} no está en formación activa en esta ficha.')

    if es_festivo_colombia(fecha):
        raise ValueError(f'No se pueden programar turnos en días festivos ({fecha.strftime("%d/%m/%Y")}).')

    actor = actor_label or (
        'el instructor' if origen == 'instructor' else 'el aprendiz administrador'
    )
    turno = TurnoAseo.query.filter_by(ficha_id=ficha_id, fecha=fecha).first()
    if turno:
        reemplazar_aprendices(
            turno,
            aprendiz_1,
            aprendiz_2,
            observacion=observacion,
            origen=origen,
            actor_label=actor,
        )
    else:
        if not SesionAsistencia.query.filter_by(ficha_id=ficha_id, fecha=fecha).first():
            db.session.add(SesionAsistencia(
                ficha_id=ficha_id,
                fecha=fecha,
                observaciones=f'Sesión creada automáticamente al asignar turno de aseo por {actor}.',
            ))
        turno = TurnoAseo(
            ficha_id=ficha_id,
            fecha=fecha,
            aprendiz_1_id=aprendiz_1.id,
            aprendiz_2_id=aprendiz_2.id,
            estado='programado',
            generado_por=origen,
            auditoria_1=f'Asignación manual realizada por {actor} para {aprendiz_1.nombre_completo}.',
            auditoria_2=f'Asignación manual realizada por {actor} para {aprendiz_2.nombre_completo}.',
            observacion=observacion or f'Asignación manual de {actor}.',
        )
        db.session.add(turno)

    db.session.flush()
    return turno


def reemplazar_aprendices(
    turno,
    aprendiz_1,
    aprendiz_2,
    observacion=None,
    origen='instructor',
    actor_label=None,
):
    if aprendiz_1.id == aprendiz_2.id:
        raise ValueError('Un turno necesita dos aprendices diferentes.')
    if (
        aprendiz_1.ficha_id != turno.ficha_id
        or aprendiz_2.ficha_id != turno.ficha_id
    ):
        raise ValueError('Los aprendices deben pertenecer a la misma ficha.')
    if aprendiz_1.estado not in ESTADOS_ACTIVOS or not aprendiz_1.activo:
        raise ValueError(f'{aprendiz_1.nombre_completo} no está en formación activa en esta ficha.')
    if aprendiz_2.estado not in ESTADOS_ACTIVOS or not aprendiz_2.activo:
        raise ValueError(f'{aprendiz_2.nombre_completo} no está en formación activa en esta ficha.')

    actor = actor_label or (
        'el instructor' if origen == 'instructor' else 'el aprendiz administrador'
    )
    turno.aprendiz_1_id = aprendiz_1.id
    turno.aprendiz_2_id = aprendiz_2.id
    turno.generado_por = origen
    turno.auditoria_1 = (
        f'Asignacion manual realizada por {actor} para '
        f'{aprendiz_1.nombre_completo}.'
    )
    turno.auditoria_2 = (
        f'Asignacion manual realizada por {actor} para '
        f'{aprendiz_2.nombre_completo}.'
    )
    turno.observacion = observacion or f'Ajuste manual de {actor}.'
    if turno.estado != 'cumplido':
        turno.estado = 'programado'
        turno.completado_1 = None
        turno.completado_2 = None
    else:
        turno.completado_1 = True
        turno.completado_2 = True
        recalcular_contadores(turno.ficha_id)


def desvincular_aprendiz_de_turnos_futuros(ficha_id, aprendiz_id):
    """Reemplaza al aprendiz deshabilitado en turnos pendientes futuros o cancela el turno si no hay candidatos."""
    IntercambioAseo.query.filter(
        IntercambioAseo.turno.has(ficha_id=ficha_id),
        IntercambioAseo.estado == 'pendiente',
        db.or_(
            IntercambioAseo.aprendiz_solicita_id == aprendiz_id,
            IntercambioAseo.aprendiz_recibe_id == aprendiz_id,
        ),
    ).update({'estado': 'rechazado'}, synchronize_session='fetch')

    hoy = date.today()
    turnos_futuros = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.fecha >= hoy,
        TurnoAseo.estado.in_(ESTADOS_PENDIENTES),
        db.or_(
            TurnoAseo.aprendiz_1_id == aprendiz_id,
            TurnoAseo.aprendiz_2_id == aprendiz_id,
        ),
    ).all()

    if not turnos_futuros:
        return

    activos = aprendices_activos(ficha_id)
    candidatos_base = [a for a in activos if a.id != aprendiz_id]

    if not candidatos_base:
        for turno in turnos_futuros:
            db.session.delete(turno)
        db.session.flush()
        return

    contadores = asegurar_contadores(ficha_id)
    cargas_prog, ultima_prog = _cargas_programadas(ficha_id)
    historial_parejas = _obtener_historial_parejas(ficha_id)

    for turno in turnos_futuros:
        otro_id = turno.aprendiz_2_id if turno.aprendiz_1_id == aprendiz_id else turno.aprendiz_1_id
        candidatos = [a for a in candidatos_base if a.id != otro_id]
        if not candidatos:
            db.session.delete(turno)
            continue

        reemplazo = _elegir_por_cola_justa(
            candidatos,
            contadores,
            cargas_prog,
            ultima_prog,
            companero_id=otro_id,
            historial_parejas=historial_parejas,
        )
        if not reemplazo:
            db.session.delete(turno)
            continue

        if turno.aprendiz_1_id == aprendiz_id:
            turno.aprendiz_1_id = reemplazo.id
            turno.auditoria_1 = 'Reemplazo automático por deshabilitación de aprendiz.'
        else:
            turno.aprendiz_2_id = reemplazo.id
            turno.auditoria_2 = 'Reemplazo automático por deshabilitación de aprendiz.'

        cargas_prog[reemplazo.id] += 1
        ultima_prog[reemplazo.id] = turno.fecha

    db.session.flush()


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
    if turno.fecha < date.today():
        raise ValueError('El turno ya pasó y no admite intercambios.')

    if not intercambio.aprendiz_solicita or not intercambio.aprendiz_solicita.activo or not intercambio.aprendiz_recibe or not intercambio.aprendiz_recibe.activo:
        raise ValueError('Uno de los aprendices se encuentra deshabilitado.')

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
    salientes = IntercambioAseo.query.filter_by(
        aprendiz_solicita_id=aprendiz.id, estado='pendiente'
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
        'intercambios_salientes': salientes,
        'candidatos_intercambio': candidatos,
    }


def contar_cumplidos_en_periodo(ficha_id, fecha_inicio, fecha_fin):
    """Calcula la cantidad de turnos de aseo cumplidos por aprendiz en un rango de fechas.

    Solo se cuentan las asignaciones en estado 'cumplido' donde el aprendiz no haya
    sido marcado como ausente (completado_1 / completado_2 no sea explícitamente False).
    """
    conteos = defaultdict(int)
    turnos = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha_id,
        TurnoAseo.estado == 'cumplido',
        TurnoAseo.fecha.between(fecha_inicio, fecha_fin),
    ).all()
    for turno in turnos:
        if turno.aprendiz_1_id and turno.completado_1 is not False:
            conteos[turno.aprendiz_1_id] += 1
        if turno.aprendiz_2_id and turno.completado_2 is not False:
            conteos[turno.aprendiz_2_id] += 1
    return dict(conteos)


def datos_transparencia(ficha_id, mes=None):
    if mes is None:
        mes = date.today().replace(day=1)
    import calendar as cal
    ultimo_dia = cal.monthrange(mes.year, mes.month)[1]
    fin_mes = mes.replace(day=ultimo_dia)

    verificar_ausencias_en_turnos(ficha_id, mes, fin_mes)

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

    contadores = recalcular_contadores(ficha_id)
    cumplidos_periodo = contar_cumplidos_en_periodo(ficha_id, mes, fin_mes)
    activos = aprendices_activos(ficha_id)
    pendientes_totales = cargas_pendientes(ficha_id)
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
            'veces_periodo': cumplidos_periodo.get(aprendiz.id, 0),
            'veces_total': contadores[aprendiz.id].veces_aseo,
            'veces_pendientes': pendientes_totales.get(aprendiz.id, 0),
            'veces_comprometidas': contadores[aprendiz.id].veces_aseo
            + pendientes_totales.get(aprendiz.id, 0),
            'proxima': proximos.get(aprendiz.id),
        }
        for aprendiz in activos
    ]
    equidad.sort(
        key=lambda fila: (
            fila['veces_total'],
            fila['contador'].ultima_vez_aseo or date.min,
        )
    )
    totales = [fila['veces_comprometidas'] for fila in equidad]

    semanas = cal.Calendar(firstweekday=0).monthdatescalendar(mes.year, mes.month)
    anios_mes = {mes.year, fin_mes.year}
    festivos_mes = {}
    for anio in anios_mes:
        for f, nom in obtener_festivos_colombia(anio).items():
            if mes <= f <= fin_mes:
                festivos_mes[f] = nom

    return {
        'turnos_por_fecha': turnos_por_fecha,
        'sesiones_mes': sesiones_mes,
        'festivos_mes': festivos_mes,
        'equidad': equidad,
        'equidad_delta': (max(totales) - min(totales)) if totales else 0,
        'semanas': semanas,
        'mes': mes,
        'total_cumplidos': sum(1 for t in turnos_mes if t.estado == 'cumplido'),
        'total_programados': sum(1 for t in turnos_mes if t.estado in ESTADOS_PENDIENTES),
    }
