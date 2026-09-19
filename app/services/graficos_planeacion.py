"""Datos geométricos de los gráficos de la vista de planeación.

Traduce el avance de la ficha a las coordenadas que la plantilla dibuja:
la Curva S con abanico probabilístico, el radar de cobertura por competencia,
la matriz de carga docente y el progreso por fases.
"""

from __future__ import annotations

import math
import unicodedata
from datetime import date

from app.services.planeacion import componente_instructor, normalizar_instructor


HORAS_LECTIVAS_POR_DEFECTO = 3120.0
MAXIMO_EJES_RADAR = 10


_MESES_ESP = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


def _formato_mes_anio(f):
    if not f:
        return ''
    return f"{_MESES_ESP[f.month]} {str(f.year)[2:]}"


def _formato_rango(f_ini, f_fin):
    if not f_ini or not f_fin:
        return ''
    if f_ini.year == f_fin.year:
        if f_ini.month == f_fin.month:
            return f"{_MESES_ESP[f_ini.month]} {str(f_ini.year)[2:]}"
        return f"{_MESES_ESP[f_ini.month]}–{_MESES_ESP[f_fin.month]} {str(f_ini.year)[2:]}"
    return f"{_MESES_ESP[f_ini.month]} {str(f_ini.year)[2:]}–{_MESES_ESP[f_fin.month]} {str(f_fin.year)[2:]}"


def _x_de_fecha(f, bloques, x_start, paso, x_end):
    """Mapea con precisión matemática cualquier fecha al eje X continuo de la Curva S."""
    if not f or not bloques:
        return x_start
    if f <= bloques[0]['inicio']:
        return x_start

    for k, b in enumerate(bloques):
        if b['inicio'] <= f <= b['fin']:
            dias = max(b.get('dias', (b['fin'] - b['inicio']).days + 1), 1)
            frac = min(max((f - b['inicio']).days / dias, 0.0), 1.0)
            if k == 0:
                return round(x_start, 1)
            else:
                x_prev = x_start + (k - 1) * paso
                x_curr = x_start + k * paso
                return round(x_prev + frac * (x_curr - x_prev), 1)

    ultimo = bloques[-1]
    if f > ultimo['fin']:
        dias_extra = (f - ultimo['fin']).days
        return round(min(x_end + (dias_extra / 90.0) * paso, x_end + 45.0), 1)
    return x_end


