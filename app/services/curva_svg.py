"""Generador de coordenadas vectoriales SVG y métricas de renderizado para curvas formativas."""

from __future__ import annotations

from typing import Any, Dict, List


def construir_curva_svg_aprendiz(
    puntos: List[Dict[str, Any]],
    meta_pct: float = 70.0,
    ancho: float = 600.0,
    alto: float = 210.0,
) -> Dict[str, Any]:
    """Genera coordenadas vectoriales SVG y métricas de renderizado para la curva."""
    if not puntos:
        return {
            'linea_puntaje': '',
            'poligono_area': '',
            'y_meta': 70.0,
            'viewbox': f'0 0 {int(ancho)} {int(alto)}',
            'marcas_y': [],
            'marcas_x': [],
            'x_start': 50.0,
            'x_end': ancho - 35.0,
            'y_zero': alto - 35.0,
            'y_full': 25.0,
        }

    x_start = 50.0
    x_end = ancho - 35.0
    y_zero = alto - 35.0   # 175px para 0%
    y_full = 25.0          # 25px para 100%
    y_height = y_zero - y_full  # 150px de recorrido útil

    num_puntos = len(puntos)
    paso = (x_end - x_start) / max(num_puntos - 1, 1)

    scores = [min(max(float(pt.get('puntaje', 0.0)), 0.0), 100.0) for pt in puntos]
    max_score = max(scores) if scores else 0.0
    min_score = min(scores) if scores else 0.0
    idx_max = scores.index(max_score) if scores else -1
    idx_ultimo = num_puntos - 1

    for i, pt in enumerate(puntos):
        x = round(x_start + i * paso, 1)
        score = scores[i]
        y = round(y_zero - (score / 100.0) * y_height, 1)
        pt['x'] = x
        pt['y'] = y
        pt['es_ultimo'] = (i == idx_ultimo)
        pt['es_maximo'] = (i == idx_max and max_score > 0)
        pt['es_minimo'] = (score == min_score and min_score < max_score)
        # Mostrar etiqueta fija: si hay pocos puntos (<=6) se muestran todas;
        # si hay muchos puntos (>6), solo se muestra en el pico máximo y en el último corte
        pt['mostrar_etiqueta_puntaje'] = True if num_puntos <= 6 else (i == idx_ultimo or i == idx_max)

    linea_puntaje = ' '.join(f"{p['x']},{p['y']}" for p in puntos)
    poligono_area = (
        f"{puntos[0]['x']},{round(y_zero, 1)} "
        + linea_puntaje
        + f" {puntos[-1]['x']},{round(y_zero, 1)}"
    )
    y_meta = round(y_zero - (meta_pct / 100.0) * y_height, 1)

    marcas_y = [
        {'valor': 100, 'y': round(y_full, 1)},
        {'valor': 75, 'y': round(y_zero - 0.75 * y_height, 1)},
        {'valor': 50, 'y': round(y_zero - 0.50 * y_height, 1)},
        {'valor': 25, 'y': round(y_zero - 0.25 * y_height, 1)},
        {'valor': 0, 'y': round(y_zero, 1)},
    ]

    # Marcas para el eje X: se seleccionan entre 4 y 6 hitos temporales para evitar solapamientos
    marcas_x = []
    if num_puntos == 1:
        marcas_x.append({'fecha': puntos[0].get('fecha_str', ''), 'x': puntos[0]['x']})
    elif num_puntos <= 6:
        for pt in puntos:
            marcas_x.append({'fecha': pt.get('fecha_str', ''), 'x': pt['x']})
    else:
        indices_x = sorted(list({
            0,
            int(round((num_puntos - 1) * 0.25)),
            int(round((num_puntos - 1) * 0.5)),
            int(round((num_puntos - 1) * 0.75)),
            num_puntos - 1,
        }))
        for idx in indices_x:
            marcas_x.append({
                'fecha': puntos[idx].get('fecha_str', ''),
                'x': puntos[idx]['x'],
            })

    return {
        'linea_puntaje': linea_puntaje,
        'poligono_area': poligono_area,
        'y_meta': y_meta,
        'meta_pct': meta_pct,
        'viewbox': f'0 0 {int(ancho)} {int(alto)}',
        'marcas_y': marcas_y,
        'marcas_x': marcas_x,
        'x_start': x_start,
        'x_end': x_end,
        'y_zero': y_zero,
        'y_full': y_full,
    }
