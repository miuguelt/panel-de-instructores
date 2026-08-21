"""Curva de avance planeado contra real, métricas EVM y proyección estadística.

El ritmo se calcula con las aprobaciones fechadas del Reporte de Juicios
Evaluativos, que es la única evidencia de cuándo ocurrió realmente la
formación. La proyección integra Gestión de Valor Ganado (Earned Value Management)
y estimación probabilística (P10, P50, P90) para evaluar la viabilidad del cierre.

Solo entran las competencias exigibles (técnicas) para el cronograma crítico.
Las transversales y el inglés se resumen de manera complementaria.
"""

from __future__ import annotations

import math
from datetime import date, timedelta


DIAS_POR_MES = 30.44
VENTANA_RITMO_DIAS = 180
MARGEN_RIESGO_DIAS = 30


def _fechas(item):
    valores = []
    for valor in item.get('fechas_aprobacion') or []:
        valores.append(valor.date() if hasattr(valor, 'date') else valor)
    return sorted(fecha for fecha in valores if fecha)


def _resumen_flexibles(resultados, aprendices_meta):
    """Avance de lo que se sugiere pero no ata el cronograma."""
    meta = max(aprendices_meta or 0, 1)
    posibles = len(resultados) * meta
    aprobados = sum(min(item.get('aprendices_aprobados') or 0, meta) for item in resultados)
    return {
        'resultados': len(resultados),
        'competencias': len({item.get('competencia') for item in resultados}),
        'horas': round(sum(max(item.get('horas_total') or 0, 0) for item in resultados)),
        'aprobados': aprobados,
        'pendientes': max(posibles - aprobados, 0),
        'porcentaje_avance': round(aprobados / posibles * 100) if posibles else 0,
    }