def construir_curva_svg(proyeccion, calendario, hoy=None):
    """Calcula coordenadas SVG para la Curva S, abanico P10/P50/P90 y puntos interactivos."""
    curva = (proyeccion or {}).get('curva') or []
    if not curva or not calendario or not calendario.get('configurado'):
        return None

    hoy = hoy or date.today()
    x_start = 65.0
    x_end = 760.0
    y_zero = 210.0
    y_full = 30.0
    y_height = y_zero - y_full  # 180px para 0% - 100%

    num_puntos = len(curva)
    paso = (x_end - x_start) / max(num_puntos - 1, 1)

    bloques = calendario.get('bloques') or []
    bloques_por_num = {b['numero']: b for b in bloques}

    puntos_plan = []
    puntos_real = []
    puntos_datos = []
    ultimo_real_x = x_start
    ultimo_real_y = y_zero
    ultimo_real_pct = 0
    ultimo_real_idx = 0

    prev_pv = 0.0
    prev_ev = 0.0

    for i, b in enumerate(curva):
        x = round(x_start + i * paso, 1)
        plan_pct = float(b.get('planeado') or 0)
        y_plan = round(y_zero - (plan_pct / 100.0) * y_height, 1)
        puntos_plan.append(f"{x},{y_plan}")

        real_pct = b.get('real')
        y_real = None
        pv_h = float(b.get('pv_horas') or 0)
        ev_h = float(b.get('ev_horas')) if b.get('ev_horas') is not None else None

        # Incrementos por bloque (velocidad)
        pv_inc = max(pv_h - prev_pv, 0.0)
        prev_pv = pv_h

        ev_inc = None
        if ev_h is not None:
            ev_inc = max(ev_h - prev_ev, 0.0) if prev_ev is not None else ev_h
            prev_ev = ev_h

        if real_pct is not None:
            real_val = float(real_pct)
            y_real = round(y_zero - (real_val / 100.0) * y_height, 1)
            puntos_real.append(f"{x},{y_real}")
            ultimo_real_x = x
            ultimo_real_y = y_real
            ultimo_real_pct = real_val
            ultimo_real_idx = i

        sv_h = round(ev_h - pv_h, 1) if ev_h is not None else None

        # Bloque de calendario asociado
        b_cal = bloques_por_num.get(b.get('numero'), bloques[i] if i < len(bloques) else {})
        f_ini = b_cal.get('inicio')
        f_fin = b_cal.get('fin')
        dias_b = b_cal.get('dias', (f_fin - f_ini).days + 1 if f_ini and f_fin else 0)

        puntos_datos.append({
            'index': i,
            'numero': b.get('numero'),
            'etiqueta': b.get('etiqueta'),
            'nombre': b.get('nombre'),
            'etapa': b.get('etapa'),
            'estado': b.get('estado'),
            'estado_label': 'En curso' if b.get('estado') == 'en_curso' else ('Cumplido' if b.get('estado') == 'cumplido' else 'Futuro'),
            'fecha_inicio': f_ini,
            'fecha_fin': f_fin,
            'fecha_inicio_str': f_ini.strftime('%d/%m/%Y') if f_ini else '',
            'fecha_fin_str': f_fin.strftime('%d/%m/%Y') if f_fin else '',
            'rango_fechas': f"Del {f_ini.strftime('%d/%m/%Y')} al {f_fin.strftime('%d/%m/%Y')}" if f_ini and f_fin else '',
            'rango_corto': _formato_rango(f_ini, f_fin),
            'dias_duracion': dias_b,
            'x': x,
            'y_plan': y_plan,
            'y_real': y_real,
            'planeado_pct': plan_pct,
            'real_pct': real_pct,
            'pv_horas': pv_h,
            'ev_horas': ev_h,
            'pv_inc_horas': round(pv_inc, 1),
            'ev_inc_horas': round(ev_inc, 1) if ev_inc is not None else None,
            'sv_horas': sv_h,
            'es_pasado_o_actual': real_pct is not None,
            'es_actual': b.get('estado') == 'en_curso',
        })

    # Polígono de área real
    poligono_real = ""
    if puntos_real:
        primer_x = puntos_datos[0]['x']
        poligono_real = f"{primer_x},{y_zero} " + " ".join(puntos_real) + f" {ultimo_real_x},{y_zero}"

    # Proyección probabilística (Abanico P10 / P50 / P90)
    prob = proyeccion.get('proyeccion_probabilistica')
    proyeccion_svg = None

    if prob and ultimo_real_pct < 100 and puntos_real:
        x_p10 = _x_de_fecha(prob['p10']['fecha'], bloques, x_start, paso, x_end)
        x_p50 = _x_de_fecha(prob['p50']['fecha'], bloques, x_start, paso, x_end)
        x_p90 = _x_de_fecha(prob['p90']['fecha'], bloques, x_start, paso, x_end)

        # Garantizar orden visual x_p10 <= x_p50 <= x_p90
        x_p10 = max(x_p10, ultimo_real_x + 6.0)
        x_p50 = max(x_p50, x_p10 + 6.0)
        x_p90 = max(x_p90, x_p50 + 6.0)

        # Orden visual: P10 (más rápido) a la izquierda, P90 (más lento) a la derecha
        linea_p10 = f"{ultimo_real_x},{ultimo_real_y} {x_p10},{y_full}"
        linea_p50 = f"{ultimo_real_x},{ultimo_real_y} {x_p50},{y_full}"
        linea_p90 = f"{ultimo_real_x},{ultimo_real_y} {x_p90},{y_full}"

        # Abanico: triángulo desde último dato real hasta puntos P10 y P90 al 100%
        poligono_abanico = f"{ultimo_real_x},{ultimo_real_y} {x_p10},{y_full} {x_p90},{y_full}"

        # Escalonamiento dinámico anti-colisión — labels con separación y no superpuestas
        dist_10_50 = abs(x_p50 - x_p10)
        dist_50_90 = abs(x_p90 - x_p50)

        # Posicionamiento vertical escalonado y más abajo para dar aire al gráfico
        if dist_10_50 < 80 or dist_50_90 < 80:
            y_lbl_p10 = round(y_full + 26.0, 1)
            y_lbl_p50 = round(y_full + 44.0, 1)
            y_lbl_p90 = round(y_full + 62.0, 1)
            anchor_p10 = 'end' if (x_p10 - 60 > x_start) else 'middle'
            anchor_p50 = 'middle'
            anchor_p90 = 'start' if (x_p90 + 60 < x_end) else 'middle'
        else:
            y_lbl_p10 = round(y_full + 26.0, 1)
            y_lbl_p50 = round(y_full + 26.0, 1)
            y_lbl_p90 = round(y_full + 26.0, 1)
            anchor_p10 = 'middle'
            anchor_p50 = 'middle'
            anchor_p90 = 'middle'

        proyeccion_svg = {
            'x_p10': x_p10,
            'x_p50': x_p50,
            'x_p90': x_p90,
            'y_meta': y_full,
            'y_lbl_p10': y_lbl_p10,
            'y_lbl_p50': y_lbl_p50,
            'y_lbl_p90': y_lbl_p90,
            'linea_p10': linea_p10,
            'linea_p50': linea_p50,
            'linea_p90': linea_p90,
            'poligono_abanico': poligono_abanico,
            'fecha_p10': prob['p10']['fecha'],
            'fecha_p50': prob['p50']['fecha'],
            'fecha_p90': prob['p90']['fecha'],
            'fecha_p10_str': prob['p10']['fecha'].strftime('%d/%m/%Y'),
            'fecha_p50_str': prob['p50']['fecha'].strftime('%d/%m/%Y'),
            'fecha_p90_str': prob['p90']['fecha'].strftime('%d/%m/%Y'),
            'fecha_p10_corta': prob['p10']['fecha'].strftime('%d/%m/%y'),
            'fecha_p50_corta': prob['p50']['fecha'].strftime('%d/%m/%y'),
            'fecha_p90_corta': prob['p90']['fecha'].strftime('%d/%m/%y'),
            'meses_p10': prob['p10'].get('meses'),
            'meses_p50': prob['p50'].get('meses'),
            'meses_p90': prob['p90'].get('meses'),
            'dias_vs_fin_p10': prob['p10'].get('dias_vs_fin'),
            'dias_vs_fin_p50': prob['p50'].get('dias_vs_fin'),
            'dias_vs_fin_p90': prob['p90'].get('dias_vs_fin'),
            'label_humano_p10': f"Optimista: {prob['p10']['fecha'].strftime('%d/%m/%y')}",
            'label_humano_p50': f"Probable: {prob['p50']['fecha'].strftime('%d/%m/%y')}",
            'label_humano_p90': f"Conservador: {prob['p90']['fecha'].strftime('%d/%m/%y')}",
            'anchor_p10': anchor_p10,
            'anchor_p90': anchor_p90,
        }

    # Posición precisa de hoy en el gráfico continuo
    x_hoy = _x_de_fecha(hoy, bloques, x_start, paso, x_end)
    hoy_str = hoy.strftime('%d/%m/%Y')
    hoy_corta = f"{hoy.day} {_MESES_ESP[hoy.month]} {hoy.year}"

    # Franja productiva
    bloque_prod = next((b for b in curva if b.get('etapa') == 'productiva'), None)
    rect_prod = None
    if bloque_prod:
        prod_idx = bloque_prod.get('numero', len(curva)) - 1
        x_prod = round(x_start + (prod_idx - 0.5) * paso, 1)
        w_prod = round(paso * 1.5, 1)
        rect_prod = {'x': x_prod, 'width': w_prod}

    return {
        'x_start': x_start,
        'x_end': x_end,
        'y_zero': y_zero,
        'y_full': y_full,
        'linea_plan': " ".join(puntos_plan),
        'linea_real': " ".join(puntos_real),
        'poligono_real': poligono_real,
        'proyeccion': proyeccion_svg,
        'x_hoy': x_hoy,
        'hoy_str': hoy_str,
        'hoy_corta': hoy_corta,
        'rect_productiva': rect_prod,
        'puntos_datos': puntos_datos,
        'ultimo_real_pct': ultimo_real_pct,
    }


