"""Motor de recomendaciones pedagógicas y logros formativos.

Evalúa de manera determinística las diferentes dimensiones del proceso de formación:
1. Ritmo de fases y cronograma (GFPI-F-134 vs SOFIA Plus).
2. Juicios evaluativos y cobertura de competencias.
3. Tareas y ritmo de calificaciones docentes.
4. Asistencia y alertas preventivas de comité (Resolución 009 de 2024).
5. Planes de mejoramiento y debido proceso (Art. 28).
6. Recomendaciones personalizadas y logros alcanzados para el aprendiz.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_

from app import db
from app.models.alertas import (
    Alerta,
    ConfiguracionAlertasComite,
    PlanMejoramiento,
)
from app.models.aprendiz import Aprendiz, ESTADOS_EN_FORMACION
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.models.ficha import Ficha
from app.models.insignia import Insignia, InsigniaOtorgada
from app.models.juicio import JuicioEvaluativo
from app.models.tarea import Entrega, MODALIDAD_EVIDENCIA, Tarea
from app.services.cronograma import obtener_cronograma
from app.services.fases_dashboard import obtener_seguimiento_fases_dashboard


# Categorías de recomendaciones
CAT_FASES = 'fases_cronograma'
CAT_JUICIOS = 'juicios_evaluativos'
CAT_TAREAS = 'tareas_calificaciones'
CAT_ASISTENCIA = 'asistencia_comite'
CAT_PLANES = 'planes_mejoramiento'
CAT_RECONOCIMIENTOS = 'reconocimientos'

# Niveles de severidad y prioridad
SEV_CRITICA = 'critica'        # Acción inmediata requerida (rojo / riesgo inminente)
SEV_PREVENTIVA = 'preventiva'  # Atención temprana (ámbar / seguimiento)
SEV_SUGERENCIA = 'sugerencia'  # Mejora operativa o pedagógica (azul / informativo)
SEV_POSITIVA = 'positiva'      # Hito positivo o reconocimiento (verde / logro)


@dataclass
class Recomendacion:
    id: str
    categoria: str
    severidad: str
    icono: str
    titulo: str
    mensaje: str
    accion_texto: Optional[str] = None
    accion_url: Optional[str] = None
    metrica_destacada: Optional[str] = None
    destinatario: str = 'instructor'  # 'instructor' o 'aprendiz'
    prioridad: int = 10  # Menor número = mayor prioridad (1 es máxima)
    contexto: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LogroAprendiz:
    codigo: str
    titulo: str
    descripcion: str
    icono: str
    categoria: str
    nivel: str  # 'bronce', 'plata', 'oro', 'diamante'
    desbloqueado: bool
    progreso_actual: int
    progreso_meta: int
    porcentaje: int
    fecha_logro: Optional[str] = None
    mensaje_feedback: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# EVALUADORES PARA EL INSTRUCTOR
# ─────────────────────────────────────────────────────────────────────────────

def _evaluar_ritmo_fases_instructor(
    ficha: Ficha,
    fases_data: Dict[str, Any],
    cronograma: Dict[str, Any],
) -> List[Recomendacion]:
    recomendaciones: List[Recomendacion] = []
    if not fases_data or not fases_data.get('disponible'):
        return recomendaciones

    desfase = fases_data.get('desfase_fases', 0)
    fase_esperada = fases_data.get('fase_esperada', {})
    fase_real = fases_data.get('fase_real', {})
    nombre_esperada = (fase_esperada.get('nombre') or '').title()
    nombre_real = (fase_real.get('nombre') or '').title()

    # R1: Desfase de fases (el caso emblemático del usuario)
    if desfase > 0:
        severidad = SEV_CRITICA if desfase >= 2 else SEV_PREVENTIVA
        prioridad = 1 if desfase >= 2 else 2
        raps_pend = fase_real.get('resultados_total', 0) - fase_real.get('resultados_aprobados', 0)
        metrica = f"Retraso de {desfase} {'fase' if desfase == 1 else 'fases'}"
        if raps_pend > 0:
            metrica += f" · {raps_pend} RAPs pendientes"

        recomendaciones.append(
            Recomendacion(
                id=f'desfase_fase_{ficha.id}',
                categoria=CAT_FASES,
                severidad=severidad,
                icono='⏰',
                titulo=f'Priorizar evaluaciones de {nombre_real}',
                mensaje=(
                    f'El grupo está en fase de {nombre_esperada} por calendario, '
                    f'pero aún tiene resultados pendientes de {nombre_real}. '
                    f'Se recomienda asentar juicios en SOFIA Plus con los instructores responsables.'
                ),
                accion_texto='Revisar juicios en SOFIA Plus',
                accion_url=f'/instructor/fichas/{ficha.id}/juicios',
                metrica_destacada=metrica,
                prioridad=prioridad,
                contexto={
                    'desfase': desfase,
                    'fase_esperada': nombre_esperada,
                    'fase_real': nombre_real,
                },
            )
        )
    elif desfase < 0:
        # Ficha adelantada
        recomendaciones.append(
            Recomendacion(
                id=f'fase_adelantada_{ficha.id}',
                categoria=CAT_FASES,
                severidad=SEV_POSITIVA,
                icono='🚀',
                titulo=f'Ritmo de avance sobresaliente en {nombre_real}',
                mensaje=(
                    f'El grupo ha superado el ritmo lectivo y se encuentra en fase de {nombre_real} '
                    f'con aprobación anticipada de resultados de aprendizaje.'
                ),
                accion_texto='Ver progreso pedagógico',
                accion_url=f'/instructor/fichas/{ficha.id}/vision-general',
                metrica_destacada='Ritmo adelantado',
                prioridad=8,
            )
        )
    elif cronograma.get('configurado'):
        # Al día
        recomendaciones.append(
            Recomendacion(
                id=f'fase_al_dia_{ficha.id}',
                categoria=CAT_FASES,
                severidad=SEV_POSITIVA,
                icono='✅',
                titulo=f'Formación sincronizada en fase de {nombre_esperada}',
                mensaje=(
                    f'El calendario y la aprobación de resultados de aprendizaje marchan alineados '
                    f'en fase de {nombre_esperada}.'
                ),
                accion_texto='Ver detalles',
                accion_url=f'/instructor/fichas/{ficha.id}/vision-general',
                metrica_destacada='Al día con el cronograma',
                prioridad=9,
            )
        )

    # R2: Transición próxima a etapa productiva
    if cronograma.get('dias_restantes_lectiva') is not None:
        dias_lectiva = cronograma.get('dias_restantes_lectiva')
        if 0 < dias_lectiva <= 45:
            resumen_raps = fases_data.get('resumen_raps', {})
            pct_raps = resumen_raps.get('porcentaje_aprobados', 0)
            if pct_raps < 95:
                recomendaciones.append(
                    Recomendacion(
                        id=f'transicion_productiva_{ficha.id}',
                        categoria=CAT_FASES,
                        severidad=SEV_CRITICA,
                        icono='🎓',
                        titulo='Asegurar paz y salvo académico para Etapa Productiva',
                        mensaje=(
                            f'Quedan {dias_lectiva} días para finalizar la etapa lectiva y el avance '
                            f'en RAPs es del {pct_raps}%. Sin el 100% de juicios aprobados los aprendices '
                            f'no podrán iniciar etapa productiva.'
                        ),
                        accion_texto='Auditar RAPs faltantes',
                        accion_url=f'/instructor/fichas/{ficha.id}/juicios',
                        metrica_destacada=f'{dias_lectiva} días restantes · {pct_raps}% RAPs',
                        prioridad=1,
                    )
                )

    return recomendaciones


def _evaluar_juicios_instructor(
    ficha: Ficha,
    aprendices_activos: List[Aprendiz],
    top_competencias: Optional[List[tuple]] = None,
) -> List[Recomendacion]:
    recomendaciones: List[Recomendacion] = []
    total_activos = len(aprendices_activos)
    if total_activos == 0:
        return recomendaciones

    # R3: Competencias con bajo índice de aprobación
    if top_competencias:
        for comp_name, comp_data in top_competencias:
            total_eval = comp_data.get('total', 0)
            aprobados = comp_data.get('aprobados', 0)
            if total_eval > 0:
                pct = round((aprobados / total_eval) * 100)
                if pct < 60:
                    nombre_corto = comp_name[:50] + '...' if len(comp_name) > 50 else comp_name
                    recomendaciones.append(
                        Recomendacion(
                            id=f'competencia_critica_{hash(comp_name)}_{ficha.id}',
                            categoria=CAT_JUICIOS,
                            severidad=SEV_CRITICA if pct < 40 else SEV_PREVENTIVA,
                            icono='📊',
                            titulo=f'Bajo índice en: {nombre_corto}',
                            mensaje=(
                                f'La competencia registra apenas un {pct}% de resultados aprobados '
                                f'({aprobados} de {total_eval}). Se sugiere acordar actividades de nivelación '
                                f'o concertar con el instructor de la competencia.'
                            ),
                            accion_texto='Explorar competencia',
                            accion_url=f'/instructor/fichas/{ficha.id}/juicios',
                            metrica_destacada=f'{pct}% aprobación',
                            prioridad=3 if pct < 40 else 4,
                        )
                    )
                    break  # Mostramos la más crítica para no saturar

    # R4: Aprendices a punto de cerrar competencia (1 o 2 RAPs faltantes)
    filas_pend = (
        db.session.query(
            JuicioEvaluativo.aprendiz_id,
            func.count(JuicioEvaluativo.id).label('pendientes'),
        )
        .filter(
            JuicioEvaluativo.ficha_id == ficha.id,
            JuicioEvaluativo.aprendiz_id.in_([a.id for a in aprendices_activos]),
            or_(
                JuicioEvaluativo.juicio.is_(None),
                JuicioEvaluativo.juicio.ilike('%POR EVALUAR%'),
                JuicioEvaluativo.juicio.ilike('%AUN NO%'),
            ),
        )
        .group_by(JuicioEvaluativo.aprendiz_id)
        .having(func.count(JuicioEvaluativo.id) <= 2)
        .all()
    )
    if filas_pend and len(filas_pend) >= 3:
        recomendaciones.append(
            Recomendacion(
                id=f'aprendices_por_cerrar_{ficha.id}',
                categoria=CAT_JUICIOS,
                severidad=SEV_SUGERENCIA,
                icono='🎯',
                titulo='Oportunidad de cierre para aprendices rezagados leves',
                mensaje=(
                    f'{len(filas_pend)} aprendices tienen solo 1 o 2 resultados pendientes '
                    f'para completar todos sus juicios evaluativos. Una revisión focalizada '
                    f'permitirá cerrar su estado académico.'
                ),
                accion_texto='Ver lista de aprendices',
                accion_url=f'/instructor/fichas/{ficha.id}/aprendices',
                metrica_destacada=f'{len(filas_pend)} aprendices casi al 100%',
                prioridad=5,
            )
        )

    return recomendaciones


def _evaluar_tareas_instructor(
    ficha: Ficha,
    entregas_pendientes: List[Entrega],
    todas_tareas: List[Tarea],
    total_activos: int,
    ahora: datetime,
) -> List[Recomendacion]:
    recomendaciones: List[Recomendacion] = []

    # R5: Cuello de botella docente (entregas con más de 3 días hábiles sin calificar)
    limite_dias = ahora - timedelta(days=3)
    entregas_antiguas = [
        e for e in entregas_pendientes
        if e.fecha_entrega and e.fecha_entrega <= limite_dias
    ]
    total_sin_calificar = len(entregas_pendientes)

    if entregas_antiguas:
        recomendaciones.append(
            Recomendacion(
                id=f'entregas_retrasadas_docente_{ficha.id}',
                categoria=CAT_TAREAS,
                severidad=SEV_PREVENTIVA,
                icono='📝',
                titulo='Priorizar calificación de evidencias enviadas',
                mensaje=(
                    f'Hay {len(entregas_antiguas)} evidencias con más de 3 días esperando '
                    f'retroalimentación. Calificar a tiempo permite al aprendiz corregir antes de la siguiente fase.'
                ),
                accion_texto='Ir a calificar',
                accion_url=f'/instructor/fichas/{ficha.id}/tareas',
                metrica_destacada=f'{len(entregas_antiguas)} de {total_sin_calificar} con demora',
                prioridad=3,
            )
        )
    elif total_sin_calificar > 10:
        recomendaciones.append(
            Recomendacion(
                id=f'entregas_pendientes_volumen_{ficha.id}',
                categoria=CAT_TAREAS,
                severidad=SEV_SUGERENCIA,
                icono='📥',
                titulo='Acumulación de evidencias por revisar',
                mensaje=(
                    f'Se registran {total_sin_calificar} entregas pendientes de revisión en la ficha. '
                    f'Dedica un bloque de tiempo a asentar calificaciones.'
                ),
                accion_texto='Revisar tareas',
                accion_url=f'/instructor/fichas/{ficha.id}/tareas',
                metrica_destacada=f'{total_sin_calificar} por calificar',
                prioridad=6,
            )
        )

    # R6: Tareas próximas a vencer con baja entrega
    limite_proximo = ahora + timedelta(hours=48)
    for t in todas_tareas:
        if t.fecha_limite and ahora <= t.fecha_limite <= limite_proximo:
            entregadas_count = Entrega.query.filter_by(tarea_id=t.id).count()
            if total_activos > 0:
                pct_entregado = round((entregadas_count / total_activos) * 100)
                if pct_entregado < 50:
                    horas_restantes = max(round((t.fecha_limite - ahora).total_seconds() / 3600), 1)
                    recomendaciones.append(
                        Recomendacion(
                            id=f'tarea_por_vencer_baja_entrega_{t.id}',
                            categoria=CAT_TAREAS,
                            severidad=SEV_PREVENTIVA,
                            icono='⏳',
                            titulo=f'Baja entrega en tarea por vencer: {t.titulo[:35]}',
                            mensaje=(
                                f'La tarea vence en {horas_restantes}h y solo el {pct_entregado}% '
                                f'del grupo ({entregadas_count}/{total_activos}) ha entregado. '
                                f'Se sugiere enviar un recordatorio en clase o verificar bloqueos técnicos.'
                            ),
                            accion_texto='Ver tarea',
                            accion_url=f'/instructor/fichas/{ficha.id}/tareas',
                            metrica_destacada=f'{pct_entregado}% entregado · {horas_restantes}h restantes',
                            prioridad=4,
                        )
                    )
                    break

    return recomendaciones


def _evaluar_asistencia_comite_instructor(
    ficha: Ficha,
    aprendices_rojo: List[Dict[str, Any]],
    aprendices_amarillo: List[Dict[str, Any]],
    alertas_activas: List[Alerta],
    planes_pendientes: List[PlanMejoramiento],
    ahora: datetime,
) -> List[Recomendacion]:
    recomendaciones: List[Recomendacion] = []

    # R7: Aprendices en riesgo inminente de comité
    alertas_comite = [a for a in alertas_activas if a.tipo == 'comite_desercion']
    if alertas_comite:
        total_comite = len(alertas_comite)
        recomendaciones.append(
            Recomendacion(
                id=f'riesgo_comite_ficha_{ficha.id}',
                categoria=CAT_ASISTENCIA,
                severidad=SEV_CRITICA,
                icono='🚨',
                titulo=f'{total_comite} aprendiz{"ces" if total_comite > 1 else ""} en causal de comité',
                mensaje=(
                    f'Se han detectado {total_comite} aprendices que cumplen causales del '
                    f'Reglamento del Aprendiz (Res. 009/2024 Art. 22) por inasistencia reiterada. '
                    f'Es imperativo citar a comité o formalizar el debido proceso.'
                ),
                accion_texto='Gestionar casos de comité',
                accion_url=f'/instructor/fichas/{ficha.id}/casos-seguimiento',
                metrica_destacada=f'{total_comite} casos críticos',
                prioridad=1,
            )
        )
    elif aprendices_rojo:
        total_rojo = len(aprendices_rojo)
        recomendaciones.append(
            Recomendacion(
                id=f'semaforo_rojo_ficha_{ficha.id}',
                categoria=CAT_ASISTENCIA,
                severidad=SEV_PREVENTIVA,
                icono='⚠️',
                titulo=f'{total_rojo} aprendiz{"ces" if total_rojo > 1 else ""} en semáforo rojo',
                mensaje=(
                    f'{total_rojo} aprendices presentan fallas acumuladas o tareas pendientes '
                    f'por encima del umbral de alerta. Conviene coordinar un plan de apoyo preventivo.'
                ),
                accion_texto='Ver semáforo',
                accion_url=f'/instructor/fichas/{ficha.id}/vision-general',
                metrica_destacada=f'{total_rojo} en riesgo',
                prioridad=2,
            )
        )

    # R8: Planes de mejoramiento próximos a vencer sin evidencia
    planes_urgentes = []
    limite_plan = ahora + timedelta(days=2)
    for p in planes_pendientes:
        if p.fecha_limite and p.fecha_limite <= limite_plan and not p.evidencia_url:
            planes_urgentes.append(p)

    if planes_urgentes:
        recomendaciones.append(
            Recomendacion(
                id=f'planes_por_vencer_{ficha.id}',
                categoria=CAT_PLANES,
                severidad=SEV_CRITICA,
                icono='📋',
                titulo=f'{len(planes_urgentes)} plan{"es" if len(planes_urgentes) > 1 else ""} de mejora por vencer sin soporte',
                mensaje=(
                    f'Los planes acordados bajo Art. 28 vencen en menos de 48 horas y los aprendices '
                    f'aún no han cargado evidencia. Si vencen sin cumplimiento procede auto-escalación a comité.'
                ),
                accion_texto='Revisar planes',
                accion_url=f'/instructor/fichas/{ficha.id}/planes-mejoramiento',
                metrica_destacada=f'{len(planes_urgentes)} planes por vencer',
                prioridad=2,
            )
        )

    # R9: Evidencias de planes enviadas esperando revisión
    planes_con_evidencia = [p for p in planes_pendientes if p.evidencia_url]
    if planes_con_evidencia:
        recomendaciones.append(
            Recomendacion(
                id=f'planes_con_evidencia_{ficha.id}',
                categoria=CAT_PLANES,
                severidad=SEV_SUGERENCIA,
                icono='📄',
                titulo=f'{len(planes_con_evidencia)} evidencia{"s" if len(planes_con_evidencia) > 1 else ""} de plan esperando veredicto',
                mensaje=(
                    f'Hay aprendices que ya entregaron el soporte de su plan de mejoramiento. '
                    f'Valida las evidencias para levantar las alertas o dar por cumplido el caso.'
                ),
                accion_texto='Calificar planes',
                accion_url=f'/instructor/fichas/{ficha.id}/planes-mejoramiento',
                metrica_destacada=f'{len(planes_con_evidencia)} por calificar',
                prioridad=4,
            )
        )

    return recomendaciones


def obtener_recomendaciones_ficha(
    ficha_id: int,
    instructor_id: Optional[int] = None,
    ahora: Optional[datetime] = None,
    contexto_precalculado: Optional[Dict[str, Any]] = None,
) -> List[Recomendacion]:
    """Obtiene y prioriza las recomendaciones pedagógicas y operativas para la ficha."""
    ahora = ahora or datetime.utcnow()
    hoy = ahora.date()
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        return []

    # Extraer datos precalculados si vienen de resumen_ficha_360 para evitar duplicar queries
    if contexto_precalculado:
        fases_data = contexto_precalculado.get('fases_data', {})
        cronograma = contexto_precalculado.get('cronograma', {})
        aprendices_activos = [item['aprendiz'] for item in contexto_precalculado.get('aprendices_verde', [])] + \
                             [item['aprendiz'] for item in contexto_precalculado.get('aprendices_amarillo', [])] + \
                             [item['aprendiz'] for item in contexto_precalculado.get('aprendices_rojo', [])]
        top_competencias = contexto_precalculado.get('extra', {}).get('top_competencias')
        entregas_pendientes = contexto_precalculado.get('entregas_pendientes', [])
        todas_tareas = contexto_precalculado.get('todas_tareas', [])
        aprendices_rojo = contexto_precalculado.get('aprendices_rojo', [])
        aprendices_amarillo = contexto_precalculado.get('aprendices_amarillo', [])
        alertas_activas = contexto_precalculado.get('alertas_activas', [])
        planes_pendientes = contexto_precalculado.get('planes_pendientes', [])
    else:
        cronograma = obtener_cronograma(ficha)
        fases_data = obtener_seguimiento_fases_dashboard(ficha, cronograma, hoy=hoy)
        aprendices_activos = Aprendiz.query_en_formacion(ficha_id).all()
        top_competencias = None
        entregas_pendientes = (
            Entrega.query
            .join(Tarea, Entrega.tarea_id == Tarea.id)
            .filter(
                Tarea.ficha_id == ficha_id,
                Tarea.modalidad == MODALIDAD_EVIDENCIA,
                or_(Entrega.calificada == False, Entrega.estado_revision == 'pendiente'),
            )
            .all()
        )
        todas_tareas = Tarea.query.filter_by(ficha_id=ficha_id).all()
        aprendices_rojo = []
        aprendices_amarillo = []
        alertas_activas = Alerta.query.filter_by(ficha_id=ficha_id, estado='activa').all()
        planes_pendientes = PlanMejoramiento.query.filter_by(ficha_id=ficha_id, estado='pendiente').all()

    todas: List[Recomendacion] = []
    todas.extend(_evaluar_ritmo_fases_instructor(ficha, fases_data, cronograma))
    todas.extend(_evaluar_juicios_instructor(ficha, aprendices_activos, top_competencias))
    todas.extend(_evaluar_tareas_instructor(ficha, entregas_pendientes, todas_tareas, len(aprendices_activos), ahora))
    todas.extend(_evaluar_asistencia_comite_instructor(
        ficha, aprendices_rojo, aprendices_amarillo, alertas_activas, planes_pendientes, ahora
    ))

    # Ordenar por prioridad (1 es más urgente) y luego por severidad
    severidad_orden = {SEV_CRITICA: 0, SEV_PREVENTIVA: 1, SEV_SUGERENCIA: 2, SEV_POSITIVA: 3}
    todas.sort(key=lambda r: (r.prioridad, severidad_orden.get(r.severidad, 99)))
    return todas


# ─────────────────────────────────────────────────────────────────────────────
# EVALUADORES PARA EL APRENDIZ (RECOMENDACIONES Y LOGROS)
# ─────────────────────────────────────────────────────────────────────────────

def obtener_recomendaciones_aprendiz(
    ficha_id: int,
    aprendiz_id: int,
    ahora: Optional[datetime] = None,
) -> List[Recomendacion]:
    """Genera recomendaciones de acción personalizadas para un aprendiz específico."""
    ahora = ahora or datetime.utcnow()
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not aprendiz:
        return []

    recomendaciones: List[Recomendacion] = []

    # 1. Tareas próximas a vencer no entregadas
    tareas = Tarea.query.filter_by(ficha_id=ficha_id).all()
    entregas = {e.tarea_id: e for e in Entrega.query.filter_by(aprendiz_id=aprendiz_id).all()}

    tareas_pendientes_urgentes = []
    limite_48h = ahora + timedelta(hours=48)
    for t in tareas:
        ent = entregas.get(t.id)
        if not ent and t.fecha_limite and ahora <= t.fecha_limite <= limite_48h:
            tareas_pendientes_urgentes.append(t)

    for t in tareas_pendientes_urgentes[:2]:
        horas = max(round((t.fecha_limite - ahora).total_seconds() / 3600), 1)
        recomendaciones.append(
            Recomendacion(
                id=f'aprendiz_tarea_urgente_{t.id}',
                categoria=CAT_TAREAS,
                severidad=SEV_CRITICA if horas <= 24 else SEV_PREVENTIVA,
                icono='⏰',
                titulo=f'Entrega pendiente: {t.titulo[:35]}',
                mensaje=f'Esta actividad vence en {horas} horas. Prepara tu evidencia y envíala antes del cierre.',
                accion_texto='Subir evidencia',
                accion_url=f'#tarea-{t.id}',
                metrica_destacada=f'{horas}h restantes',
                destinatario='aprendiz',
                prioridad=1,
            )
        )

    # 2. Tareas en corrección requerida
    tareas_corregir = [
        ent for ent in entregas.values()
        if ent.estado_revision == 'rechazada'
    ]
    for ent in tareas_corregir[:2]:
        nombre_tarea = ent.tarea.titulo if ent.tarea else 'Actividad'
        recomendaciones.append(
            Recomendacion(
                id=f'aprendiz_corregir_{ent.id}',
                categoria=CAT_TAREAS,
                severidad=SEV_PREVENTIVA,
                icono='✏️',
                titulo=f'Corrección solicitada: {nombre_tarea[:35]}',
                mensaje=(
                    f'Tu instructor ha solicitado ajustes en tu entrega. '
                    f'Revisa las observaciones y carga nuevamente tu trabajo.'
                ),
                accion_texto='Ver retroalimentación',
                accion_url=f'#tarea-{ent.tarea_id}',
                metrica_destacada='Ajuste pendiente',
                destinatario='aprendiz',
                prioridad=2,
            )
        )

    # 3. Asistencia en riesgo (Res. 009)
    total_sesiones = SesionAsistencia.query.filter_by(ficha_id=ficha_id).count()
    total_faltas = (
        RegistroAsistencia.query
        .join(SesionAsistencia, RegistroAsistencia.sesion_id == SesionAsistencia.id)
        .filter(
            SesionAsistencia.ficha_id == ficha_id,
            RegistroAsistencia.aprendiz_id == aprendiz_id,
            RegistroAsistencia.estado.in_(['FALTA', 'FALTA_JUSTIFICADA', 'EXCUSA_MEDICA']),
        )
        .count()
    )
    if total_sesiones > 0:
        pct_asis = round(((total_sesiones - total_faltas) / total_sesiones) * 100)
        if 75 <= pct_asis < 82:
            recomendaciones.append(
                Recomendacion(
                    id=f'aprendiz_asistencia_riesgo_{aprendiz_id}',
                    categoria=CAT_ASISTENCIA,
                    severidad=SEV_PREVENTIVA,
                    icono='⚠️',
                    titulo='Tu asistencia está cerca del límite reglamentario',
                    mensaje=(
                        f'Tu porcentaje actual es del {pct_asis}%. La Resolución 009 establece '
                        f'que bajar del 75% es causal de comité de evaluación y deserción. '
                        f'¡Cuida tus próximas asistencias!'
                    ),
                    accion_texto='Consultar historial de asistencia',
                    accion_url='#seccion-asistencia',
                    metrica_destacada=f'{pct_asis}% asistencia',
                    destinatario='aprendiz',
                    prioridad=1,
                )
            )

    # 4. Plan de mejoramiento activo
    plan_activo = (
        PlanMejoramiento.query
        .filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz_id, estado='pendiente')
        .order_by(PlanMejoramiento.fecha_limite.asc())
        .first()
    )
    if plan_activo:
        dias_plan = (plan_activo.fecha_limite - ahora).days if plan_activo.fecha_limite else None
        tiempo_texto = f'Vence en {dias_plan} días' if dias_plan is not None else 'Activo'
        recomendaciones.append(
            Recomendacion(
                id=f'aprendiz_plan_activo_{plan_activo.id}',
                categoria=CAT_PLANES,
                severidad=SEV_CRITICA if (dias_plan is not None and dias_plan <= 2) else SEV_PREVENTIVA,
                icono='📋',
                titulo='Tienes un plan de mejoramiento en curso',
                mensaje=(
                    f'Cumple con los compromisos acordados y carga tu evidencia '
                    f'para que tu instructor pueda validarla a tiempo.'
                ),
                accion_texto='Ir a mi plan de mejoramiento',
                accion_url='#seccion-planes',
                metrica_destacada=tiempo_texto,
                destinatario='aprendiz',
                prioridad=1,
            )
        )

    # 5. Juicios evaluativos - Meta de cierre de fase
    juicios = JuicioEvaluativo.query.filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz_id).all()
    if juicios:
        total_j = len(juicios)
        aprobados_j = sum(
            1 for j in juicios
            if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper()
        )
        pendientes_j = total_j - aprobados_j
        if 0 < pendientes_j <= 3:
            recomendaciones.append(
                Recomendacion(
                    id=f'aprendiz_meta_cierre_juicios_{aprendiz_id}',
                    categoria=CAT_JUICIOS,
                    severidad=SEV_POSITIVA,
                    icono='🎯',
                    titulo='¡Estás muy cerca de completar tus resultados!',
                    mensaje=(
                        f'Solo te faltan {pendientes_j} resultado{"s" if pendientes_j > 1 else ""} '
                        f'de aprendizaje para tener el 100% de tus juicios evaluativos aprobados. '
                        f'Verifica con tus instructores para asentar juicios.'
                    ),
                    accion_texto='Ver mis juicios',
                    accion_url='#seccion-juicios',
                    metrica_destacada=f'{aprobados_j}/{total_j} RAPs aprobados',
                    destinatario='aprendiz',
                    prioridad=3,
                )
            )

    return recomendaciones


def obtener_logros_aprendiz(
    ficha_id: int,
    aprendiz_id: int,
    ahora: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Calcula el estado de logros formativos y feedback motivacional del aprendiz."""
    ahora = ahora or datetime.utcnow()
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not aprendiz:
        return {'logros': [], 'total_desbloqueados': 0, 'resumen_nivel': 'Iniciando'}

    logros: List[LogroAprendiz] = []

    # 1. LOGRO: Racha de Hierro en Asistencia
    # 12 sesiones continuas sin fallas
    total_sesiones = (
        SesionAsistencia.query
        .join(RegistroAsistencia, RegistroAsistencia.sesion_id == SesionAsistencia.id)
        .filter(
            SesionAsistencia.ficha_id == ficha_id,
            RegistroAsistencia.aprendiz_id == aprendiz_id,
        )
        .order_by(SesionAsistencia.fecha.desc())
        .limit(16)
        .all()
    )
    sesiones_asistidas = 0
    for s in total_sesiones:
        reg = next((r for r in s.registros if r.aprendiz_id == aprendiz_id), None)
        if reg and reg.estado in ('PRESENTE', 'RETARDO'):
            sesiones_asistidas += 1
        else:
            break

    meta_racha = 12
    desbloqueado_racha = sesiones_asistidas >= meta_racha
    pct_racha = min(round((sesiones_asistidas / meta_racha) * 100), 100)
    logros.append(
        LogroAprendiz(
            codigo='LOG_RACHA_ASISTENCIA',
            titulo='Racha de Hierro',
            descripcion='Asiste a 12 o más sesiones continuas sin inasistencias injustificadas.',
            icono='⚡',
            categoria='asistencia',
            nivel='oro' if desbloqueado_racha else 'plata',
            desbloqueado=desbloqueado_racha,
            progreso_actual=min(sesiones_asistidas, meta_racha),
            progreso_meta=meta_racha,
            porcentaje=pct_racha,
            mensaje_feedback='¡Excelente compromiso con tu presencia en clase!' if desbloqueado_racha else f'Llevas {sesiones_asistidas} de {meta_racha} sesiones seguidas.',
        )
    )

    # 2. LOGRO: Entregas Impecables (Puntualidad total en tareas)
    entregas = (
        Entrega.query
        .join(Tarea, Entrega.tarea_id == Tarea.id)
        .filter(
            Tarea.ficha_id == ficha_id,
            Entrega.aprendiz_id == aprendiz_id,
        )
        .all()
    )
    total_entregadas = len(entregas)
    a_tiempo = sum(1 for e in entregas if e.entregada_a_tiempo)
    meta_tareas = 5
    desbloqueado_entregas = total_entregadas >= meta_tareas and (a_tiempo == total_entregadas)
    pct_entregas = min(round((a_tiempo / meta_tareas) * 100), 100) if meta_tareas else 0
    logros.append(
        LogroAprendiz(
            codigo='LOG_PUNTUALIDAD_TAREAS',
            titulo='Entregas Impecables',
            descripcion='Entrega al menos 5 evidencias dentro de la fecha límite sin retrasos.',
            icono='🎯',
            categoria='academico',
            nivel='oro' if desbloqueado_entregas else 'bronce',
            desbloqueado=desbloqueado_entregas,
            progreso_actual=min(a_tiempo, meta_tareas),
            progreso_meta=meta_tareas,
            porcentaje=pct_entregas,
            mensaje_feedback='¡Tu puntualidad demuestra gran profesionalismo!' if desbloqueado_entregas else f'{a_tiempo} de {meta_tareas} entregadas a tiempo.',
        )
    )

    # 3. LOGRO: Conquistador de Fase (100% RAPs aprobados de fase actual o global)
    juicios = JuicioEvaluativo.query.filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz_id).all()
    total_juicios = len(juicios)
    aprobados_juicios = sum(
        1 for j in juicios
        if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper()
    )
    meta_juicios = max(total_juicios, 1)
    desbloqueado_fase = (total_juicios > 0) and (aprobados_juicios == total_juicios)
    pct_juicios = round((aprobados_juicios / meta_juicios) * 100) if total_juicios else 0
    logros.append(
        LogroAprendiz(
            codigo='LOG_CONQUISTADOR_FASE',
            titulo='Conquistador Curricular',
            descripcion='Alcanza el 100% de aprobación en los resultados de aprendizaje registrados.',
            icono='🎓',
            categoria='progreso',
            nivel='diamante' if desbloqueado_fase else 'oro',
            desbloqueado=desbloqueado_fase,
            progreso_actual=aprobados_juicios,
            progreso_meta=meta_juicios,
            porcentaje=pct_juicios,
            mensaje_feedback='¡Meta alcanzada! Tienes todos tus resultados aprobados.' if desbloqueado_fase else f'Avance curricular del {pct_juicios}%.',
        )
    )

    # 4. LOGRO: Resiliencia Formativa (Superó un plan de mejoramiento)
    plan_cumplido = (
        PlanMejoramiento.query
        .filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz_id, estado='cumplido')
        .first()
    )
    desbloqueado_resiliencia = plan_cumplido is not None
    logros.append(
        LogroAprendiz(
            codigo='LOG_RESILIENCIA',
            titulo='Resiliencia y Superación',
            descripcion='Cumple exitosamente un plan de mejoramiento académico o disciplinario.',
            icono='🌱',
            categoria='resiliencia',
            nivel='plata',
            desbloqueado=desbloqueado_resiliencia,
            progreso_actual=1 if desbloqueado_resiliencia else 0,
            progreso_meta=1,
            porcentaje=100 if desbloqueado_resiliencia else 0,
            mensaje_feedback='Demostraste capacidad de superar obstáculos y levantarte con éxito.' if desbloqueado_resiliencia else 'Cumple tus compromisos para desbloquear este reconocimiento.',
        )
    )

    # 5. LOGRO: Pionero de Entrega (Primera entrega de una tarea)
    insignia_pionero = (
        InsigniaOtorgada.query
        .join(Insignia, InsigniaOtorgada.insignia_id == Insignia.id)
        .filter(
            InsigniaOtorgada.aprendiz_id == aprendiz_id,
            Insignia.codigo.in_(['PRIMERO_ENTREGAR', 'NUNCA_TARDE']),
        )
        .first()
    )
    desbloqueado_pionero = insignia_pionero is not None
    logros.append(
        LogroAprendiz(
            codigo='LOG_PIONERO',
            titulo='Pionero de Clase',
            descripcion='Sé de los primeros en enviar una evidencia con alta calidad técnica.',
            icono='🚀',
            categoria='academico',
            nivel='bronce',
            desbloqueado=desbloqueado_pionero,
            progreso_actual=1 if desbloqueado_pionero else 0,
            progreso_meta=1,
            porcentaje=100 if desbloqueado_pionero else 0,
            mensaje_feedback='¡Tu iniciativa e interés marcan el ritmo del grupo!' if desbloqueado_pionero else 'Entrega con anticipación tus próximas evidencias para obtenerlo.',
        )
    )

    total_desbloqueados = sum(1 for l in logros if l.desbloqueado)
    if total_desbloqueados >= 4:
        rango = 'Aprendiz Destacado (Diamante)'
    elif total_desbloqueados >= 2:
        rango = 'En Pleno Crecimiento (Oro)'
    elif total_desbloqueados >= 1:
        rango = 'Primeros Hitos (Plata)'
    else:
        rango = 'Comenzando el Camino (Bronce)'

    return {
        'logros': logros,
        'total_desbloqueados': total_desbloqueados,
        'total_logros': len(logros),
        'porcentaje_global': round((total_desbloqueados / len(logros)) * 100) if logros else 0,
        'rango': rango,
    }
