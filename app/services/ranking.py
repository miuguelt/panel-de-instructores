from collections import defaultdict
from datetime import datetime, time, timedelta

from app import db
from app.models.aprendiz import Aprendiz
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.models.insignia import Insignia, InsigniaOtorgada
from app.models.juicio import JuicioEvaluativo
from app.models.ranking import ConfiguracionRanking, PuntajeHistorico
from app.models.tarea import Entrega, Tarea


CATALOGO_INSIGNIAS = (
    {
        'codigo': 'RACHA_HIERRO',
        'nombre': 'Racha de Hierro',
        'descripcion': 'Completa cuatro semanas seguidas sin fallas no justificadas.',
        'icono': '🔥',
        'tipo': 'automatica',
        'condicion_json': {'semanas': 4},
    },
    {
        'codigo': 'PUNTUALIDAD_TOTAL',
        'nombre': 'Puntualidad Total',
        'descripcion': 'Completa un mes de formación sin tardanzas.',
        'icono': '⏱️',
        'tipo': 'automatica',
        'condicion_json': {'minimo_sesiones': 4},
    },
    {
        'codigo': 'REGRESO_TRIUNFAL',
        'nombre': 'Regreso Triunfal',
        'descripcion': 'Mejora de forma clara su asistencia después de un periodo difícil.',
        'icono': '🌱',
        'tipo': 'automatica',
        'condicion_json': {'mejora_minima': 15},
    },
    {
        'codigo': 'PRIMERO_ENTREGAR',
        'nombre': 'Primero en Entregar',
        'descripcion': 'Realiza la primera entrega anticipada de una actividad.',
        'icono': '🚀',
        'tipo': 'automatica',
        'condicion_json': {},
    },
    {
        'codigo': 'NUNCA_TARDE',
        'nombre': 'Nunca Tarde',
        'descripcion': 'Completa cinco entregas seguidas antes de la fecha límite.',
        'icono': '✅',
        'tipo': 'automatica',
        'condicion_json': {'entregas': 5},
    },
    {
        'codigo': 'EVIDENCIA_DESTACADA',
        'nombre': 'Evidencia Destacada',
        'descripcion': 'El instructor reconoce una evidencia como ejemplo positivo para el grupo.',
        'icono': '⭐',
        'tipo': 'manual',
        'condicion_json': {},
    },
    {
        'codigo': 'MAYOR_ESCALADA',
        'nombre': 'Mayor Escalada',
        'descripcion': 'Logra el mayor avance de posiciones del periodo.',
        'icono': '📈',
        'tipo': 'automatica',
        'condicion_json': {},
    },
    {
        'codigo': 'CONSTANCIA',
        'nombre': 'Constancia',
        'descripcion': 'Mantiene o mejora su puntaje durante tres meses.',
        'icono': '🧭',
        'tipo': 'automatica',
        'condicion_json': {'meses': 3},
    },
    {
        'codigo': 'SEGUNDA_OPORTUNIDAD',
        'nombre': 'Segunda Oportunidad',
        'descripcion': 'Supera un periodo difícil y vuelve a una zona positiva de participación.',
        'icono': '🌟',
        'tipo': 'automatica',
        'condicion_json': {},
    },
)


def obtener_configuracion(ficha_id, crear=False):
    config = ConfiguracionRanking.query.filter_by(ficha_id=ficha_id).first()
    if not config and crear:
        config = ConfiguracionRanking(ficha_id=ficha_id)
        db.session.add(config)
        db.session.flush()
    return config


def asegurar_catalogo_insignias(ficha_id):
    existentes = {
        insignia.codigo
        for insignia in Insignia.query.filter_by(ficha_id=ficha_id).all()
        if insignia.codigo
    }
    nuevas = []
    for datos in CATALOGO_INSIGNIAS:
        if datos['codigo'] not in existentes:
            insignia = Insignia(ficha_id=ficha_id, **datos)
            db.session.add(insignia)
            nuevas.append(insignia)
    if nuevas:
        db.session.flush()
    return nuevas


def _inicio_periodo(config, periodo, ahora):
    inicio_corte = config.inicio_corte
    if periodo == 'semanal':
        inicio = datetime.combine(
            (ahora - timedelta(days=ahora.weekday())).date(), time.min
        )
    elif periodo == 'mensual':
        inicio = datetime(ahora.year, ahora.month, 1)
    else:
        inicio = inicio_corte

    if inicio_corte and (not inicio or inicio_corte > inicio):
        return inicio_corte
    return inicio