def construir_radar(linea, contraste, programa):
    """Calcula datos de cobertura y coordenadas SVG para el gráfico de radar."""
    total_horas_prog = HORAS_LECTIVAS_POR_DEFECTO
    if programa and (programa.get('resumen') or {}).get('horas_lectivas_declaradas'):
        total_horas_prog = float(programa['resumen']['horas_lectivas_declaradas']) or HORAS_LECTIVAS_POR_DEFECTO

    comps_dict = {}
    for c in (linea or {}).get('competencias', []):
        nom = c.get('nombre') or 'Competencia'
        comps_dict[nom] = {
            'nombre': nom,
            'horas_planeadas': float(c.get('horas') or 0),
            'horas_programa': float(c.get('horas_programa') or c.get('horas') or 0),
            'avance_real': float(c.get('porcentaje_avance') or 0),
            'tipo': 'tecnica' if c.get('exigible') else 'transversal',
        }

    if contraste and contraste.get('competencias'):
        for cc in contraste['competencias']:
            nom = cc.get('nombre') or ''
            if nom in comps_dict:
                comps_dict[nom]['horas_programa'] = float(cc.get('horas_programa') or comps_dict[nom]['horas_programa'])
            else:
                comps_dict[nom] = {
                    'nombre': nom,
                    'horas_planeadas': float(cc.get('horas_planeacion') or 0),
                    'horas_programa': float(cc.get('horas_programa') or 0),
                    'avance_real': 0.0,
                    'tipo': cc.get('tipo') or 'tecnica',
                }

    ejes_raw = []
    for nom, d in sorted(comps_dict.items(), key=lambda x: (x[1]['tipo'] != 'tecnica', -x[1]['horas_programa'])):
        h_prog = d['horas_programa']
        peso_prog = round((h_prog / total_horas_prog) * 100, 1) if total_horas_prog > 0 else 0
        h_plan = d['horas_planeadas']
        cob_plan = round((h_plan / h_prog) * 100, 1) if h_prog > 0 else 100.0
        nom_corto = nom[:24] + '...' if len(nom) > 26 else nom
        ejes_raw.append({
            'nombre': nom,
            'nombre_corto': nom_corto,
            'tipo': d['tipo'],
            'horas_programa': h_prog,
            'peso_programa_pct': peso_prog,
            'horas_planeadas': h_plan,
            'cobertura_planeada_pct': min(cob_plan, 100.0),
            'avance_real_pct': d['avance_real'],
        })

    ejes_seleccionados = ejes_raw[:MAXIMO_EJES_RADAR]
    num_ejes = max(len(ejes_seleccionados), 3)
    cx, cy = 180, 145
    radio_max = 105

    ejes_con_coords = []
    pts_plan = []
    pts_real = []

    for i, eje in enumerate(ejes_seleccionados):
        ang = (i * 2 * math.pi / num_ejes) - (math.pi / 2)
        ex = round(cx + radio_max * math.cos(ang), 1)
        ey = round(cy + radio_max * math.sin(ang), 1)
        lx = round(cx + (radio_max + 24) * math.cos(ang), 1)
        ly = round(cy + (radio_max + 14) * math.sin(ang), 1)
        anchor = 'middle' if abs(math.cos(ang)) < 0.3 else ('start' if math.cos(ang) > 0 else 'end')

        r_plan = radio_max * (eje['cobertura_planeada_pct'] / 100.0)
        r_real = radio_max * (eje['avance_real_pct'] / 100.0)

        px_plan = round(cx + r_plan * math.cos(ang), 1)
        py_plan = round(cy + r_plan * math.sin(ang), 1)
        px_real = round(cx + r_real * math.cos(ang), 1)
        py_real = round(cy + r_real * math.sin(ang), 1)

        pts_plan.append(f"{px_plan},{py_plan}")
        pts_real.append(f"{px_real},{py_real}")

        eje_dict = dict(eje)
        eje_dict.update({
            'ex': ex, 'ey': ey,
            'lx': lx, 'ly': ly,
            'anchor': anchor,
            'px_plan': px_plan,
            'py_plan': py_plan,
            'px_real': px_real,
            'py_real': py_real,
        })
        ejes_con_coords.append(eje_dict)

    return {
        'ejes': ejes_con_coords,
        'puntos_plan_svg': " ".join(pts_plan),
        'puntos_real_svg': " ".join(pts_real),
        'total_horas_programa': total_horas_prog,
    }


