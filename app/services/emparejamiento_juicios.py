"""Correspondencia entre resultados de la planeación y juicios del reporte oficial.

El Reporte de Juicios Evaluativos y la planeación GFPI-F-134 escriben el mismo
resultado de aprendizaje de formas distintas: con o sin código, con mayúsculas,
con espacios de más. Aquí vive la única regla de emparejamiento del sistema.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from functools import lru_cache


SIMILITUD_MINIMA = 0.78


def texto_limpio(valor):
    limpio = str(valor or '').strip()
    if not limpio or limpio in {'-', '--', '—'}:
        return ''
    return re.sub(r'\s+', ' ', limpio)


def clave_resultado(valor):
    """Normaliza el texto quitando tildes, código inicial y signos."""
    return _normalizar_clave(texto_limpio(valor))


@lru_cache(maxsize=4096)
def _normalizar_clave(texto):
    """Reutiliza únicamente transformaciones de texto, sin guardar datos derivados de la BD."""
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(c for c in texto if not unicodedata.combining(c)).lower()
    texto = re.sub(r'^\s*\d{4,}\s*[-:]\s*', '', texto)
    texto = re.sub(r'^\s*\d{1,3}\s*[-:.)]\s*|^\s*\d{1,3}\s+', '', texto)
    return re.sub(r'[^a-z0-9]+', ' ', texto).strip()


def codigo_resultado(valor):
    encontrado = re.search(r'\d{4,}', texto_limpio(valor))
    return encontrado.group(0) if encontrado else ''


def es_aprobado(juicio):
    """Solo una aprobación explícita cuenta.

    No se usa ``in`` porque "NO APROBADO" también contiene "APROBADO". El
    reporte oficial puede traer otros estados y todos quedan como pendientes
    hasta que exista una aprobación explícita.
    """
    return clave_resultado(juicio) in {'aprobado', 'aprobada'}


def indexar_juicios(juicios):
    """Arma los índices por texto normalizado y por código de resultado."""
    por_clave = defaultdict(list)
    por_codigo = defaultdict(list)
    for juicio in juicios:
        clave = clave_resultado(juicio.resultado_aprendizaje)
        codigo = codigo_resultado(juicio.resultado_aprendizaje)
        if clave:
            por_clave[clave].append(juicio)
        if codigo:
            por_codigo[codigo].append(juicio)
    return por_clave, por_codigo


def juicios_de(unidad, por_clave, por_codigo):
    """Devuelve los juicios que corresponden a una unidad de la planeación."""
    codigo = unidad.get('rap_codigo') or codigo_resultado(unidad.get('rap'))
    clave = clave_resultado(unidad.get('rap'))
    por_codigo_encontrado = por_codigo.get(codigo, []) if codigo else []
    if por_codigo_encontrado:
        return por_codigo_encontrado
    exactos = por_clave.get(clave, [])
    if exactos:
        return exactos
    # Solo se acepta una similitud alta y un único candidato para evitar que
    # textos parecidos de resultados distintos se mezclen en el avance.
    candidato = None
    mejor_ratio = 0.0
    palabras_clave = {w for w in clave.split() if len(w) > 3}
    for otra_clave, registros in por_clave.items():
        ratio = SequenceMatcher(None, clave, otra_clave).ratio()
        if ratio >= SIMILITUD_MINIMA:
            if candidato is not None and abs(ratio - mejor_ratio) < 0.02:
                return []
            if ratio > mejor_ratio:
                mejor_ratio = ratio
                candidato = registros
        elif ratio >= 0.50 and palabras_clave:
            palabras_otra = {w for w in otra_clave.split() if len(w) > 3}
            if len(palabras_clave & palabras_otra) >= 4:
                if ratio > mejor_ratio:
                    mejor_ratio = ratio
                    candidato = registros
    return candidato if candidato is not None else []

