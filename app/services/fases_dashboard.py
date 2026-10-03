"""Servicio de seguimiento de fases del proyecto formativo para el dashboard.

Calcula la fase esperada (acorde al tiempo lectivo transcurrido) y la fase real
(acorde a los resultados de aprendizaje aprobados en SOFIA Plus), adaptándose
según los archivos disponibles:
1. Con Planeación Pedagógica (GFPI-F-134): Mapeo exacto de RAPs por fase y horas.
2. Sin Planeación Pedagógica (solo Reporte de Juicios): Proyección estándar basada
   en las 4 fases del modelo de proyectos del SENA y el avance de juicios.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from flask import current_app

from app import db
from app.models.archivo_ficha import ArchivoFichaVersion, TIPO_PLANEACION, TIPO_REPORTE_JUICIOS
from app.models.aprendiz import Aprendiz, ESTADOS_EN_FORMACION
from app.models.ficha import Ficha
from app.models.juicio import JuicioEvaluativo
from app.services.analisis_planeacion import construir_analisis
from app.services.calendario_formacion import construir_calendario
from app.services.cronograma import obtener_cronograma
from app.services.linea_tiempo import construir_linea_tiempo
from app.services.planeacion import parsear_planeacion
from app.services.resultados_persistidos import (
    fecha_corte_bogota,
    obtener_contenido_documento,
    obtener_resultado_persistido,
)
from app.services.seguimiento_fases import FASES_PROYECTO, construir_seguimiento_fases
from app.services.versiones_archivos import ultima_version

_VERSION_NO_PROVISTA = object()

# Memoización por proceso; la extracción primaria ya vive en PostgreSQL.
_CACHE_PLANEACION_PARSED: Dict[tuple, Dict[str, Any]] = {}

# Distribución estándar de fases por porcentaje de etapa lectiva en proyectos SENA
# Análisis (25%), Planeación (25%), Ejecución (35%), Evaluación (15%)
UMBRALES_ESTANDAR_FASES = [
    ('ANÁLISIS', '🔍', 0.0, 25.0),
    ('PLANEACIÓN', '📐', 25.0, 50.0),
    ('EJECUCIÓN', '⚙️', 50.0, 85.0),
    ('EVALUACIÓN', '🎯', 85.0, 100.0),
]


def _buscar_planeacion_compartida(
    ficha: Ficha,
    cache_programa: Optional[Dict[str, Optional[ArchivoFichaVersion]]] = None,
) -> Optional[ArchivoFichaVersion]:
    """Busca planeación procesada de otra ficha con el mismo código de programa."""
    if not ficha.codigo_programa:
        return None
    if cache_programa is not None and ficha.codigo_programa in cache_programa:
        return cache_programa[ficha.codigo_programa]

    version_compartida = (
        ArchivoFichaVersion.query.join(Ficha, ArchivoFichaVersion.ficha_id == Ficha.id)
        .filter(
            Ficha.codigo_programa == ficha.codigo_programa,
            Ficha.id != ficha.id,
            ArchivoFichaVersion.tipo == TIPO_PLANEACION,
            ArchivoFichaVersion.estado == 'procesado',
        )
        .order_by(ArchivoFichaVersion.version.desc())
        .first()
    )
    if cache_programa is not None:
        cache_programa[ficha.codigo_programa] = version_compartida
    return version_compartida


def _buscar_version_planeacion(
    ficha: Ficha,
    cache_programa: Optional[Dict[str, Optional[ArchivoFichaVersion]]] = None,
) -> Optional[ArchivoFichaVersion]:
    """Busca la planeación procesada de la ficha o de otra ficha del mismo programa."""
    # 1. Planeación directa de la ficha
    version = ultima_version(ficha.id, TIPO_PLANEACION, solo_procesadas=True)
    if version:
        return version

    # 2. Fallback: buscar planeación válida de otra ficha con el mismo código de programa
    return _buscar_planeacion_compartida(ficha, cache_programa=cache_programa)


def _obtener_planeacion_parseada(version: ArchivoFichaVersion) -> Optional[Dict[str, Any]]:
    """Carga y parsea la planeación pedagógica con memoización en memoria."""
    clave_cache = (version.id, version.tamano_bytes, version.hash_sha256)
    if clave_cache in _CACHE_PLANEACION_PARSED:
        return _CACHE_PLANEACION_PARSED[clave_cache]

    try:
        contenido = obtener_contenido_documento(
            version, parsear_planeacion, parser_version='planeacion-v1',
        )
        _CACHE_PLANEACION_PARSED[clave_cache] = contenido
        return contenido
    except Exception:
        current_app.logger.exception('Error parseando planeación en versión %s', version.id)
        return None


def _calcular_con_planeacion(
    ficha: Ficha,
    version_planeacion: ArchivoFichaVersion,
    contenido_planeacion: Dict[str, Any],
    hoy: date,
    version_reporte: Any = _VERSION_NO_PROVISTA,
) -> Dict[str, Any]:
    """Calcula el seguimiento exacto de fases cruzando GFPI-F-134 con los juicios."""
    if version_reporte is _VERSION_NO_PROVISTA:
        version_reporte = ultima_version(
            ficha.id, TIPO_REPORTE_JUICIOS, solo_procesadas=True, recuperar_reporte=False,
        )
    analisis = construir_analisis(
        ficha,
        contenido_planeacion,
        version_planeacion=version_planeacion,
        version_reporte=version_reporte,
        hoy=hoy,
    )
    calendario = construir_calendario(ficha, hoy=hoy)
    aprendices_meta = analisis['resumen']['aprendices_analizados']
    linea = construir_linea_tiempo(
        analisis['items'],
        calendario,
        aprendices_meta=aprendices_meta,
        hoy=hoy,
    )
    seguimiento = construir_seguimiento_fases(linea, calendario, hoy=hoy)

    # Identificar competencias pendientes agrupadas por fase
    pendientes_por_fase: Dict[str, Dict[str, int]] = {}
    items_linea = linea.get('resultados', []) if isinstance(linea, dict) else (linea if isinstance(linea, list) else [])
    for item in items_linea:
        if not isinstance(item, dict):
            continue
        fase_nom = (item.get('fase') or 'Sin fase').upper().strip()
        pct = float(item.get('porcentaje_avance') or 0.0)
        if pct < 80.0:
            comp_nom = (item.get('competencia') or 'Competencia sin nombre').strip()
            pendientes_por_fase.setdefault(fase_nom, {}).setdefault(comp_nom, 0)
            pendientes_por_fase[fase_nom][comp_nom] += 1

    fases_formateadas = []
    for fase in seguimiento.get('fases', []):
        nombre_fase_upper = (fase.get('nombre') or '').upper().strip()
        comps_pend_dict = pendientes_por_fase.get(nombre_fase_upper, {})
        comps_pend_list = [
            {'competencia': comp, 'pendientes': count}
            for comp, count in sorted(comps_pend_dict.items(), key=lambda x: -x[1])
        ]

        fases_formateadas.append({
            'orden': fase.get('orden', 0),
            'nombre': fase.get('nombre'),
            'icono': fase.get('icono', '📌'),
            'inicio': fase.get('inicio'),
            'fin': fase.get('fin'),
            'porcentaje_tiempo': fase.get('porcentaje_tiempo', 0),
            'porcentaje_aprobados': fase.get('porcentaje_aprobados', 0),
            'porcentaje_evaluados': fase.get('porcentaje_evaluados', 0),
            'resultados_esperados': fase.get('resultados_esperados', 0),
            'resultados_aprobados': fase.get('resultados_aprobados', 0),
            'resultados_evaluados': fase.get('resultados_evaluados', 0),
            'resultados_pendientes': fase.get('resultados_pendientes', 0),
            'resultados_total': fase.get('resultados_total', 0),
            'brecha_resultados': fase.get('brecha_resultados', 0),
            'estado_tiempo': fase.get('estado_tiempo', 'pendiente'),
            'estado_ritmo': fase.get('estado_ritmo', 'al_dia'),
            'horas': fase.get('horas', 0),
            'competencias_total': fase.get('competencias_total', 0),
            'competencias_pendientes': comps_pend_list,
        })

    fase_esperada = seguimiento.get('fase_esperada')
    fase_real = seguimiento.get('fase_real')
    estado = seguimiento.get('estado', 'al_dia')

    desfase = 0
    if fase_esperada and fase_real:
        desfase = fase_esperada.get('orden', 0) - fase_real.get('orden', 0)

    res_data = seguimiento.get('resultados', {})
    total_raps = res_data.get('total', 0)
    aprobados_raps = res_data.get('aprobados', 0)
    evaluados_raps = res_data.get('evaluados', 0)
    pendientes_raps = res_data.get('pendientes', 0)
    esperados_raps = res_data.get('esperados', 0)
    pct_aprobados = res_data.get('porcentaje_aprobados', 0)
    pct_esperados = round((esperados_raps / total_raps * 100), 1) if total_raps else 0.0

    raps_vencidos_pendientes = sum(
        f.get('resultados_pendientes', 0)
        for f in fases_formateadas
        if f.get('estado_tiempo') == 'vencida'
    )
    fases_vencidas_info = [
        {
            'nombre': f['nombre'],
            'pendientes': f['resultados_pendientes'],
            'total': f['resultados_total'],
            'aprobados': f['resultados_aprobados'],
        }
        for f in fases_formateadas
        if f.get('estado_tiempo') == 'vencida' and f['resultados_pendientes'] > 0
    ]

    # Mensaje ejecutivo sintético
    if not total_raps:
        mensaje_veredicto = 'Sin resultados registrados para calcular fases.'
    elif estado == 'completado':
        mensaje_veredicto = 'Todos los resultados de aprendizaje han sido aprobados.'
    elif raps_vencidos_pendientes > 0 and desfase > 0:
        nombres_vencidas = ', '.join(f"{fv['nombre'].title()} ({fv['pendientes']})" for fv in fases_vencidas_info)
        mensaje_veredicto = (
            f"Fase esperada por tiempo: {fase_esperada.get('nombre', '').title()} · "
            f"Fase según RAPs: {fase_real.get('nombre', '').title()} (Retraso de {desfase} "
            f"{'fase' if desfase == 1 else 'fases'}, con {raps_vencidos_pendientes} RAPs pendientes en fases ya culminadas: {nombres_vencidas})."
        )
    elif desfase > 0:
        mensaje_veredicto = (
            f"Fase esperada por tiempo: {fase_esperada.get('nombre', '').title()} · "
            f"Fase según RAPs: {fase_real.get('nombre', '').title()} (Retraso de {desfase} "
            f"{'fase' if desfase == 1 else 'fases'})."
        )
    elif desfase < 0:
        mensaje_veredicto = (
            f"Fase según RAPs: {fase_real.get('nombre', '').title()} (Adelantada respecto a "
            f"{fase_esperada.get('nombre', '').title()})."
        )
    else:
        nombre_fase = fase_esperada.get('nombre', '').title() if fase_esperada else 'En curso'
        mensaje_veredicto = f"Al día: Proyecto sincronizado en fase de {nombre_fase}."

    raps_vencidos_detalle = []
    items_linea = linea.get('resultados', []) if isinstance(linea, dict) else (linea if isinstance(linea, list) else [])
    for it in items_linea:
        if not isinstance(it, dict):
            continue
        fin_val = it.get('fecha_plan_fin')
        if not fin_val:
            continue
        fin_dt = fin_val if isinstance(fin_val, date) else None
        if not fin_dt:
            from app.services.seguimiento_fases import _fecha
            fin_dt = _fecha(fin_val)
        if fin_dt and fin_dt <= hoy:
            pct_av = float(it.get('porcentaje_avance') or 0.0)
            if pct_av < 80.0:
                ini_val = it.get('fecha_plan_inicio')
                ini_dt = ini_val if isinstance(ini_val, date) else None
                if not ini_dt and ini_val:
                    from app.services.seguimiento_fases import _fecha
                    ini_dt = _fecha(ini_val)
                dias_atraso = (hoy - fin_dt).days if fin_dt else 0
                comp_nom = (it.get('competencia') or '').strip()
                comp_tipo = it.get('competencia_tipo')
                if not comp_tipo:
                    from app.services.importacion_ficha import clasificar_competencia
                    comp_tipo = clasificar_competencia(comp_nom)
                raps_vencidos_detalle.append({
                    'fase': (it.get('fase') or '').strip().upper(),
                    'competencia': comp_nom,
                    'competencia_tipo': comp_tipo or 'tecnica',
                    'rap': (it.get('rap') or '').strip(),
                    'rap_codigo': (it.get('rap_codigo') or '').strip(),
                    'horas': float(it.get('horas_total') or 0.0),
                    'fecha_plan_inicio': ini_dt.strftime('%d/%m/%Y') if ini_dt else '',
                    'fecha_plan_fin': fin_dt.strftime('%d/%m/%Y') if fin_dt else '',
                    'fecha_plan_fin_iso': fin_dt.isoformat() if fin_dt else '',
                    'dias_atraso': dias_atraso,
                    'porcentaje_avance': round(pct_av, 1),
                    'aprendices_aprobados': int(it.get('aprendices_aprobados') or 0),
                    'aprendices_total': int(it.get('aprendices_total') or 0),
                    'instructores': it.get('instructores') or [],
                })
    raps_vencidos_detalle.sort(key=lambda x: (x['fecha_plan_fin_iso'], x['fase']))

    return {
        'disponible': True,
        'fuente': 'planeacion_gfpi',
        'fuente_etiqueta': 'Planeación GFPI-F-134',
        'planeacion_sincronizada': True,
        'estado': estado,
        'desfase_fases': desfase,
        'fase_esperada': {
            'orden': fase_esperada.get('orden', 0) if fase_esperada else 0,
            'nombre': fase_esperada.get('nombre') if fase_esperada else 'Sin definir',
            'icono': fase_esperada.get('icono', '⏱️') if fase_esperada else '⏱️',
            'porcentaje_tiempo': fase_esperada.get('porcentaje_tiempo', 0) if fase_esperada else 0,
        },
        'fase_real': {
            'orden': fase_real.get('orden', 0) if fase_real else 0,
            'nombre': fase_real.get('nombre') if fase_real else 'Sin definir',
            'icono': fase_real.get('icono', '📚') if fase_real else '📚',
            'porcentaje_aprobados': fase_real.get('porcentaje_aprobados', 0) if fase_real else 0,
            'resultados_aprobados': fase_real.get('resultados_aprobados', 0) if fase_real else 0,
            'resultados_total': fase_real.get('resultados_total', 0) if fase_real else 0,
        },
        'fases': fases_formateadas,
        'resumen_raps': {
            'total': total_raps,
            'aprobados': aprobados_raps,
            'evaluados': evaluados_raps,
            'pendientes': pendientes_raps,
            'esperados': esperados_raps,
            'porcentaje_aprobados': pct_aprobados,
            'porcentaje_esperados': pct_esperados,
            'raps_vencidos_pendientes': raps_vencidos_pendientes,
            'fases_vencidas': fases_vencidas_info,
            'raps_vencidos_detalle': raps_vencidos_detalle,
        },
        'mensaje_veredicto': mensaje_veredicto,
    }


def _calcular_estimado_por_juicios(
    ficha: Ficha,
    cronograma: Dict[str, Any],
    hoy: date,
) -> Dict[str, Any]:
    """Calcula la estimación elegante de fases cuando solo se tiene el Reporte de Juicios."""
    pct_tiempo = float(cronograma.get('porcentaje_lectiva') or cronograma.get('porcentaje') or 0.0)
    configurado = bool(cronograma.get('configurado'))

    # Métricas de juicios en BD para los aprendices en formación
    juicios_query = (
        db.session.query(
            JuicioEvaluativo.juicio,
            JuicioEvaluativo.resultado_aprendizaje,
        )
        .join(Aprendiz, JuicioEvaluativo.aprendiz_id == Aprendiz.id)
        .filter(
            JuicioEvaluativo.ficha_id == ficha.id,
            Aprendiz.estado.in_(ESTADOS_EN_FORMACION),
        )
        .all()
    )

    raps_unicos = set()
    raps_aprobados_set = set()
    total_juicios = len(juicios_query)
    total_aprobados = 0
    total_evaluados = 0

    for juicio_val, rap_val in juicios_query:
        rap_limpio = (rap_val or '').strip()
        if rap_limpio:
            raps_unicos.add(rap_limpio)
        j_upper = (juicio_val or '').upper()
        es_aprobado = bool(juicio_val and 'APROBADO' in j_upper and 'AUN NO' not in j_upper)
        es_evaluado = bool(juicio_val and ('APROBADO' in j_upper or 'NO APROBADO' in j_upper or j_upper in ('A', 'NA')))
        if es_aprobado:
            total_aprobados += 1
            if rap_limpio:
                raps_aprobados_set.add(rap_limpio)
        if es_evaluado:
            total_evaluados += 1

    total_raps = len(raps_unicos) or (round(total_juicios / 25) if total_juicios else 0)
    pct_aprobados = round((total_aprobados / total_juicios * 100), 1) if total_juicios else 0.0
    pct_evaluados = round((total_evaluados / total_juicios * 100), 1) if total_juicios else 0.0

    # Ubicar fase esperada por tiempo
    fase_esperada_nombre = 'ANÁLISIS'
    fase_esperada_icono = '🔍'
    idx_esperada = 0
    if configurado and pct_tiempo > 0:
        for idx, (fase_nom, icono, min_pct, max_pct) in enumerate(UMBRALES_ESTANDAR_FASES):
            if min_pct <= pct_tiempo <= max_pct or (idx == len(UMBRALES_ESTANDAR_FASES) - 1 and pct_tiempo >= min_pct):
                fase_esperada_nombre = fase_nom
                fase_esperada_icono = icono
                idx_esperada = idx
                break

    # Ubicar fase real estimada por RAPs aprobados
    fase_real_nombre = 'ANÁLISIS'
    fase_real_icono = '🔍'
    idx_real = 0
    if pct_aprobados > 0:
        for idx, (fase_nom, icono, min_pct, max_pct) in enumerate(UMBRALES_ESTANDAR_FASES):
            if min_pct <= pct_aprobados <= max_pct or (idx == len(UMBRALES_ESTANDAR_FASES) - 1 and pct_aprobados >= min_pct):
                fase_real_nombre = fase_nom
                fase_real_icono = icono
                idx_real = idx
                break

    desfase = (idx_esperada - idx_real) if configurado else 0
    if not configurado:
        estado = 'sin_datos'
        mensaje_veredicto = 'Configura las fechas de la ficha para calcular el avance por fases.'
    elif pct_aprobados >= 100:
        estado = 'completado'
        mensaje_veredicto = '100% de los resultados aprobados.'
    elif desfase > 0:
        estado = 'atrasado'
        mensaje_veredicto = (
            f"Fase esperada por tiempo: {fase_esperada_nombre.title()} · "
            f"Fase según RAPs: {fase_real_nombre.title()} (Retraso de {desfase} "
            f"{'fase' if desfase == 1 else 'fases'})."
        )
    elif desfase < 0:
        estado = 'adelantado'
        mensaje_veredicto = (
            f"Fase según RAPs: {fase_real_nombre.title()} (Adelantada respecto al cronograma)."
        )
    else:
        estado = 'al_dia'
        mensaje_veredicto = f"Al día: Proyecto sincronizado en fase de {fase_esperada_nombre.title()}."

    # Fases estimadas
    fases_formateadas = []
    acum_totales = 0
    for idx, (fase_nom, icono, min_pct, max_pct) in enumerate(UMBRALES_ESTANDAR_FASES):
        rango = max_pct - min_pct
        if pct_tiempo >= max_pct:
            t_pct = 100
            st_tiempo = 'cumplida'
        elif pct_tiempo >= min_pct:
            t_pct = round((pct_tiempo - min_pct) / rango * 100)
            st_tiempo = 'en_curso'
        else:
            t_pct = 0
            st_tiempo = 'futura'

        if pct_aprobados >= max_pct:
            rap_pct = 100
            rap_ratio = 1.0
        elif pct_aprobados >= min_pct:
            rap_ratio = (pct_aprobados - min_pct) / rango
            rap_pct = round(rap_ratio * 100)
        else:
            rap_pct = 0
            rap_ratio = 0.0

        if idx == len(UMBRALES_ESTANDAR_FASES) - 1:
            raps_fase_total = max(total_raps - acum_totales, 0)
        else:
            raps_fase_total = max(round(total_raps * (rango / 100)), 1) if total_raps else 0
            acum_totales += raps_fase_total

        raps_fase_aprobados = min(round(raps_fase_total * rap_ratio), raps_fase_total)
        raps_fase_esperados = min(round(raps_fase_total * (t_pct / 100)), raps_fase_total)
        raps_fase_pendientes = max(raps_fase_total - raps_fase_aprobados, 0)
        brecha_fase = raps_fase_aprobados - raps_fase_esperados

        fases_formateadas.append({
            'orden': idx,
            'nombre': fase_nom,
            'icono': icono,
            'inicio': None,
            'fin': None,
            'porcentaje_tiempo': t_pct,
            'porcentaje_aprobados': rap_pct,
            'porcentaje_evaluados': rap_pct,
            'resultados_esperados': raps_fase_esperados,
            'resultados_aprobados': raps_fase_aprobados,
            'resultados_evaluados': raps_fase_aprobados,
            'resultados_pendientes': raps_fase_pendientes,
            'resultados_total': raps_fase_total,
            'brecha_resultados': brecha_fase,
            'estado_tiempo': st_tiempo,
            'estado_ritmo': 'al_dia' if rap_pct >= t_pct else 'atrasado',
            'horas': 0,
            'competencias_total': 0,
            'competencias_pendientes': [],
        })

    aprobados_raps = sum(f['resultados_aprobados'] for f in fases_formateadas) if total_raps else 0
    evaluados_raps = max(round(total_raps * (pct_evaluados / 100)), aprobados_raps) if total_raps else 0
    esperados_totales = sum(f['resultados_esperados'] for f in fases_formateadas) if total_raps else 0
    raps_vencidos = sum(
        f['resultados_pendientes']
        for f in fases_formateadas
        if f['estado_tiempo'] == 'cumplida'
    )
    fases_vencidas_info = [
        {
            'nombre': f['nombre'],
            'pendientes': f['resultados_pendientes'],
            'total': f['resultados_total'],
            'aprobados': f['resultados_aprobados'],
        }
        for f in fases_formateadas
        if f['estado_tiempo'] == 'cumplida' and f['resultados_pendientes'] > 0
    ]

    return {
        'disponible': True,
        'fuente': 'estimado_reporte',
        'fuente_etiqueta': 'Estimación estándar por juicios',
        'planeacion_sincronizada': False,
        'estado': estado,
        'desfase_fases': desfase,
        'fase_esperada': {
            'orden': idx_esperada,
            'nombre': fase_esperada_nombre if configurado else 'Fechas pendientes',
            'icono': fase_esperada_icono if configurado else '📅',
            'porcentaje_tiempo': round(pct_tiempo),
        },
        'fase_real': {
            'orden': idx_real,
            'nombre': fase_real_nombre,
            'icono': fase_real_icono,
            'porcentaje_aprobados': round(pct_aprobados),
            'resultados_aprobados': aprobados_raps,
            'resultados_total': total_raps,
        },
        'fases': fases_formateadas,
        'resumen_raps': {
            'total': total_raps,
            'aprobados': aprobados_raps,
            'evaluados': evaluados_raps,
            'pendientes': max(total_raps - aprobados_raps, 0),
            'esperados': esperados_totales,
            'porcentaje_aprobados': round(pct_aprobados, 1),
            'porcentaje_esperados': round(pct_tiempo, 1) if configurado else 0.0,
            'raps_vencidos_pendientes': raps_vencidos,
            'fases_vencidas': fases_vencidas_info,
            'raps_vencidos_detalle': [],
        },
        'mensaje_veredicto': mensaje_veredicto,
    }


def obtener_seguimiento_fases_dashboard(
    ficha: Ficha,
    cronograma: Optional[Dict[str, Any]] = None,
    hoy: Optional[date] = None,
    cache_programa: Optional[Dict[str, Optional[ArchivoFichaVersion]]] = None,
    version_plan: Any = _VERSION_NO_PROVISTA,
    version_reporte: Any = _VERSION_NO_PROVISTA,
) -> Dict[str, Any]:
    """Punto de entrada principal para el estado de fases del proyecto en la tarjeta."""
    hoy = hoy or fecha_corte_bogota()
    if cronograma is None:
        cronograma = obtener_cronograma(ficha, hoy)

    if version_plan is _VERSION_NO_PROVISTA:
        version_plan = _buscar_version_planeacion(ficha, cache_programa=cache_programa)
    elif version_plan is None:
        version_plan = _buscar_planeacion_compartida(ficha, cache_programa=cache_programa)

    if version_reporte is _VERSION_NO_PROVISTA:
        version_reporte = ultima_version(
            ficha.id, TIPO_REPORTE_JUICIOS, solo_procesadas=True, recuperar_reporte=False,
        )

    def _construir():
        if version_plan:
            contenido = _obtener_planeacion_parseada(version_plan)
            if contenido and contenido.get('unidades'):
                try:
                    return _calcular_con_planeacion(
                        ficha, version_plan, contenido, hoy, version_reporte=version_reporte
                    )
                except Exception:
                    current_app.logger.exception(
                        'Error calculando fases con planeación para ficha %s, usando fallback de juicios',
                        ficha.id,
                    )
        return _calcular_estimado_por_juicios(ficha, cronograma, hoy)

    return obtener_resultado_persistido(
        ficha, 'fases', hoy, [version_plan, version_reporte], _construir,
    )
