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
from pathlib import Path
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
from app.services.seguimiento_fases import FASES_PROYECTO, construir_seguimiento_fases
from app.services.versiones_archivos import ultima_version

# Caché en memoria para evitar re-parsear archivos Excel de planeación en cada petición HTTP
_CACHE_PLANEACION_PARSED: Dict[tuple, Dict[str, Any]] = {}

# Distribución estándar de fases por porcentaje de etapa lectiva en proyectos SENA
# Análisis (25%), Planeación (25%), Ejecución (35%), Evaluación (15%)
UMBRALES_ESTANDAR_FASES = [
    ('ANÁLISIS', '🔍', 0.0, 25.0),
    ('PLANEACIÓN', '📐', 25.0, 50.0),
    ('EJECUCIÓN', '⚙️', 50.0, 85.0),
    ('EVALUACIÓN', '🎯', 85.0, 100.0),
]


def _buscar_version_planeacion(ficha: Ficha) -> Optional[ArchivoFichaVersion]:
    """Busca la planeación procesada de la ficha o de otra ficha del mismo programa."""
    # 1. Planeación directa de la ficha
    version = ultima_version(ficha.id, TIPO_PLANEACION, solo_procesadas=True)
    if version:
        return version

    # 2. Fallback: buscar planeación válida de otra ficha con el mismo código de programa
    if ficha.codigo_programa:
        otras_fichas = (
            db.session.query(Ficha.id)
            .filter(Ficha.codigo_programa == ficha.codigo_programa, Ficha.id != ficha.id)
            .all()
        )
        for (otra_id,) in otras_fichas:
            version_compartida = ultima_version(otra_id, TIPO_PLANEACION, solo_procesadas=True)
            if version_compartida:
                return version_compartida

    return None


def _obtener_planeacion_parseada(version: ArchivoFichaVersion) -> Optional[Dict[str, Any]]:
    """Carga y parsea la planeación pedagógica con memoización en memoria."""
    clave_cache = (version.id, version.tamano_bytes, version.hash_sha256)
    if clave_cache in _CACHE_PLANEACION_PARSED:
        return _CACHE_PLANEACION_PARSED[clave_cache]

    try:
        ruta = Path(current_app.config['UPLOAD_FOLDER']) / version.ruta_archivo
        if not ruta.is_file():
            return None
        contenido = parsear_planeacion(ruta)
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
) -> Dict[str, Any]:
    """Calcula el seguimiento exacto de fases cruzando GFPI-F-134 con los juicios."""
    version_reporte = ultima_version(ficha.id, TIPO_REPORTE_JUICIOS, solo_procesadas=True)
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

    fases_formateadas = []
    for fase in seguimiento.get('fases', []):
        fases_formateadas.append({
            'orden': fase.get('orden', 0),
            'nombre': fase.get('nombre'),
            'icono': fase.get('icono', '📌'),
            'porcentaje_tiempo': fase.get('porcentaje_tiempo', 0),
            'porcentaje_aprobados': fase.get('porcentaje_aprobados', 0),
            'porcentaje_evaluados': fase.get('porcentaje_evaluados', 0),
            'resultados_aprobados': fase.get('resultados_aprobados', 0),
            'resultados_total': fase.get('resultados_total', 0),
            'estado_tiempo': fase.get('estado_tiempo', 'pendiente'),
            'estado_ritmo': fase.get('estado_ritmo', 'al_dia'),
            'horas': fase.get('horas', 0),
        })

    fase_esperada = seguimiento.get('fase_esperada')
    fase_real = seguimiento.get('fase_real')
    estado = seguimiento.get('estado', 'al_dia')

    desfase = 0
    if fase_esperada and fase_real:
        desfase = fase_esperada.get('orden', 0) - fase_real.get('orden', 0)

    # Mensaje ejecutivo sintético
    if not seguimiento.get('resultados', {}).get('total'):
        mensaje_veredicto = 'Sin resultados registrados para calcular fases.'
    elif estado == 'completado':
        mensaje_veredicto = 'Todos los resultados de aprendizaje han sido aprobados.'
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

    res_data = seguimiento.get('resultados', {})
    total_raps = res_data.get('total', 0)
    aprobados_raps = res_data.get('aprobados', 0)
    pct_aprobados = res_data.get('porcentaje_aprobados', 0)

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
            'evaluados': res_data.get('evaluados', 0),
            'pendientes': res_data.get('pendientes', 0),
            'porcentaje_aprobados': pct_aprobados,
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

    for juicio_val, rap_val in juicios_query:
        rap_limpio = (rap_val or '').strip()
        if rap_limpio:
            raps_unicos.add(rap_limpio)
        es_aprobado = bool(juicio_val and 'APROBADO' in juicio_val.upper() and 'AUN NO' not in juicio_val.upper())
        if es_aprobado:
            total_aprobados += 1
            if rap_limpio:
                raps_aprobados_set.add(rap_limpio)

    total_raps = len(raps_unicos) or (round(total_juicios / 25) if total_juicios else 0)
    pct_aprobados = round((total_aprobados / total_juicios * 100), 1) if total_juicios else 0.0
    aprobados_raps = round(total_raps * (pct_aprobados / 100)) if total_raps else 0

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
        elif pct_aprobados >= min_pct:
            rap_pct = round((pct_aprobados - min_pct) / rango * 100)
        else:
            rap_pct = 0

        raps_fase_total = max(round(total_raps * (rango / 100)), 1) if total_raps else 0
        raps_fase_aprobados = min(round(raps_fase_total * (rap_pct / 100)), raps_fase_total)

        fases_formateadas.append({
            'orden': idx,
            'nombre': fase_nom,
            'icono': icono,
            'porcentaje_tiempo': t_pct,
            'porcentaje_aprobados': rap_pct,
            'porcentaje_evaluados': rap_pct,
            'resultados_aprobados': raps_fase_aprobados,
            'resultados_total': raps_fase_total,
            'estado_tiempo': st_tiempo,
            'estado_ritmo': 'al_dia' if rap_pct >= t_pct else 'atrasado',
            'horas': 0,
        })

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
            'evaluados': total_aprobados,
            'pendientes': max(total_raps - aprobados_raps, 0),
            'porcentaje_aprobados': round(pct_aprobados, 1),
        },
        'mensaje_veredicto': mensaje_veredicto,
    }


def obtener_seguimiento_fases_dashboard(
    ficha: Ficha,
    cronograma: Optional[Dict[str, Any]] = None,
    hoy: Optional[date] = None,
) -> Dict[str, Any]:
    """Punto de entrada principal para el estado de fases del proyecto en la tarjeta."""
    hoy = hoy or date.today()
    if cronograma is None:
        cronograma = obtener_cronograma(ficha, hoy)

    version_plan = _buscar_version_planeacion(ficha)
    if version_plan:
        contenido = _obtener_planeacion_parseada(version_plan)
        if contenido and contenido.get('unidades'):
            try:
                return _calcular_con_planeacion(ficha, version_plan, contenido, hoy)
            except Exception:
                current_app.logger.exception(
                    'Error calculando fases con planeación para ficha %s, usando fallback de juicios',
                    ficha.id,
                )

    # Fallback seguro: degradación elegante con juicios y cronograma
    return _calcular_estimado_por_juicios(ficha, cronograma, hoy)
