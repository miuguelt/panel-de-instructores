"""Regla de tiempo de una ficha: trimestres lectivos y etapa productiva.

La duración lectiva no se declara en ninguna parte: se deduce restando la
etapa productiva de la ficha. Para ADSO son 27 meses totales menos 6 de etapa
productiva, es decir 21 meses lectivos que la planeación GFPI-F-134 numera
como ``Trimestre 1`` a ``Trimestre 7``.
"""

from __future__ import annotations

import calendar
from datetime import date

from app.services.cronograma import obtener_cronograma


MESES_POR_TRIMESTRE = 3
DIAS_POR_MES = 30.44


def sumar_meses(fecha, meses):
    """Suma meses calendario recortando el día al último válido del mes."""
    total = fecha.year * 12 + fecha.month - 1 + meses
    año, mes_indice = divmod(total, 12)
    mes = mes_indice + 1
    return date(año, mes, min(fecha.day, calendar.monthrange(año, mes)[1]))


def _meses_entre(inicio, fin):
    """Meses aproximados entre dos fechas, redondeados al mes más cercano."""
    return max(round(((fin - inicio).days + 1) / DIAS_POR_MES), 1)


def _estado_bloque(bloque, hoy):
    if hoy > bloque['fin']:
        return 'cumplido'
    if hoy < bloque['inicio']:
        return 'futuro'
    return 'en_curso'


def _porcentaje_transcurrido(bloque, hoy):
    dias = max((bloque['fin'] - bloque['inicio']).days + 1, 1)
    if hoy > bloque['fin']:
        return 100
    if hoy < bloque['inicio']:
        return 0
    return round(min((hoy - bloque['inicio']).days + 1, dias) / dias * 100)


def _calendario_vacio(mensaje):
    return {
        'configurado': False,
        'mensaje': mensaje,
        'bloques': [],
        'bloque_actual': None,
        'trimestres_lectivos': 0,
        'meses_lectiva': 0,
        'meses_productiva': 0,
        'meses_totales': 0,
        'inicio': None,
        'fin': None,
        'fin_lectiva': None,
        'inicio_productiva': None,
        'dias_restantes_lectiva': None,
        'dias_transcurridos_lectiva': None,
        'dias_totales_lectiva': None,
        'porcentaje_lectiva': 0,
        'fase': 'sin_fechas',
    }


def _construir_bloques(inicio, fin_lectiva, inicio_productiva, fin, trimestres, hoy):
    bloques = []
    for numero in range(1, trimestres + 1):
        bloque_inicio = sumar_meses(inicio, MESES_POR_TRIMESTRE * (numero - 1))
        if numero == trimestres:
            # El último trimestre absorbe el residuo para que la etapa lectiva
            # termine exactamente donde empieza la productiva.
            bloque_fin = fin_lectiva
        else:
            siguiente = sumar_meses(inicio, MESES_POR_TRIMESTRE * numero)
            bloque_fin = date.fromordinal(siguiente.toordinal() - 1)
        bloques.append({
            'numero': numero,
            'etiqueta': f'T{numero}',
            'nombre': f'Trimestre {numero}',
            'etapa': 'lectiva',
            'inicio': bloque_inicio,
            'fin': max(bloque_fin, bloque_inicio),
        })
    bloques.append({
        'numero': trimestres + 1,
        'etiqueta': 'EP',
        'nombre': 'Etapa productiva',
        'etapa': 'productiva',
        'inicio': inicio_productiva,
        'fin': fin,
    })
    for bloque in bloques:
        dias_b = max((bloque['fin'] - bloque['inicio']).days + 1, 1)
        bloque['dias'] = dias_b
        bloque['dias_transcurridos'] = min(max((hoy - bloque['inicio']).days + 1, 0), dias_b) if hoy >= bloque['inicio'] else 0
        bloque['estado'] = _estado_bloque(bloque, hoy)
        bloque['porcentaje_transcurrido'] = _porcentaje_transcurrido(bloque, hoy)
    return bloques


def _posicion_hoy(bloques, hoy):
    """Ubica el día actual sobre bloques de igual ancho visual, en porcentaje.

    Los bloques duran distinto (un trimestre son 3 meses y la etapa productiva
    6), pero la línea de tiempo los dibuja del mismo ancho. La posición se
    calcula sobre columnas, no sobre días, para que el marcador coincida con
    lo que se ve.
    """
    total = len(bloques)
    if not total:
        return 0
    for indice, bloque in enumerate(bloques):
        if hoy < bloque['inicio']:
            return round(indice / total * 100, 2)
        if hoy <= bloque['fin']:
            avance = (hoy - bloque['inicio']).days / bloque['dias']
            return round((indice + min(avance, 1)) / total * 100, 2)
    return 100.0


def construir_calendario(ficha, hoy=None):
    """Divide la ficha en trimestres lectivos más un bloque de etapa productiva."""
    hoy = hoy or date.today()
    cronograma = obtener_cronograma(ficha, hoy)
    if not cronograma['configurado']:
        return _calendario_vacio(cronograma['mensaje'])

    inicio = cronograma['inicio_lectiva']
    fin = cronograma['fin_productiva']
    fin_lectiva = cronograma['fin_lectiva']
    inicio_productiva = cronograma['inicio_productiva']
    meses_lectiva = _meses_entre(inicio, fin_lectiva)
    trimestres = max(round(meses_lectiva / MESES_POR_TRIMESTRE), 1)
    bloques = _construir_bloques(inicio, fin_lectiva, inicio_productiva, fin, trimestres, hoy)
    bloque_actual = next((bloque for bloque in bloques if bloque['estado'] == 'en_curso'), None)
    dias_lectiva = max((fin_lectiva - inicio).days + 1, 1)
    transcurridos = min(max((hoy - inicio).days + 1, 0), dias_lectiva)

    return {
        'configurado': True,
        'mensaje': cronograma['mensaje'],
        'bloques': bloques,
        'bloque_actual': bloque_actual,
        'trimestres_lectivos': trimestres,
        'meses_lectiva': meses_lectiva,
        'meses_productiva': cronograma['meses_productiva'],
        'meses_totales': meses_lectiva + cronograma['meses_productiva'],
        'inicio': inicio,
        'fin': fin,
        'fin_lectiva': fin_lectiva,
        'inicio_productiva': inicio_productiva,
        'dias_restantes_lectiva': (fin_lectiva - hoy).days if hoy <= fin_lectiva else 0,
        'dias_transcurridos_lectiva': transcurridos,
        'dias_totales_lectiva': dias_lectiva,
        'porcentaje_lectiva': round(transcurridos / dias_lectiva * 100, 1),
        'posicion_hoy': _posicion_hoy(bloques, hoy),
        'fase': cronograma['fase'],
        'fase_label': cronograma['fase_label'],
    }


def bloque_de(calendario, numero):
    """Devuelve el bloque solicitado sin salirse del calendario disponible."""
    bloques = calendario.get('bloques') or []
    if not bloques:
        return None
    indice = min(max(int(numero or 1), 1), len(bloques)) - 1
    return bloques[indice]