def _en_periodo_sesion(sesion, inicio, fin, inicio_corte):
    if sesion.fecha > fin.date():
        return False
    if inicio and sesion.fecha < inicio.date():
        return False
    if (
        inicio_corte
        and sesion.fecha == inicio_corte.date()
        and (not sesion.creada_en or sesion.creada_en < inicio_corte)
    ):
        return False
    return True


def _en_periodo_fecha(fecha, inicio, fin):
    if not fecha:
        return inicio is None
    return (not inicio or fecha >= inicio) and fecha <= fin


def _numero_calificacion(valor):
    if valor is None:
        return None
    try:
        return float(str(valor).strip().replace(',', '.'))
    except (TypeError, ValueError):
        return None


def _racha_perfecta(registros, sesiones_map, semanas, ahora):
    if semanas <= 0:
        return False
    inicio = ahora.date() - timedelta(days=(semanas * 7) - 1)
    semanas_con_sesion = set()
    for registro in registros:
        sesion = sesiones_map.get(registro.sesion_id)
        if not sesion or sesion.fecha < inicio or sesion.fecha > ahora.date():
            continue
        semanas_con_sesion.add(sesion.fecha.isocalendar()[:2])
        if registro.estado == 'FALTA':
            return False
    return len(semanas_con_sesion) >= semanas


def _alias_aprendiz(aprendiz):
    return f'Aprendiz {aprendiz.id:03d}'