def construir_heatmap_docente(linea, calendario):
    """Calcula la matriz de carga horaria e intensidad docente por trimestre e instructor."""
    bloques = calendario.get('bloques') or []
    if not bloques or not linea.get('resultados'):
        return {
            'filas': [],
            'trimestres': [b['etiqueta'] for b in bloques],
            'totales_ficha': [],
            'resumen': {
                'total_horas_directas': 0.0,
                'total_horas_totales': 0.0,
                'max_intensidad_semanal': 0.0,
                'docentes_count': 0,
            },
        }

    # Semanas por bloque (lectivas reales o 12 por defecto)
    semanas_por_bloque = {}
    for b in bloques:
        f_ini = b.get('inicio')
        f_fin = b.get('fin')
        if f_ini and f_fin:
            dias = max((f_fin - f_ini).days + 1, 1)
            semanas_por_bloque[b['numero']] = max(round(dias / 7.0, 1), 1.0)
        else:
            semanas_por_bloque[b['numero']] = 12.0

    docentes_map = {}
    totales_ficha_directas = {b['numero']: 0.0 for b in bloques}
    totales_ficha_totales = {b['numero']: 0.0 for b in bloques}
    totales_ficha_independientes = {b['numero']: 0.0 for b in bloques}

    for item in linea.get('resultados', []):
        insts_raw = item.get('instructores') or []
        comp_nom = item.get('competencia') or 'Sin competencia'
        comp_tipo = item.get('competencia_tipo') or ('tecnica' if item.get('exigible') else 'transversal')

        # Normalizar instructores y desduplicar
        insts_norm = []
        for x in insts_raw:
            if x:
                n = normalizar_instructor(x, comp_nom, comp_tipo)
                if n and n not in insts_norm:
                    insts_norm.append(n)
        if not insts_norm:
            insts_norm = [normalizar_instructor('', comp_nom, comp_tipo)]

        t_ini = item.get('trimestre_inicio', 1)
        t_fin = item.get('trimestre_fin', 1)
        t_span = max(t_fin - t_ini + 1, 1)

        h_dir_total = float(item.get('horas_directas') or 0.0)
        h_ind_total = float(item.get('horas_independientes') or 0.0)
        h_tot_total = float(item.get('horas_total') or (h_dir_total + h_ind_total))

        if h_dir_total == 0 and h_ind_total == 0 and h_tot_total > 0:
            h_dir_total = h_tot_total

        num_insts = len(insts_norm)
        # Horas repartidas equitativamente entre los instructores asignados a este resultado
        h_dir_por_trim_inst = (h_dir_total / t_span) / num_insts
        h_tot_por_trim_inst = (h_tot_total / t_span) / num_insts
        h_ind_por_trim_inst = (h_ind_total / t_span) / num_insts

        # Horas para el grupo/ficha (el grupo recibe la clase completa)
        h_dir_por_trim_ficha = h_dir_total / t_span
        h_tot_por_trim_ficha = h_tot_total / t_span
        h_ind_por_trim_ficha = h_ind_total / t_span

        for t_num in range(t_ini, t_fin + 1):
            if t_num in totales_ficha_directas:
                totales_ficha_directas[t_num] += h_dir_por_trim_ficha
                totales_ficha_totales[t_num] += h_tot_por_trim_ficha
                totales_ficha_independientes[t_num] += h_ind_por_trim_ficha

        rap_info = {
            'rap': item.get('rap') or 'Resultado de aprendizaje',
            'rap_codigo': item.get('rap_codigo') or '',
            'competencia': comp_nom,
            'fase': item.get('fase') or '',
            'horas_directas': round(h_dir_por_trim_inst, 1),
            'horas_total': round(h_tot_por_trim_inst, 1),
        }

        for nom_inst in insts_norm:
            if nom_inst not in docentes_map:
                docentes_map[nom_inst] = {
                    'directas': {b['numero']: 0.0 for b in bloques},
                    'totales': {b['numero']: 0.0 for b in bloques},
                    'independientes': {b['numero']: 0.0 for b in bloques},
                    'detalles': {b['numero']: [] for b in bloques},
                }
            for t_num in range(t_ini, t_fin + 1):
                if t_num in docentes_map[nom_inst]['directas']:
                    docentes_map[nom_inst]['directas'][t_num] += h_dir_por_trim_inst
                    docentes_map[nom_inst]['totales'][t_num] += h_tot_por_trim_inst
                    docentes_map[nom_inst]['independientes'][t_num] += h_ind_por_trim_inst
                    docentes_map[nom_inst]['detalles'][t_num].append(rap_info)

    filas = []
    max_intensidad_global = 0.0

    def orden_docente(nom):
        comp = componente_instructor(nom)
        orden_tipo = {'tecnico': 1, 'bilinguismo': 2, 'transversal': 3, 'institucional': 4}.get(comp['tipo'], 5)
        return (orden_tipo, nom)

    for doc, datos in sorted(docentes_map.items(), key=lambda x: orden_docente(x[0])):
        total_dir = sum(datos['directas'].values())
        total_tot = sum(datos['totales'].values())
        comp_info = componente_instructor(doc)

        celdas = []
        for b in bloques:
            num_b = b['numero']
            semanas = semanas_por_bloque.get(num_b, 12.0)
            h_dir = round(datos['directas'].get(num_b, 0.0), 1)
            h_tot = round(datos['totales'].get(num_b, 0.0), 1)

            # Intensidad semanal de docencia directa
            intensidad_semanal = round(h_dir / semanas, 1) if semanas > 0 else 0.0
            intensidad_semanal_tot = round(h_tot / semanas, 1) if semanas > 0 else 0.0

            if intensidad_semanal > max_intensidad_global:
                max_intensidad_global = intensidad_semanal

            # Semáforo normativo SENA (Resolución 642 de 2004: max 32h directas/semana)
            if h_dir <= 0 and h_tot <= 0:
                nivel = 'cero'
                nivel_label = 'Sin asignación'
            elif intensidad_semanal > 32:
                nivel = 'alto'
                nivel_label = 'Sobrecarga (>32 h/sem)'
            elif intensidad_semanal >= 28:
                nivel = 'pleno'
                nivel_label = 'Jornada Plena (28–32 h/sem)'
            elif intensidad_semanal >= 10:
                nivel = 'medio'
                nivel_label = 'Carga Regular (10–28 h/sem)'
            else:
                nivel = 'bajo'
                nivel_label = 'Carga Ligera (<10 h/sem)'

            celdas.append({
                'numero': num_b,
                'etiqueta': b['etiqueta'],
                'horas': h_dir,
                'horas_directas': h_dir,
                'horas_totales': h_tot,
                'semanas': semanas,
                'intensidad_semanal': intensidad_semanal,
                'intensidad_semanal_tot': intensidad_semanal_tot,
                'nivel': nivel,
                'nivel_label': nivel_label,
                'raps': datos['detalles'].get(num_b, []),
                'num_raps': len(datos['detalles'].get(num_b, [])),
            })

        filas.append({
            'instructor': doc,
            'componente': comp_info,
            'total_horas': round(total_dir, 1),
            'total_horas_directas': round(total_dir, 1),
            'total_horas_totales': round(total_tot, 1),
            'celdas': celdas,
        })

    # Fila de consolidado general de la Ficha
    celdas_totales_ficha = []
    for b in bloques:
        num_b = b['numero']
        semanas = semanas_por_bloque.get(num_b, 12.0)
        tot_dir = round(totales_ficha_directas.get(num_b, 0.0), 1)
        tot_tot = round(totales_ficha_totales.get(num_b, 0.0), 1)
        int_sem_grupo = round(tot_dir / semanas, 1) if semanas > 0 else 0.0

        celdas_totales_ficha.append({
            'numero': num_b,
            'etiqueta': b['etiqueta'],
            'horas_directas': tot_dir,
            'horas_totales': tot_tot,
            'semanas': semanas,
            'intensidad_semanal': int_sem_grupo,
            'nivel_ficha': 'sobrecargado' if int_sem_grupo > 35 else ('adecuado' if int_sem_grupo >= 20 else ('ligero' if int_sem_grupo > 0 else 'cero')),
        })

    return {
        'trimestres': [b['etiqueta'] for b in bloques],
        'bloques': [{'numero': b['numero'], 'etiqueta': b['etiqueta'], 'semanas': semanas_por_bloque.get(b['numero'], 12.0)} for b in bloques],
        'filas': filas,
        'totales_ficha': celdas_totales_ficha,
        'resumen': {
            'total_horas_directas': round(sum(totales_ficha_directas.values()), 1),
            'total_horas_totales': round(sum(totales_ficha_totales.values()), 1),
            'max_intensidad_semanal': max_intensidad_global,
            'docentes_count': len(filas),
        },
    }


