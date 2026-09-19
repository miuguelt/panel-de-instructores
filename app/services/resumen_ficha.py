"""Servicio centralizado para la Visión General de la Ficha (Ficha 360).

Consolida en un único punto de verdad (SSoT) el estado pedagógico, operativo,
disciplinario y de asistencia de la ficha que el instructor está gestionando.
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Any, Dict, List, Optional
from sqlalchemy import func, or_

from app import db
from app.models.ficha import Ficha
from app.models.aprendiz import Aprendiz, ESTADOS_EN_FORMACION
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.models.tarea import Tarea, Entrega, MODALIDAD_EVIDENCIA
from app.models.alertas import Alerta, ConfiguracionAlertas, PlanMejoramiento
from app.models.aseo import TurnoAseo
from app.models.juicio import JuicioEvaluativo
from app.models.observador import NotaObservador
from app.services.cronograma import obtener_cronograma
from app.services.fases_dashboard import obtener_seguimiento_fases_dashboard
from app.services.permisos import tareas_visibles
from app.services.asistencia import contar_sesiones_registradas


ESTADOS_FALTA = ('FALTA', 'FALTA_JUSTIFICADA', 'EXCUSA_MEDICA')


def _faltas_por_aprendiz(ficha_id: int, corte_id: Optional[int] = None) -> Dict[int, Dict[str, int]]:
    """Cuenta inasistencias por aprendiz y estado en una sola consulta agregada."""
    consulta = (
        db.session.query(
            RegistroAsistencia.aprendiz_id,
            RegistroAsistencia.estado,
            func.count(RegistroAsistencia.id),
        )
        .join(SesionAsistencia, RegistroAsistencia.sesion_id == SesionAsistencia.id)
        .filter(
            SesionAsistencia.ficha_id == ficha_id,
            RegistroAsistencia.estado.in_(ESTADOS_FALTA),
        )
    )
    if corte_id is not None:
        consulta = consulta.filter(SesionAsistencia.corte_id == corte_id)
    filas = consulta.group_by(RegistroAsistencia.aprendiz_id, RegistroAsistencia.estado).all()
    conteo: Dict[int, Dict[str, int]] = {}
    for aprendiz_id, estado, cantidad in filas:
        conteo.setdefault(aprendiz_id, {})[estado] = cantidad
    return conteo


def _ultima_entrega_por_aprendiz(tareas: List[Tarea]) -> Dict[tuple[int, int], Entrega]:
    """Mapa {(tarea_id, aprendiz_id): entrega_mas_reciente} en una sola consulta."""
    ids_tareas = [t.id for t in tareas]
    if not ids_tareas:
        return {}
    entregas = (
        Entrega.query
        .filter(Entrega.tarea_id.in_(ids_tareas))
        .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
        .all()
    )
    ultimas: Dict[tuple[int, int], Entrega] = {}
    for entrega in entregas:
        ultimas.setdefault((entrega.tarea_id, entrega.aprendiz_id), entrega)
    return ultimas


def calcular_semaforo(ficha_id: int, aprendices: List[Aprendiz], config: ConfiguracionAlertas, ahora: Optional[datetime] = None, corte_id: Optional[int] = None):
    """Calcula nivel de riesgo (verde/amarillo/rojo), faltas y tareas pendientes."""
    ahora = ahora or datetime.utcnow()
    total_sesiones = contar_sesiones_registradas(ficha_id, corte_id=corte_id)
    faltas = _faltas_por_aprendiz(ficha_id, corte_id=corte_id)
    tareas_ficha = tareas_visibles(ficha_id, corte_id=corte_id, ver_todas=True).all()
    ultimas_entregas = _ultima_entrega_por_aprendiz(tareas_ficha)

    stats_map = {}
    for aprendiz in aprendices:
        conteo = faltas.get(aprendiz.id, {})
        faltas_no_justificadas = conteo.get('FALTA', 0)
        total_faltas = sum(conteo.values())
        faltas_justificadas = total_faltas - faltas_no_justificadas
        pct_asistencia = (
            (total_sesiones - total_faltas) / total_sesiones * 100
            if total_sesiones > 0 else 100.0
        )

        tareas_pendientes = 0
        for tarea in tareas_ficha:
            entrega = ultimas_entregas.get((tarea.id, aprendiz.id))
            if entrega and entrega.estado_revision == 'rechazada':
                tareas_pendientes += 1
            elif not entrega and tarea.fecha_limite and tarea.fecha_limite < ahora:
                tareas_pendientes += 1

        umbral_rojo = config.umbral_rojo if config and config.umbral_rojo is not None else 6
        umbral_amarillo = config.umbral_amarillo if config and config.umbral_amarillo is not None else 3

        if faltas_no_justificadas >= umbral_rojo or tareas_pendientes >= 3:
            nivel = 'rojo'
        elif faltas_no_justificadas >= umbral_amarillo or tareas_pendientes >= 1:
            nivel = 'amarillo'
        else:
            nivel = 'verde'

        stats_map[aprendiz.id] = {
            'faltas_no_justificadas': faltas_no_justificadas,
            'faltas_justificadas': faltas_justificadas,
            'pct_asistencia': round(pct_asistencia, 1),
            'tareas_pendientes': tareas_pendientes,
            'nivel': nivel,
        }
    return stats_map, total_sesiones


def obtener_resumen_ficha_360(ficha: Ficha, instructor_id: Optional[int] = None, ahora: Optional[datetime] = None, corte_id: Optional[int] = None) -> Dict[str, Any]:
    """Genera una visión consolidada y sin redundancias de lo que pasa en la ficha."""
    ahora = ahora or datetime.utcnow()
    hoy = ahora.date()

    # 1. Cronograma y Fases formativas
    cronograma = obtener_cronograma(ficha)
    fases_data = obtener_seguimiento_fases_dashboard(ficha, cronograma, hoy=hoy)

    # 2. Configuración de alertas
    config_alertas = (
        ConfiguracionAlertas.query.filter_by(ficha_id=ficha.id).first()
        or ConfiguracionAlertas(ficha_id=ficha.id)
    )

    # 3. Aprendices (censo y estado)
    todos_aprendices = (
        Aprendiz.query.filter_by(ficha_id=ficha.id)
        .order_by(Aprendiz.apellidos, Aprendiz.nombre)
        .all()
    )
    estados_distribucion: Dict[str, int] = {}
    for ap in todos_aprendices:
        estados_distribucion[ap.estado] = estados_distribucion.get(ap.estado, 0) + 1

    aprendices_activos = [ap for ap in todos_aprendices if ap.en_formacion]
    total_activos = len(aprendices_activos)
    total_general = len(todos_aprendices)

    # 4. Semáforo y Aprendices en riesgo
    stats_map, total_sesiones = calcular_semaforo(
        ficha.id, aprendices_activos, config_alertas, ahora=ahora, corte_id=corte_id
    )

    aprendices_rojo = []
    aprendices_amarillo = []
    aprendices_verde = []
    for ap in aprendices_activos:
        st = stats_map.get(ap.id, {})
        item = {'aprendiz': ap, 'stats': st}
        nivel = st.get('nivel', 'verde')
        if nivel == 'rojo':
            aprendices_rojo.append(item)
        elif nivel == 'amarillo':
            aprendices_amarillo.append(item)
        else:
            aprendices_verde.append(item)

    # 5. Métricas de Asistencia Global
    posibles_asistencias = total_sesiones * total_activos
    total_faltas_injustificadas = sum(st.get('faltas_no_justificadas', 0) for st in stats_map.values())
    total_faltas_todas = sum(st.get('faltas_no_justificadas', 0) + st.get('faltas_justificadas', 0) for st in stats_map.values())
    pct_asistencia_global = (
        round(((posibles_asistencias - total_faltas_todas) / posibles_asistencias * 100), 1)
        if posibles_asistencias > 0 else 100.0
    )

    # 6. Tareas y Entregas pendientes de calificación
    tareas_query = Tarea.query.filter_by(ficha_id=ficha.id)
    if corte_id is not None:
        tareas_query = tareas_query.filter_by(corte_id=corte_id)
    todas_tareas = tareas_query.order_by(Tarea.fecha_limite.desc(), Tarea.id.desc()).all()

    # Entregas que necesitan atención del instructor (pendientes de calificar)
    entregas_pendientes_query = (
        Entrega.query
        .join(Tarea, Entrega.tarea_id == Tarea.id)
        .join(Aprendiz, Entrega.aprendiz_id == Aprendiz.id)
        .filter(
            Tarea.ficha_id == ficha.id,
            Tarea.modalidad == MODALIDAD_EVIDENCIA,
            or_(Entrega.calificada == False, Entrega.estado_revision == 'pendiente'),
            Aprendiz.estado.in_(ESTADOS_EN_FORMACION),
        )
    )
    if instructor_id and not getattr(ficha, 'es_admin', False):
        # Si no es admin, priorizamos las tareas donde es responsable
        pass
    entregas_pendientes = (
        entregas_pendientes_query
        .order_by(Entrega.fecha_entrega.asc())
        .all()
    )

    total_entregas_recibidas = (
        Entrega.query
        .join(Tarea, Entrega.tarea_id == Tarea.id)
        .filter(Tarea.ficha_id == ficha.id)
        .count()
    )
    entregas_esperadas = len(todas_tareas) * total_activos
    pct_entregas_global = (
        round((total_entregas_recibidas / entregas_esperadas * 100))
        if entregas_esperadas > 0 else 100
    )

    # Tareas próximas a vencer (en los próximos 15 días o futuras más cercanas)
    tareas_proximas = (
        Tarea.query.filter(
            Tarea.ficha_id == ficha.id,
            Tarea.fecha_limite >= ahora,
        )
        .order_by(Tarea.fecha_limite.asc())
        .limit(5)
        .all()
    )

    # 7. Alertas tempranas activas
    alertas_activas = (
        Alerta.query.filter_by(ficha_id=ficha.id, estado='activa')
        .order_by(Alerta.fecha_generada.desc())
        .all()
    )

    # 8. Planes de mejoramiento pendientes
    planes_pendientes = (
        PlanMejoramiento.query.filter_by(ficha_id=ficha.id, estado='pendiente')
        .order_by(PlanMejoramiento.fecha_creacion.desc())
        .all()
    )

    # 9. Turno de aseo de hoy
    turno_aseo_hoy = (
        TurnoAseo.query.filter_by(ficha_id=ficha.id, fecha=hoy)
        .first()
    )

    # 10. Juicios Evaluativos y RAPs (Consolidado)
    juicios_query = (
        JuicioEvaluativo.query.filter_by(ficha_id=ficha.id)
        .join(Aprendiz, JuicioEvaluativo.aprendiz_id == Aprendiz.id)
        .filter(Aprendiz.estado.in_(ESTADOS_EN_FORMACION))
    )
    juicios = juicios_query.all()
    juicios_totales = len(juicios)
    juicios_aprobados = sum(
        1 for j in juicios
        if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper()
    )
    pct_juicios = round(juicios_aprobados / juicios_totales * 100) if juicios_totales > 0 else 0

    # Certificación al 100% y meta TyT
    juicios_por_aprendiz: Dict[int, Dict[str, int]] = {}
    for j in juicios:
        aid = j.aprendiz_id
        if aid not in juicios_por_aprendiz:
            juicios_por_aprendiz[aid] = {'total': 0, 'aprobados': 0}
        juicios_por_aprendiz[aid]['total'] += 1
        if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper():
            juicios_por_aprendiz[aid]['aprobados'] += 1

    aprendices_certificados = 0
    aprendices_meta_tyt = 0
    for ap in aprendices_activos:
        d = juicios_por_aprendiz.get(ap.id)
        if d and d['total'] > 0:
            if d['total'] == d['aprobados']:
                aprendices_certificados += 1
            if (d['aprobados'] / d['total']) >= 0.7:
                aprendices_meta_tyt += 1

    # Competencias críticas (menor tasa de aprobación)
    comps_map: Dict[str, Dict[str, Any]] = {}
    for j in juicios:
        nombre_c = (j.competencia or '').strip()
        if not nombre_c:
            continue
        if nombre_c not in comps_map:
            comps_map[nombre_c] = {
                'nombre': nombre_c,
                'tipo': j.tipo_competencia or 'tecnica',
                'total': 0,
                'aprobados': 0,
            }
        comps_map[nombre_c]['total'] += 1
        if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper():
            comps_map[nombre_c]['aprobados'] += 1

    for cdata in comps_map.values():
        t = cdata['total']
        ap = cdata['aprobados']
        cdata['pct'] = round(ap / t * 100) if t > 0 else 0
        cdata['pendientes'] = t - ap

    competencias_criticas = sorted(
        comps_map.values(),
        key=lambda c: (c['pct'], -c['pendientes'])
    )[:4]

    # 11. Últimas notas registradas en observador
    ultimas_notas = (
        NotaObservador.query.filter_by(ficha_id=ficha.id)
        .order_by(NotaObservador.fecha.desc(), NotaObservador.id.desc())
        .limit(5)
        .all()
    )

    # 12. Consolidación del resumen
    resultado = {
        'ficha': ficha,
        'cronograma': cronograma,
        'fases_data': fases_data,
        'config_alertas': config_alertas,

        # Aprendices
        'total_aprendices': total_activos,
        'total_aprendices_general': total_general,
        'estados_distribucion': estados_distribucion,
        'aprendices_activos': aprendices_activos,

        # Lo Urgente (Atención Inmediata)
        'aprendices_riesgo_rojo': aprendices_rojo,
        'aprendices_riesgo_amarillo': aprendices_amarillo,
        'aprendices_riesgo_verde': aprendices_verde,
        'entregas_pendientes': entregas_pendientes,
        'num_entregas_pendientes': len(entregas_pendientes),
        'alertas_activas': alertas_activas,
        'planes_pendientes': planes_pendientes,
        'turno_aseo_hoy': turno_aseo_hoy,

        # KPIs Asistencia
        'sesiones_asistencia_total': total_sesiones,
        'pct_asistencia_global': pct_asistencia_global,
        'total_faltas_injustificadas': total_faltas_injustificadas,

        # KPIs Tareas
        'tareas_totales': len(todas_tareas),
        'pct_entregas_global': pct_entregas_global,
        'total_entregas_recibidas': total_entregas_recibidas,
        'tareas_proximas_vencer': tareas_proximas,

        # KPIs Académicos (Juicios y RAPs)
        'juicios_totales': juicios_totales,
        'juicios_aprobados': juicios_aprobados,
        'pct_juicios': pct_juicios,
        'aprendices_certificados': aprendices_certificados,
        'pct_certificados': round(aprendices_certificados / total_activos * 100) if total_activos else 0,
        'aprendices_meta_tyt': aprendices_meta_tyt,
        'pct_meta_tyt': round(aprendices_meta_tyt / total_activos * 100) if total_activos else 0,
        'competencias_criticas': competencias_criticas,

        # Observador reciente
        'ultimas_notas_observador': ultimas_notas,
    }

    # 12. Motor de Recomendaciones Pedagógicas y Operativas
    from app.services.recomendaciones import obtener_recomendaciones_ficha

    contexto_recoms = {
        'fases_data': fases_data,
        'cronograma': cronograma,
        'aprendices_rojo': aprendices_rojo,
        'aprendices_amarillo': aprendices_amarillo,
        'aprendices_verde': aprendices_verde,
        'entregas_pendientes': entregas_pendientes,
        'todas_tareas': todas_tareas,
        'alertas_activas': alertas_activas,
        'planes_pendientes': planes_pendientes,
        'extra': {
            'top_competencias': [
                (c['nombre'], {'total': c['total'], 'aprobados': c['aprobados']})
                for c in competencias_criticas
            ]
        },
    }
    recomendaciones = obtener_recomendaciones_ficha(
        ficha.id,
        instructor_id=instructor_id,
        ahora=ahora,
        contexto_precalculado=contexto_recoms,
    )
    resultado['recomendaciones'] = recomendaciones
    resultado['top_recomendacion'] = recomendaciones[0] if recomendaciones else None

    return resultado