def calcular_ranking(ficha_id, periodo='general', ahora=None):
    ahora = ahora or datetime.utcnow()
    if periodo not in ('general', 'semanal', 'mensual'):
        periodo = 'general'

    config = obtener_configuracion(ficha_id, crear=True)
    inicio = _inicio_periodo(config, periodo, ahora)
    aprendices = Aprendiz.query.filter_by(ficha_id=ficha_id).all()

    sesiones = [
        sesion
        for sesion in SesionAsistencia.query.filter_by(ficha_id=ficha_id).all()
        if _en_periodo_sesion(sesion, inicio, ahora, config.inicio_corte)
    ]
    sesiones_map = {sesion.id: sesion for sesion in sesiones}
    registros_por_aprendiz = defaultdict(list)
    if sesiones_map:
        registros = RegistroAsistencia.query.filter(
            RegistroAsistencia.sesion_id.in_(sesiones_map)
        ).all()
        for registro in registros:
            registros_por_aprendiz[registro.aprendiz_id].append(registro)

    tareas = [
        tarea
        for tarea in Tarea.query.filter_by(ficha_id=ficha_id).all()
        if _en_periodo_fecha(tarea.creada_en, inicio, ahora)
    ]
    tareas_map = {tarea.id: tarea for tarea in tareas}
    entregas_por_aprendiz = defaultdict(dict)
    if tareas_map:
        entregas = Entrega.query.filter(Entrega.tarea_id.in_(tareas_map)).all()
        for entrega in sorted(entregas, key=lambda item: item.fecha_entrega or ahora):
            entregas_por_aprendiz[entrega.aprendiz_id].setdefault(
                entrega.tarea_id, entrega
            )

    juicios = JuicioEvaluativo.query.filter(
        JuicioEvaluativo.ficha_id == ficha_id,
    ).all()
    juicios_por_aprendiz = defaultdict(list)
    for j in juicios:
        juicios_por_aprendiz[j.aprendiz_id].append(j)

    fecha_referencia = ahora - timedelta(days=7)
    historicos = PuntajeHistorico.query.filter(
        PuntajeHistorico.ficha_id == ficha_id,
        PuntajeHistorico.fecha_corte <= fecha_referencia,
    ).order_by(PuntajeHistorico.fecha_corte.desc()).all()
    anterior_por_aprendiz = {}
    for historico in historicos:
        anterior_por_aprendiz.setdefault(historico.aprendiz_id, historico)

    filas = []
    for aprendiz in aprendices:
        registros = registros_por_aprendiz.get(aprendiz.id, [])
        justificadas = sum(
            1
            for registro in registros
            if registro.estado in ('FALTA_JUSTIFICADA', 'EXCUSA_MEDICA')
        )
        no_justificadas = sum(
            1 for registro in registros if registro.estado == 'FALTA'
        )
        sesiones_computables = max(len(registros) - justificadas, 0)
        asistencias = sum(
            1 for registro in registros if registro.estado in ('ASISTE', 'TARDANZA')
        )
        if sesiones_computables:
            porcentaje_asistencia = (asistencias / sesiones_computables) * 100
        elif registros and justificadas == len(registros):
            # Si todo el periodo estuvo debidamente justificado, no se castiga al aprendiz.
            porcentaje_asistencia = 100.0
        else:
            porcentaje_asistencia = 0.0

        entregas = entregas_por_aprendiz.get(aprendiz.id, {})
        entregadas_a_tiempo = 0
        entregas_anticipadas = 0
        calificaciones_altas = 0
        for tarea in tareas:
            entrega = entregas.get(tarea.id)
            if not entrega:
                continue
            fecha_entrega = entrega.fecha_entrega or ahora
            if not tarea.fecha_limite or fecha_entrega <= tarea.fecha_limite:
                entregadas_a_tiempo += 1
            if (
                tarea.fecha_limite
                and fecha_entrega <= tarea.fecha_limite
                - timedelta(hours=max(config.horas_entrega_anticipada, 0))
            ):
                entregas_anticipadas += 1
            nota = _numero_calificacion(entrega.calificacion)
            if nota is not None and nota >= config.umbral_calificacion_alta:
                calificaciones_altas += 1

        porcentaje_evidencias = (
            (entregadas_a_tiempo / len(tareas)) * 100 if tareas else 0.0
        )

        juicios_aprendiz = juicios_por_aprendiz.get(aprendiz.id, [])
        total_juicios = len(juicios_aprendiz)
        aprobados = sum(1 for j in juicios_aprendiz if j.juicio and j.juicio.strip().upper() == 'APROBADO')
        porcentaje_aprobados = (aprobados / total_juicios * 100) if total_juicios else 0.0

        puntos_asistencia = (
            config.peso_asistencia * porcentaje_asistencia / 100
        )
        puntos_evidencias = (
            config.peso_evidencias * porcentaje_evidencias / 100
        )
        puntos_juicios = (
            config.peso_juicios * porcentaje_aprobados / 100
        )
        tiene_racha = _racha_perfecta(
            registros, sesiones_map, config.semanas_racha, ahora
        )
        bonus = (
            entregas_anticipadas * config.bonus_entrega_anticipada
            + calificaciones_altas * config.bonus_calificacion_alta
            + (config.bonus_racha_asistencia if tiene_racha else 0)
        )
        penalizacion = no_justificadas * config.penalizacion_falla_injustificada
        total = max(0.0, puntos_asistencia + puntos_evidencias + puntos_juicios + bonus - penalizacion)

        filas.append(
            {
                'aprendiz': aprendiz,
                'nombre_visible': aprendiz.nombre_completo,
                'porcentaje_asistencia': round(porcentaje_asistencia, 1),
                'porcentaje_evidencias': round(porcentaje_evidencias, 1),
                'porcentaje_aprobados': round(porcentaje_aprobados, 1),
                'puntaje_asistencia': round(puntos_asistencia, 2),
                'puntaje_evidencias': round(puntos_evidencias, 2),
                'puntaje_juicios': round(puntos_juicios, 2),
                'bonus': round(bonus, 2),
                'penalizacion': round(penalizacion, 2),
                'puntaje_total': round(total, 2),
                'barra_puntaje': min(round(total, 2), 100),
                'faltas_no_justificadas': no_justificadas,
                'entregadas_a_tiempo': entregadas_a_tiempo,
                'total_tareas': len(tareas),
                'total_juicios': total_juicios,
                'aprobados': aprobados,
                'tiene_racha': tiene_racha,
                'posicion_anterior': (
                    anterior_por_aprendiz[aprendiz.id].posicion
                    if aprendiz.id in anterior_por_aprendiz
                    else None
                ),
            }
        )

    filas.sort(
        key=lambda fila: (
            -fila['puntaje_total'],
            -fila['porcentaje_evidencias'],
            -fila['porcentaje_aprobados'],
            -fila['porcentaje_asistencia'],
            fila['aprendiz'].apellidos.lower(),
            fila['aprendiz'].nombre.lower(),
        )
    )

    otorgamientos = InsigniaOtorgada.query.join(Insignia).filter(
        Insignia.ficha_id == ficha_id
    ).order_by(InsigniaOtorgada.fecha_obtencion.desc()).all()
    insignias_por_aprendiz = defaultdict(list)
    for otorgamiento in otorgamientos:
        insignias_por_aprendiz[otorgamiento.aprendiz_id].append(otorgamiento.insignia)

    for posicion, fila in enumerate(filas, start=1):
        fila['posicion'] = posicion
        fila['medalla'] = {1: '🥇', 2: '🥈', 3: '🥉'}.get(posicion)
        anterior = fila['posicion_anterior']
        if anterior is None or anterior == posicion:
            fila['tendencia'] = 'estable'
            fila['tendencia_icono'] = '→'
        elif posicion < anterior:
            fila['tendencia'] = 'sube'
            fila['tendencia_icono'] = '↑'
        else:
            fila['tendencia'] = 'baja'
            fila['tendencia_icono'] = '↓'
        fila['insignias'] = insignias_por_aprendiz.get(fila['aprendiz'].id, [])[:4]
        if config.modo_anonimo_parcial:
            fila['alias'] = _alias_aprendiz(fila['aprendiz'])
        else:
            fila['alias'] = fila['aprendiz'].nombre_completo

    return filas, config