def construir_fases_progreso(linea, seguimiento=None):
    """Resume las fases del proyecto formativo para tarjetas visuales de progreso."""
    fases = (linea or {}).get('fases') or []
    seguimiento_por_fase = {}
    if seguimiento:
        for fase in seguimiento.get('fases') or []:
            clave = unicodedata.normalize('NFKD', str(fase.get('nombre') or ''))
            clave = ''.join(c for c in clave if not unicodedata.combining(c)).lower()
            seguimiento_por_fase[clave] = fase
    resumen_fases = []

    for f in fases:
        nombre = f.get('nombre') or 'Sin fase'
        horas = float(f.get('horas') or 0)
        avance = int(f.get('porcentaje_avance') or 0)
        raps_total = int(f.get('resultados_total') or 0)
        comps = f.get('competencias') or []
        comps_tecnicas = sum(1 for c in comps if c.get('exigible'))
        comps_transversales = len(comps) - comps_tecnicas
        desfase_dias = int(f.get('dias_desfase') or 0)

        icono = '📌'
        nom_l = nombre.lower()
        if 'analisis' in nom_l or 'análisis' in nom_l:
            icono = '🔍'
        elif 'planeacion' in nom_l or 'planeación' in nom_l:
            icono = '📐'
        elif 'ejecucion' in nom_l or 'ejecución' in nom_l:
            icono = '⚙️'
        elif 'evaluacion' in nom_l or 'evaluación' in nom_l:
            icono = '🎯'
        elif 'productiva' in nom_l or 'practica' in nom_l:
            icono = '🏢'

        clave_fase = unicodedata.normalize('NFKD', nombre)
        clave_fase = ''.join(c for c in clave_fase if not unicodedata.combining(c)).lower()
        seguimiento_fase = seguimiento_por_fase.get(clave_fase, {})
        estado_ritmo = seguimiento_fase.get('estado_ritmo')
        tono_ritmo = {
            'atrasado': 'danger',
            'adelantado': 'success',
            'al_dia': 'success',
            'futura': 'neutral',
        }.get(estado_ritmo, f.get('estado_tono'))

        resumen_fases.append({
            'nombre': nombre,
            'icono': icono,
            'etiqueta_trimestre': f.get('etiqueta_trimestre'),
            'horas': round(horas, 1),
            'porcentaje_avance': avance,
            'estado_label': f.get('estado_label'),
            'estado_tono': f.get('estado_tono'),
            'resultados_total': raps_total,
            'competencias_total': len(comps),
            'competencias_tecnicas': comps_tecnicas,
            'competencias_transversales': comps_transversales,
            'dias_desfase': desfase_dias,
            'resultados_evaluados': seguimiento_fase.get('resultados_evaluados', 0),
            'resultados_aprobados': seguimiento_fase.get('resultados_aprobados', 0),
            'resultados_esperados': seguimiento_fase.get('resultados_esperados', 0),
            'brecha_resultados': seguimiento_fase.get('brecha_resultados', 0),
            'porcentaje_evaluados': seguimiento_fase.get('porcentaje_evaluados', 0),
            'estado_ritmo': estado_ritmo or 'sin_datos',
            'estado_ritmo_tono': tono_ritmo or 'neutral',
        })

    return resumen_fases



