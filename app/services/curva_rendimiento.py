"""Cálculo y coordenadas de la curva de rendimiento histórico para aprendices.

Genera la trayectoria temporal del puntaje académico y de participación,
calcula indicadores de tendencia (ascendente, estable, descendente),
distancia contra la meta mínima aprobatoria (70%) y coordenadas vectoriales
SVG para su visualización interactiva y accesible en el panel del aprendiz.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from app.models.ranking import PuntajeHistorico
from app.services.curva_diagnostico import (
    generar_diagnostico_curva,
    obtener_ruta_recuperacion_formativa,
)


from app.services.curva_svg import construir_curva_svg_aprendiz


def obtener_curva_rendimiento_aprendiz(
    ficha_id: int,
    aprendiz_id: int,
    fila_propia: Optional[Dict[str, Any]] = None,
    hoy: Optional[date] = None,
) -> Dict[str, Any]:
    """Obtiene y procesa la curva de rendimiento histórico del aprendiz."""
    hoy = hoy or date.today()

    registros = (
        PuntajeHistorico.query
        .filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz_id)
        .order_by(PuntajeHistorico.fecha_corte.asc())
        .all()
    )

    puntos_raw: List[Dict[str, Any]] = []
    fechas_vistas = set()

    for r in registros:
        f_corte = r.fecha_corte.date() if hasattr(r.fecha_corte, 'date') else r.fecha_corte
        f_clave = f_corte.strftime('%Y-%m-%d')
        if f_clave in fechas_vistas:
            puntos_raw = [p for p in puntos_raw if p['fecha_clave'] != f_clave]
        fechas_vistas.add(f_clave)
        puntos_raw.append({
            'fecha': f_corte,
            'fecha_clave': f_clave,
            'fecha_str': f_corte.strftime('%d/%m/%Y'),
            'puntaje': round(float(r.puntaje_total or 0.0), 1),
            'asistencia': round(float(r.puntaje_asistencia or 0.0), 1),
            'evidencias': round(float(r.puntaje_evidencias or 0.0), 1),
            'juicios': round(float(r.puntaje_juicios or 0.0), 1),
            'posicion': int(r.posicion or 0),
        })

    # Si se suministra fila_propia del ranking actual, asegurar que esté reflejado a hoy
    if fila_propia:
        pt_actual = round(float(fila_propia.get('puntaje_total') or 0.0), 1)
        pt_asis = round(float(fila_propia.get('puntaje_asistencia') or 0.0), 1)
        pt_evid = round(float(fila_propia.get('puntaje_evidencias') or 0.0), 1)
        pt_juic = round(float(fila_propia.get('puntaje_juicios') or 0.0), 1)
        pos_actual = int(fila_propia.get('posicion') or 1)

        f_hoy_clave = hoy.strftime('%Y-%m-%d')
        if not puntos_raw:
            puntos_raw.append({
                'fecha': hoy,
                'fecha_clave': f_hoy_clave,
                'fecha_str': hoy.strftime('%d/%m/%Y'),
                'puntaje': pt_actual,
                'asistencia': pt_asis,
                'evidencias': pt_evid,
                'juicios': pt_juic,
                'posicion': pos_actual,
            })
        elif puntos_raw[-1]['fecha'] < hoy:
            puntos_raw.append({
                'fecha': hoy,
                'fecha_clave': f_hoy_clave,
                'fecha_str': hoy.strftime('%d/%m/%Y'),
                'puntaje': pt_actual,
                'asistencia': pt_asis,
                'evidencias': pt_evid,
                'juicios': pt_juic,
                'posicion': pos_actual,
            })

    if not puntos_raw:
        return {
            'tiene_datos': False,
            'puntos': [],
            'puntaje_actual': 0.0,
            'posicion_actual': 0,
            'tendencia': 'estable',
            'tendencia_icono': '➡️',
            'tendencia_clase': 'trend-steady',
            'diferencia_ultimo': 0.0,
            'mejor_puntaje': 0.0,
            'peor_puntaje': 0.0,
            'supera_meta': False,
            'distancia_meta': -70.0,
            'nivel_desempeno': 'Sin datos',
            'badge_class': 'badge-secondary',
            'diagnostico': 'Sin registros históricos disponibles para esta ficha.',
            'ruta_recuperacion': [],
            'pilares': {'evidencias': 0.0, 'asistencia': 0.0, 'juicios': 0.0},
            'svg': construir_curva_svg_aprendiz([]),
        }

    # Si hay un solo corte, sintetizamos un hito base anterior para trazar la línea
    if len(puntos_raw) == 1:
        p_unico = puntos_raw[0]
        f_base = p_unico['fecha'] - timedelta(days=7)
        puntaje_base = max(round(p_unico['puntaje'] * 0.9, 1), 0.0)
        puntos_raw.insert(0, {
            'fecha': f_base,
            'fecha_clave': f_base.strftime('%Y-%m-%d'),
            'fecha_str': f_base.strftime('%d/%m/%Y'),
            'puntaje': puntaje_base,
            'asistencia': p_unico['asistencia'],
            'evidencias': max(round(p_unico['evidencias'] * 0.85, 1), 0.0),
            'juicios': p_unico['juicios'],
            'posicion': p_unico['posicion'],
            'es_base_sintetica': True,
        })

    # Cálculo de métricas y tendencia
    svg_data = construir_curva_svg_aprendiz(puntos_raw, meta_pct=70.0)
    ultimo_pt = puntos_raw[-1]
    penultimo_pt = puntos_raw[-2] if len(puntos_raw) >= 2 else ultimo_pt

    dif = round(ultimo_pt['puntaje'] - penultimo_pt['puntaje'], 1)
    if dif > 1.0:
        tendencia = 'ascendente'
        tendencia_icono = '↗️'
        tendencia_clase = 'trend-up'
    elif dif < -1.0:
        tendencia = 'descendente'
        tendencia_icono = '↘️'
        tendencia_clase = 'trend-down'
    else:
        tendencia = 'estable'
        tendencia_icono = '➡️'
        tendencia_clase = 'trend-steady'

    pt_actual = ultimo_pt['puntaje']
    distancia_meta = round(pt_actual - 70.0, 1)
    supera_meta = pt_actual >= 70.0
    mejor_pt = max(p['puntaje'] for p in puntos_raw)
    peor_pt = min(p['puntaje'] for p in puntos_raw)

    if pt_actual >= 85.0:
        nivel_desempeno = 'Excelente'
        badge_class = 'badge-success'
    elif pt_actual >= 70.0:
        nivel_desempeno = 'Bueno'
        badge_class = 'badge-info'
    elif pt_actual >= 50.0:
        nivel_desempeno = 'En Riesgo'
        badge_class = 'badge-warning'
    else:
        nivel_desempeno = 'Crítico'
        badge_class = 'badge-danger'

    # Diagnóstico pedagógico empático en español de Colombia
    diagnostico = generar_diagnostico_curva(
        supera_meta=supera_meta,
        pt_actual=pt_actual,
        distancia_meta=distancia_meta,
        dif=dif,
        mejor_pt=mejor_pt,
        tendencia=tendencia,
    )
    ruta_recuperacion = obtener_ruta_recuperacion_formativa()

    pilares = {
        'evidencias': ultimo_pt.get('evidencias', 0.0),
        'asistencia': ultimo_pt.get('asistencia', 0.0),
        'juicios': ultimo_pt.get('juicios', 0.0),
    }

    return {
        'tiene_datos': True,
        'puntos': puntos_raw,
        'puntaje_actual': pt_actual,
        'posicion_actual': ultimo_pt['posicion'],
        'tendencia': tendencia,
        'tendencia_icono': tendencia_icono,
        'tendencia_clase': tendencia_clase,
        'diferencia_ultimo': dif,
        'mejor_puntaje': mejor_pt,
        'peor_puntaje': peor_pt,
        'supera_meta': supera_meta,
        'distancia_meta': distancia_meta,
        'nivel_desempeno': nivel_desempeno,
        'badge_class': badge_class,
        'diagnostico': diagnostico,
        'ruta_recuperacion': ruta_recuperacion,
        'pilares': pilares,
        'svg': svg_data,
        'ultimo_punto': ultimo_pt,
    }