def _curva_y_evm(resultados, calendario, aprendices_meta, hoy):
    """Calcula curva acumulada, métricas de Valor Ganado (EVM) y Flujo Acumulado (CFD)."""
    horas_totales = sum(max(item.get('horas_total') or 0, 0) for item in resultados)
    peso_unitario = not horas_totales
    total_horas = len(resultados) if peso_unitario else horas_totales

    curva = []
    cfd = []
    pv_acumulado_actual = 0.0
    ev_acumulado_actual = 0.0
    pv_cerrado = 0.0
    total_raps = len(resultados)

    for bloque in calendario['bloques']:
        planeado_horas = 0.0
        real_horas = 0.0
        es_pasado_o_actual = bloque['inicio'] <= hoy

        # CFD counts
        cfd_aprobados = 0
        cfd_en_evaluacion = 0
        cfd_en_formacion = 0
        cfd_no_iniciados = 0

        for item in resultados:
            peso = 1 if peso_unitario else max(item.get('horas_total') or 0, 0)
            if not peso:
                continue

            # PV: Horas cuyo trimestre de fin <= bloque actual
            if item.get('trimestre_fin', 1) <= bloque['numero']:
                planeado_horas += peso

            fechas = _fechas(item)
            meta = max(aprendices_meta or len(fechas) or 1, 1)
            aprobados_a_fecha = sum(1 for f in fechas if f <= bloque['fin']) if fechas else 0
            ratio_aprobacion = min(aprobados_a_fecha / meta, 1.0)
            
            real_horas += peso * ratio_aprobacion

            # CFD classification
            if ratio_aprobacion >= 0.8:
                cfd_aprobados += 1
            elif ratio_aprobacion > 0:
                cfd_en_evaluacion += 1
            elif item.get('trimestre_inicio', 1) <= bloque['numero']:
                cfd_en_formacion += 1
            else:
                cfd_no_iniciados += 1

        # Acumulados a la fecha de hoy. El valor ganado ya está medido a hoy,
        # así que el planeado del trimestre en curso se prorratea por la parte
        # transcurrida: comparar ambos en instantes distintos infla el SPI.
        if es_pasado_o_actual:
            if bloque['fin'] < hoy:
                pv_acumulado_actual = planeado_horas
            else:
                dias = max((bloque['fin'] - bloque['inicio']).days + 1, 1)
                avance = min(max((hoy - bloque['inicio']).days + 1, 0) / dias, 1.0)
                pv_acumulado_actual = pv_cerrado + (planeado_horas - pv_cerrado) * avance
            ev_acumulado_actual = real_horas
        if bloque['fin'] < hoy:
            pv_cerrado = planeado_horas

        curva.append({
            'numero': bloque['numero'],
            'etiqueta': bloque['etiqueta'],
            'nombre': bloque['nombre'],
            'etapa': bloque['etapa'],
            'estado': bloque['estado'],
            'planeado': round(planeado_horas / total_horas * 100) if total_horas else 0,
            'real': (round(real_horas / total_horas * 100) if total_horas else 0) if es_pasado_o_actual else None,
            'pv_horas': round(planeado_horas, 1),
            'ev_horas': round(real_horas, 1) if es_pasado_o_actual else None,
        })

        cfd.append({
            'numero': bloque['numero'],
            'etiqueta': bloque['etiqueta'],
            'aprobados': cfd_aprobados,
            'en_evaluacion': cfd_en_evaluacion,
            'en_formacion': cfd_en_formacion,
            'no_iniciados': cfd_no_iniciados,
            'total': total_raps,
        })

    # EVM global KPIs
    spi = round(ev_acumulado_actual / pv_acumulado_actual, 2) if pv_acumulado_actual > 0 else (1.0 if not resultados else 0.0)
    sv_horas = round(ev_acumulado_actual - pv_acumulado_actual, 1)
    
    if spi >= 1.05:
        evm_estado = 'adelantado'
        evm_tono = 'success'
        evm_label = 'Horas ganadas por encima del plan'
    elif spi >= 0.95:
        evm_estado = 'a_tiempo'
        evm_tono = 'success'
        evm_label = 'Horas ganadas al ritmo del plan'
    elif spi >= 0.75:
        evm_estado = 'atraso_moderado'
        evm_tono = 'warning'
        evm_label = 'Horas ganadas por debajo del plan'
    else:
        evm_estado = 'atraso_critico'
        evm_tono = 'danger'
        evm_label = 'Horas ganadas muy por debajo del plan'

    evm = {
        'pv_horas': round(pv_acumulado_actual, 1),
        'ev_horas': round(ev_acumulado_actual, 1),
        'total_horas': round(total_horas, 1),
        'spi': spi,
        'sv_horas': sv_horas,
        'estado': evm_estado,
        'tono': evm_tono,
        'label': evm_label,
    }

    return curva, evm, cfd


def _ritmo_mensual(resultados, hoy):
    """Aprobaciones por mes en la ventana reciente, ignorando homologaciones."""
    desde = hoy - timedelta(days=VENTANA_RITMO_DIAS)
    recientes = sum(
        1 for item in resultados for fecha in _fechas(item)
        if desde <= fecha <= hoy
    )
    return round(recientes / (VENTANA_RITMO_DIAS / DIAS_POR_MES), 1)


