"""Seguimiento unificado de fase, RAP evaluado y viabilidad del programa.

La planeación GFPI-F-134 aporta la fecha esperada de cada resultado; el
Reporte de Juicios aporta si el resultado ya tiene evaluación y el porcentaje
de aprendices que lo aprobó. El Programa de Formación valida la cobertura de
los resultados, pero no se usa para inventar fases que el GFPI-F-134 no
declara.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta


DIAS_POR_MES = 30.44
VENTANA_RITMO_DIAS = 180
UMBRAL_CIERRE_RAP = 80

FASES_PROYECTO = (
    ('ANÁLISIS', '🔍'),
    ('PLANEACIÓN', '📐'),
    ('EJECUCIÓN', '⚙️'),
    ('EVALUACIÓN', '🎯'),
)


def _clave(valor):
    texto = unicodedata.normalize('NFKD', str(valor or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c)).lower()
    return re.sub(r'[^a-z0-9]+', ' ', texto).strip()


def _fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or '').strip()
    for formato in ('%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _fase_orden(nombre):
    clave = _clave(nombre)
    for orden, (fase, _icono) in enumerate(FASES_PROYECTO):
        if _clave(fase) in clave or clave in _clave(fase):
            return orden
    return len(FASES_PROYECTO)


def _evaluado(item):
    """Un RAP está evaluado si trae al menos un juicio efectivamente emitido."""
    if 'total_juicios_evaluados' in item:
        return bool(item.get('total_juicios_evaluados'))
    # Compatibilidad con consumidores de la línea que todavía no enriquecen
    # el diccionario con el conteo detallado de estados del reporte.
    return bool(item.get('total_juicios') or item.get('aprendices_evaluados'))


def _cerrado(item):
    """Un RAP se considera cerrado al alcanzar el umbral institucional de 80 %."""
    return float(item.get('porcentaje_avance') or 0) >= UMBRAL_CIERRE_RAP


def _fraccion_esperada(item, hoy):
    """Avance temporal del RAP, entre 0 y 1, según su ventana planeada."""
    inicio = _fecha(item.get('fecha_plan_inicio'))
    fin = _fecha(item.get('fecha_plan_fin'))
    if not inicio or not fin or fin < inicio:
        return 0.0
    if hoy < inicio:
        return 0.0
    if hoy >= fin:
        return 1.0
    dias = max((fin - inicio).days + 1, 1)
    transcurridos = min(max((hoy - inicio).days + 1, 0), dias)
    return transcurridos / dias


def _entero_esperado(valor):
    """Redondea el avance fraccionario a un conteo comprensible de RAPs."""
    return int(valor + 0.5)


def _ventana_fase(items):
    inicios = [_fecha(item.get('fecha_plan_inicio')) for item in items]
    fines = [_fecha(item.get('fecha_plan_fin')) for item in items]
    inicios = [valor for valor in inicios if valor]
    fines = [valor for valor in fines if valor]
    return (min(inicios) if inicios else None, max(fines) if fines else None)


def _estado_tiempo_fase(inicio, fin, hoy, resultados, aprobados):
    if not resultados:
        return 'no_planeada'
    if aprobados >= resultados:
        return 'cumplida'
    if inicio and hoy < inicio:
        return 'futura'
    if fin and hoy > fin:
        return 'vencida'
    return 'en_curso'


def _resumen_fase(nombre, icono, items, hoy, orden):
    inicio, fin = _ventana_fase(items)
    total = len(items)
    evaluados = sum(1 for item in items if _evaluado(item))
    aprobados = sum(1 for item in items if _cerrado(item))
    esperados_decimal = sum(_fraccion_esperada(item, hoy) for item in items)
    esperados = min(_entero_esperado(esperados_decimal), total)
    estado_tiempo = _estado_tiempo_fase(inicio, fin, hoy, total, aprobados)
    brecha = evaluados - esperados
    if estado_tiempo == 'futura':
        estado_ritmo = 'futura'
    elif not total:
        estado_ritmo = 'no_planeada'
    elif brecha < 0:
        estado_ritmo = 'atrasado'
    elif brecha > 0:
        estado_ritmo = 'adelantado'
    else:
        estado_ritmo = 'al_dia'

    transcurrido = 0
    if inicio and fin:
        if hoy >= fin:
            transcurrido = 100
        elif hoy > inicio:
            dias = max((fin - inicio).days + 1, 1)
            transcurrido = round((hoy - inicio).days / dias * 100)

    return {
        'orden': orden,
        'nombre': nombre,
        'icono': icono,
        'inicio': inicio,
        'fin': fin,
        'planificada': bool(items),
        'estado_tiempo': estado_tiempo,
        'estado_ritmo': estado_ritmo,
        'resultados_total': total,
        'resultados_evaluados': evaluados,
        'resultados_aprobados': aprobados,
        'resultados_pendientes': max(total - aprobados, 0),
        'resultados_esperados': esperados,
        'resultados_esperados_decimal': round(esperados_decimal, 1),
        'brecha_resultados': brecha,
        'porcentaje_evaluados': round(evaluados / total * 100) if total else 0,
        'porcentaje_aprobados': round(aprobados / total * 100) if total else 0,
        'porcentaje_tiempo': max(0, min(transcurrido, 100)),
        'horas': round(sum(float(item.get('horas_total') or 0) for item in items), 1),
        'competencias_total': len({item.get('competencia') for item in items if item.get('competencia')}),
    }


def _construir_fases(linea, hoy):
    agrupados = {}
    for item in (linea or {}).get('resultados') or []:
        nombre = item.get('fase') or 'Sin fase'
        agrupados.setdefault(_clave(nombre), {'nombre': nombre, 'items': []})['items'].append(item)

    fases = []
    for orden, (nombre_canonico, icono) in enumerate(FASES_PROYECTO):
        grupo = agrupados.pop(_clave(nombre_canonico), None)
        items = grupo['items'] if grupo else []
        nombre = grupo['nombre'] if grupo else nombre_canonico
        fases.append(_resumen_fase(nombre, icono, items, hoy, orden))

    for grupo in sorted(agrupados.values(), key=lambda dato: (_fase_orden(dato['nombre']), dato['nombre'])):
        fases.append(_resumen_fase(
            grupo['nombre'], '📌', grupo['items'], hoy, _fase_orden(grupo['nombre']),
        ))
    return fases


def _fase_esperada(fases, hoy):
    planeadas = [fase for fase in fases if fase['planificada'] and fase['inicio'] and fase['fin']]
    if not planeadas:
        return None
    for fase in planeadas:
        if fase['inicio'] <= hoy <= fase['fin']:
            return fase
    futuras = [fase for fase in planeadas if hoy < fase['inicio']]
    return futuras[0] if futuras else planeadas[-1]


def _fase_real(fases):
    planeadas = [fase for fase in fases if fase['planificada']]
    if not planeadas:
        return None
    for fase in planeadas:
        if fase['resultados_aprobados'] < fase['resultados_total']:
            return fase
    return planeadas[-1]


def _fecha_ultima_evaluacion(item):
    fechas = [_fecha(item.get('ultima_evaluacion'))]
    fechas.extend(_fecha(valor) for valor in item.get('fechas_aprobacion') or [])
    fechas = [valor for valor in fechas if valor]
    return max(fechas) if fechas else None


def _proyeccion_resultados(resultados, calendario, hoy):
    total = len(resultados)
    evaluados = sum(1 for item in resultados if _evaluado(item))
    pendientes = max(total - evaluados, 0)
    desde = hoy - timedelta(days=VENTANA_RITMO_DIAS)
    recientes = sum(
        1 for item in resultados
        if _evaluado(item)
        and (fecha := _fecha_ultima_evaluacion(item))
        and desde <= fecha <= hoy
    )
    ritmo = round(recientes / (VENTANA_RITMO_DIAS / DIAS_POR_MES), 1)
    fecha_fin = calendario.get('fin') if calendario else None
    if not pendientes:
        return {
            'resultados_pendientes': 0,
            'ritmo_mensual': ritmo,
            'meses_faltantes': 0,
            'fecha_cierre': hoy,
            'dias_vs_fin': (hoy - fecha_fin).days if fecha_fin else None,
            'estado': 'completado',
        }
    if ritmo <= 0:
        return {
            'resultados_pendientes': pendientes,
            'ritmo_mensual': ritmo,
            'meses_faltantes': None,
            'fecha_cierre': None,
            'dias_vs_fin': None,
            'estado': 'sin_datos',
        }

    meses = round(pendientes / ritmo, 1)
    fecha_cierre = hoy + timedelta(days=round(meses * DIAS_POR_MES))
    dias_vs_fin = (fecha_cierre - fecha_fin).days if fecha_fin else None
    estado = 'viable' if dias_vs_fin is None or dias_vs_fin <= 0 else 'en_riesgo'
    return {
        'resultados_pendientes': pendientes,
        'ritmo_mensual': ritmo,
        'meses_faltantes': meses,
        'fecha_cierre': fecha_cierre,
        'dias_vs_fin': dias_vs_fin,
        'estado': estado,
    }


def construir_seguimiento_fases(linea, calendario, hoy=None):
    """Calcula fase esperada, fase real, brecha de RAPs y cierre proyectado."""
    hoy = hoy or date.today()
    fases = _construir_fases(linea, hoy)
    resultados = (linea or {}).get('resultados') or []
    fase_esperada = _fase_esperada(fases, hoy)
    fase_real = _fase_real(fases)
    total = len(resultados)
    evaluados = sum(1 for item in resultados if _evaluado(item))
    aprobados = sum(1 for item in resultados if _cerrado(item))
    esperados_decimal = sum(_fraccion_esperada(item, hoy) for item in resultados)
    esperados = min(_entero_esperado(esperados_decimal), total)

    if not total:
        estado = 'sin_datos'
    elif aprobados >= total:
        estado = 'completado'
    elif fase_esperada and fase_real and fase_real['orden'] < fase_esperada['orden']:
        estado = 'atrasado'
    elif fase_esperada and fase_real and fase_real['orden'] > fase_esperada['orden']:
        estado = 'adelantado'
    elif evaluados < esperados:
        estado = 'atrasado'
    else:
        estado = 'al_dia'

    return {
        'hoy': hoy,
        'fases': fases,
        'fase_esperada': fase_esperada,
        'fase_real': fase_real,
        'estado': estado,
        'resultados': {
            'total': total,
            'evaluados': evaluados,
            'aprobados': aprobados,
            'pendientes': max(total - aprobados, 0),
            'esperados': esperados,
            'esperados_decimal': round(esperados_decimal, 1),
            'brecha': evaluados - esperados,
            'porcentaje_evaluados': round(evaluados / total * 100) if total else 0,
            'porcentaje_aprobados': round(aprobados / total * 100) if total else 0,
        },
        'proyeccion': _proyeccion_resultados(resultados, calendario or {}, hoy),
    }