def guardar_snapshot(ficha_id, filas, ahora=None, tipo='automatico'):
    ahora = ahora or datetime.utcnow()
    inicio_dia = datetime.combine(ahora.date(), time.min)
    fin_dia = inicio_dia + timedelta(days=1)
    existentes = {}
    if tipo == 'automatico':
        registros = PuntajeHistorico.query.filter(
            PuntajeHistorico.ficha_id == ficha_id,
            PuntajeHistorico.tipo_corte == tipo,
            PuntajeHistorico.fecha_corte >= inicio_dia,
            PuntajeHistorico.fecha_corte < fin_dia,
        ).all()
        existentes = {registro.aprendiz_id: registro for registro in registros}

    for fila in filas:
        historico = existentes.get(fila['aprendiz'].id)
        if not historico:
            historico = PuntajeHistorico(
                aprendiz_id=fila['aprendiz'].id,
                ficha_id=ficha_id,
                tipo_corte=tipo,
            )
            db.session.add(historico)
        historico.fecha_corte = ahora
        historico.puntaje_total = fila['puntaje_total']
        historico.puntaje_asistencia = fila['puntaje_asistencia']
        historico.puntaje_evidencias = fila['puntaje_evidencias']
        historico.puntaje_juicios = fila['puntaje_juicios']
        historico.posicion = fila['posicion']


def _otorgar(aprendiz_id, insignia, nuevas):
    if not insignia or not insignia.activa:
        return
    existe = InsigniaOtorgada.query.filter_by(
        aprendiz_id=aprendiz_id, insignia_id=insignia.id
    ).first()
    if existe:
        return
    otorgamiento = InsigniaOtorgada(
        aprendiz_id=aprendiz_id,
        insignia_id=insignia.id,
        otorgada_por='sistema',
    )
    db.session.add(otorgamiento)
    nuevas.append(otorgamiento)


def _cumple_puntualidad_mes(aprendiz_id, ficha_id, ahora, minimo=4):
    inicio = datetime(ahora.year, ahora.month, 1).date()
    registros = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        SesionAsistencia.fecha >= inicio,
        SesionAsistencia.fecha <= ahora.date(),
        RegistroAsistencia.aprendiz_id == aprendiz_id,
    ).all()
    return len(registros) >= minimo and all(
        registro.estado != 'TARDANZA' for registro in registros
    )


def _fue_primero_en_entregar(aprendiz_id, ficha_id):
    tareas = Tarea.query.filter_by(ficha_id=ficha_id).all()
    for tarea in tareas:
        primera = Entrega.query.filter_by(tarea_id=tarea.id).order_by(
            Entrega.fecha_entrega.asc()
        ).first()
        if (
            primera
            and primera.aprendiz_id == aprendiz_id
            and (
                not tarea.fecha_limite
                or (
                    primera.fecha_entrega
                    and primera.fecha_entrega <= tarea.fecha_limite
                )
            )
        ):
            return True
    return False


def _cinco_entregas_tempranas(aprendiz_id, ficha_id):
    entregas = Entrega.query.join(Tarea).filter(
        Tarea.ficha_id == ficha_id,
        Entrega.aprendiz_id == aprendiz_id,
    ).order_by(Entrega.fecha_entrega.desc()).limit(5).all()
    return len(entregas) == 5 and all(
        entrega.tarea.fecha_limite
        and entrega.fecha_entrega
        and entrega.fecha_entrega < entrega.tarea.fecha_limite
        for entrega in entregas
    )


def _historial_mejora(aprendiz_id, ficha_id, campo, actual, minimo_anterior, mejora):
    historicos = PuntajeHistorico.query.filter_by(
        aprendiz_id=aprendiz_id, ficha_id=ficha_id
    ).order_by(PuntajeHistorico.fecha_corte.asc()).all()
    valores = [getattr(item, campo) for item in historicos]
    return bool(valores) and min(valores) <= minimo_anterior and actual >= min(valores) + mejora