def construir_proyeccion(resultados, calendario, aprendices_meta=0, hoy=None):
    """Proyecta el cierre lectivo con ritmo real, EVM y percentiles estadísticos."""
    hoy = hoy or date.today()
    vacio = {
        'curva': [], 'cfd': [], 'ritmo_mensual': 0, 'ritmo_requerido': 0, 'brecha_ritmo': 0,
        'pares_totales': 0, 'pares_aprobados': 0,
        'pares_pendientes': 0, 'porcentaje_pares': 0, 'meses_faltantes': None,
        'meses_restantes_lectiva': 0,
        'fecha_proyectada': None, 'dias_vs_fin_lectiva': None, 'estado': 'sin_datos',
        'evm': {'pv_horas': 0, 'ev_horas': 0, 'total_horas': 0, 'spi': 0, 'sv_horas': 0, 'estado': 'sin_datos', 'tono': 'neutral', 'label': 'Sin datos'},
        'proyeccion_probabilistica': None,
    }
    if not resultados or not calendario.get('configurado'):
        return vacio

    exigibles = [item for item in resultados if item.get('exigible')]
    flexibles = [item for item in resultados
                 if not item.get('exigible') and item.get('etapa') != 'productiva']
    meta = max(aprendices_meta or 0, 1)
    pares_totales = len(exigibles) * meta
    pares_aprobados = min(
        sum(min(item.get('aprendices_aprobados') or 0, meta) for item in exigibles),
        pares_totales,
    )
    ritmo = _ritmo_mensual(exigibles, hoy)
    curva, evm, cfd = _curva_y_evm(exigibles, calendario, meta, hoy)
    transversales = _resumen_flexibles(flexibles, meta)
    pendientes = max(pares_totales - pares_aprobados, 0)
    dias_restantes = max(calendario.get('dias_restantes_lectiva') or 0, 0)
    meses_restantes = round(dias_restantes / DIAS_POR_MES, 1) if dias_restantes > 0 else 0
    ritmo_requerido = round(pendientes / meses_restantes, 1) if (meses_restantes > 0 and pendientes > 0) else 0
    brecha_ritmo = round(ritmo - ritmo_requerido, 1) if ritmo_requerido > 0 else 0

    if not ritmo or not pares_totales:
        estado = 'completado' if pares_totales and not pendientes else 'sin_datos'
        return {**vacio, 'curva': curva, 'cfd': cfd, 'evm': evm, 'pares_totales': pares_totales,
                'pares_aprobados': pares_aprobados, 'pares_pendientes': pendientes,
                'transversales': transversales, 'estado': estado,
                'ritmo_requerido': ritmo_requerido,
                'brecha_ritmo': brecha_ritmo,
                'meses_restantes_lectiva': meses_restantes,
                'porcentaje_pares': round(pares_aprobados / pares_totales * 100) if pares_totales else 0}

    meses = round(pendientes / ritmo, 1)
    proyectada = hoy + timedelta(days=round(meses * DIAS_POR_MES))
    diferencia = (proyectada - calendario['fin_lectiva']).days
    if not pendientes:
        estado = 'completado'
    elif diferencia <= -MARGEN_RIESGO_DIAS:
        estado = 'holgado'
    elif diferencia <= 0:
        estado = 'ajustado'
    else:
        estado = 'en_riesgo'

    # Modelado probabilístico P10 (optimista), P50 (esperado), P90 (conservador)
    meses_p10 = round(pendientes / (ritmo * 1.25), 1) if ritmo > 0 else meses
    meses_p50 = meses
    meses_p90 = round(pendientes / (max(ritmo * 0.70, 0.5)), 1)

    fecha_p10 = hoy + timedelta(days=round(meses_p10 * DIAS_POR_MES))
    fecha_p50 = proyectada
    fecha_p90 = hoy + timedelta(days=round(meses_p90 * DIAS_POR_MES))

    proyeccion_probabilistica = {
        'p10': {'meses': meses_p10, 'fecha': fecha_p10, 'dias_vs_fin': (fecha_p10 - calendario['fin_lectiva']).days},
        'p50': {'meses': meses_p50, 'fecha': fecha_p50, 'dias_vs_fin': diferencia},
        'p90': {'meses': meses_p90, 'fecha': fecha_p90, 'dias_vs_fin': (fecha_p90 - calendario['fin_lectiva']).days},
    }

    return {
        'curva': curva,
        'cfd': cfd,
        'evm': evm,
        'ritmo_mensual': ritmo,
        'ritmo_requerido': ritmo_requerido,
        'brecha_ritmo': brecha_ritmo,
        'meses_restantes_lectiva': meses_restantes,
        'pares_totales': pares_totales,
        'pares_aprobados': pares_aprobados,
        'pares_pendientes': pendientes,
        'porcentaje_pares': round(pares_aprobados / pares_totales * 100) if pares_totales else 0,
        'meses_faltantes': meses,
        'fecha_proyectada': proyectada,
        'dias_vs_fin_lectiva': diferencia,
        'estado': estado,
        'transversales': transversales,
        'proyeccion_probabilistica': proyeccion_probabilistica,
    }