def _cumple_constancia(aprendiz_id, ficha_id):
    historicos = PuntajeHistorico.query.filter_by(
        aprendiz_id=aprendiz_id, ficha_id=ficha_id
    ).order_by(PuntajeHistorico.fecha_corte.asc()).all()
    por_mes = {}
    for item in historicos:
        por_mes[(item.fecha_corte.year, item.fecha_corte.month)] = item.puntaje_total
    ultimos = list(por_mes.values())[-3:]
    return len(ultimos) == 3 and all(
        actual >= anterior for anterior, actual in zip(ultimos, ultimos[1:])
    )


def evaluar_insignias(ficha_id, filas, ahora=None):
    ahora = ahora or datetime.utcnow()
    asegurar_catalogo_insignias(ficha_id)
    catalogo = {
        insignia.codigo: insignia
        for insignia in Insignia.query.filter_by(ficha_id=ficha_id).all()
        if insignia.codigo
    }
    nuevas = []

    for fila in filas:
        aprendiz_id = fila['aprendiz'].id
        if fila['tiene_racha']:
            _otorgar(aprendiz_id, catalogo.get('RACHA_HIERRO'), nuevas)
        if _cumple_puntualidad_mes(aprendiz_id, ficha_id, ahora):
            _otorgar(aprendiz_id, catalogo.get('PUNTUALIDAD_TOTAL'), nuevas)
        if _fue_primero_en_entregar(aprendiz_id, ficha_id):
            _otorgar(aprendiz_id, catalogo.get('PRIMERO_ENTREGAR'), nuevas)
        if _cinco_entregas_tempranas(aprendiz_id, ficha_id):
            _otorgar(aprendiz_id, catalogo.get('NUNCA_TARDE'), nuevas)
        if _historial_mejora(
            aprendiz_id,
            ficha_id,
            'puntaje_asistencia',
            fila['puntaje_asistencia'],
            25,
            15,
        ):
            _otorgar(aprendiz_id, catalogo.get('REGRESO_TRIUNFAL'), nuevas)
        if _historial_mejora(
            aprendiz_id,
            ficha_id,
            'puntaje_total',
            fila['puntaje_total'],
            60,
            20,
        ) and fila['puntaje_total'] >= 80:
            _otorgar(aprendiz_id, catalogo.get('SEGUNDA_OPORTUNIDAD'), nuevas)
        if _cumple_constancia(aprendiz_id, ficha_id):
            _otorgar(aprendiz_id, catalogo.get('CONSTANCIA'), nuevas)

    escaladas = [
        (
            fila['posicion_anterior'] - fila['posicion'],
            fila['aprendiz'].id,
        )
        for fila in filas
        if fila['posicion_anterior'] is not None
        and fila['posicion_anterior'] > fila['posicion']
    ]
    if escaladas:
        mayor = max(escalada for escalada, _ in escaladas)
        for escalada, aprendiz_id in escaladas:
            if escalada == mayor:
                _otorgar(aprendiz_id, catalogo.get('MAYOR_ESCALADA'), nuevas)

    return nuevas


def actualizar_participacion_ficha(ficha_id, ahora=None):
    ahora = ahora or datetime.utcnow()
    obtener_configuracion(ficha_id, crear=True)
    asegurar_catalogo_insignias(ficha_id)
    filas, _ = calcular_ranking(ficha_id, periodo='general', ahora=ahora)
    nuevas = evaluar_insignias(ficha_id, filas, ahora=ahora)
    guardar_snapshot(ficha_id, filas, ahora=ahora)
    db.session.commit()
    return filas, nuevas


def mensaje_motivacional(fila):
    if fila['posicion'] <= 3:
        return '¡Vas muy bien! Tu constancia se está notando; sigue cuidando ese ritmo.'
    if fila['tendencia'] == 'sube':
        return '¡Buen avance! Estás subiendo gracias a tu participación y cumplimiento.'
    if fila['porcentaje_evidencias'] < 70:
        return 'Cada entrega cuenta. Organiza la próxima con tiempo y sigue avanzando paso a paso.'
    if fila['porcentaje_asistencia'] < 80:
        return 'Tu proceso puede mejorar con cada sesión. Si necesitas apoyo, conversa con tu instructor.'
    return 'Vas construyendo un proceso constante. ¡Sigue así!'
