"""Extracción del diseño curricular oficial (PDF del Programa de Formación).

El documento del SENA es la única fuente que declara la duración máxima
estimada de cada competencia, su código de norma y la lista completa de
resultados de aprendizaje. La planeación pedagógica reparte esas horas entre
actividades, pero no puede decir si el reparto cubre el programa.
"""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from app.services.importacion_ficha import clasificar_competencia


MARCA_COMPETENCIA = re.compile(
    r'4\.\s*CONTENIDOS?\s+CURRICULARES?\s*(?:DE\s+LA\s+COMPETENCIA)?',
    re.I,
)
_ENCABEZADO = re.compile(r'LÍNEA TECNOLÓGICA:.*?RED DE CONOCIMIENTO[^\n]*\n', re.S)
_PIE = re.compile(r'Página \d+ de \d+\s*\d{2}/\d{2}/\d{2}\s*\d{2}:\d{2}')
_NORMA = re.compile(r'(\d{7,10})\s*4\.2')
_HORAS = re.compile(
    r'(?:APRENDIZAJE\s*\(Horas\)|\(HORAS\)|DURACI[ÓO]N\s*(?:M[ÁA]XIMA)?\s*(?:ESTIMADA)?\s*(?:DEL\s*APRENDIZAJE)?\s*\(?HORAS\)?:?)\s*([\d.,]+)\s*(?:horas)?',
    re.I,
)
# El documento numera los resultados de varias formas: ``01  Texto``, ``01- Texto``, ``01. Texto``.
_RESULTADO = re.compile(r'^(\d{2})(?:\s{2,}|\s*[-–.]\s*)(.+)$', re.M)
_NOMBRE_PRODUCTIVA = re.compile(r'etapa\s+(practica|práctica|productiva)', re.I)


def _texto_pdf(ruta):
    lector = PdfReader(Path(ruta))
    paginas = [pagina.extract_text() or '' for pagina in lector.pages]
    texto = '\n'.join(paginas)
    # Limpiar encabezados multilínea y pies de página oficiales
    texto = re.sub(
        r'LÍNEA TECNOLÓGICA:.*?RED DE CONOCIMIENTO[^\n]*(\n[^\n]+)?\n',
        '\n',
        texto,
        flags=re.S,
    )
    texto = re.sub(
        r'Página \d+ de \d+.*?(\d{2}/\d{2}/\d{2}|\d{6}/\d{2}/\d{2})\s*\d{2}:\d{2}',
        '',
        texto,
    )
    texto = re.sub(r'^\s*DE SOFTWARE\s*$', '', texto, flags=re.M)
    return texto.replace('\r', '')


def _numero(valor):
    try:
        return float(str(valor).replace('.', '').replace(',', '.'))
    except (TypeError, ValueError):
        return 0.0


def _metadatos(texto):
    cabeza = texto[:4000]
    lectiva = re.search(r'([\d.,]+)\s*horas\s*Etapa\s*Lectiva', cabeza, re.I)
    total = re.search(r'Total:\s*([\d.,]+)\s*horas', cabeza, re.I)
    codigo = re.search(r'\b(\d{6})\b', cabeza)
    nombre = ''
    corte = re.split(r'1\.\s*INFORMACION\s+B[ÁA]SICA', cabeza, maxsplit=1)
    if len(corte) > 1:
        candidatos = [linea.strip() for linea in corte[0].splitlines() if linea.strip()]
        nombre = candidatos[-1] if candidatos else ''
    horas_lectiva = _numero(lectiva.group(1)) if lectiva else 0
    horas_total = _numero(total.group(1)) if total else 0
    return {
        'nombre_programa': nombre,
        'codigo_programa': codigo.group(1) if codigo else '',
        'horas_lectiva': horas_lectiva,
        'horas_total': horas_total,
        'horas_productiva': max(horas_total - horas_lectiva, 0),
    }


def _resultados(bloque):
    """Lista los resultados numerados uniendo las líneas que continúan uno."""
    cuerpo = re.split(r'4\.6\s*CONOCIMIENTOS', bloque, maxsplit=1)[0]
    cuerpo = re.split(r'DENOMINACIÓN', cuerpo, maxsplit=1)[-1]
    resultados = []
    for coincidencia in _RESULTADO.finditer(cuerpo):
        inicio = coincidencia.end()
        siguiente = _RESULTADO.search(cuerpo, inicio)
        continuacion = cuerpo[inicio:siguiente.start() if siguiente else len(cuerpo)]
        texto = f'{coincidencia.group(2)} {continuacion}'
        texto = re.sub(r'\s+', ' ', texto).strip()
        if texto:
            resultados.append({'numero': coincidencia.group(1), 'nombre': texto})
    return resultados


def _tipo(nombre):
    if _NOMBRE_PRODUCTIVA.search(nombre or ''):
        return 'productiva'
    return clasificar_competencia(nombre)


def _extraer_vinetas(texto):
    """Extrae líneas, encabezados de actividad y viñetas individuales."""
    if not texto:
        return []
    # Normalizar símbolos de viñetas a asterisco
    normalizado = re.sub(r'[\u2022\u2023\u25E6\u2043\u2219·–—]\s*', '* ', texto)
    lineas = [l.strip() for l in normalizado.splitlines() if l.strip()]
    items = []
    for linea in lineas:
        if '*' in linea:
            partes = [p.strip() for p in linea.split('*') if p.strip()]
            for p in partes:
                p_clean = re.sub(r'\bDE SOFTWARE\b', '', p, flags=re.I).strip()
                p_clean = re.sub(r'\s+', ' ', p_clean).strip()
                if p_clean and len(p_clean) > 2:
                    items.append(p_clean)
        else:
            linea_clean = re.sub(r'\bDE SOFTWARE\b', '', linea, flags=re.I).strip()
            linea_clean = re.sub(r'\s+', ' ', linea_clean).strip()
            if linea_clean and len(linea_clean) > 2:
                items.append(linea_clean)
    return items


def _seccion_texto(bloque, inicio_patron, fin_patron=None):
    corte_inicio = re.split(inicio_patron, bloque, maxsplit=1, flags=re.I)
    if len(corte_inicio) < 2:
        return ''
    cuerpo = corte_inicio[1]
    if fin_patron:
        corte_fin = re.split(fin_patron, cuerpo, maxsplit=1, flags=re.I)
        cuerpo = corte_fin[0]
    return cuerpo.strip()


def _perfil_instructor(bloque):
    cuerpo_perfil = _seccion_texto(bloque, r'4\.8\s*PERFIL\s+DEL\s+INSTRUCTOR', r'4\.9|4\.10|5\.|6\.\s*CONTROL')
    if not cuerpo_perfil:
        return {}
    academicos_raw = _seccion_texto(cuerpo_perfil, r'4\.8\.1\s*Requisitos\s+Acad[ée]micos:?', r'4\.8\.2')
    experiencia_raw = _seccion_texto(cuerpo_perfil, r'4\.8\.2\s*Experiencia\s+laboral[^:]*:?', r'4\.8\.3')
    competencias_docente_raw = _seccion_texto(cuerpo_perfil, r'4\.8\.3\s*Competencias:?')

    academicos = re.sub(r'\s+', ' ', re.sub(r'\bDE SOFTWARE\b', '', academicos_raw, flags=re.I)).strip()
    experiencia = re.sub(r'\s+', ' ', re.sub(r'\bDE SOFTWARE\b', '', experiencia_raw, flags=re.I)).strip()
    return {
        'requisitos_academicos': academicos,
        'experiencia': experiencia,
        'competencias': _extraer_vinetas(competencias_docente_raw),
    }


def _competencia(bloque):
    corte_41 = re.split(r'4\.1\s*(?:NORMA|DENOMINACI[ÓO]N|UNIDAD)', bloque, maxsplit=1, flags=re.I)
    encabezado = re.sub(r'\s+', ' ', corte_41[0]).strip()

    norma_match = (
        re.search(r'4\.2[^\d]*(\d{7,10})', bloque, re.I)
        or re.search(r'(\d{7,10})\s*4\.2', bloque)
        or re.search(r'C[ÓO]DIGO[^\d]*(\d{7,10})', bloque, re.I)
        or re.search(r'\b(\d{9})\b', bloque)
    )
    cod_norma = norma_match.group(1) if norma_match else ''

    nombre_match = re.search(
        r'4\.3\s*NOMBRE\s+DE\s+LA\s+COMPETENCIA\s*:?\s*([^\n\r]+?)(?=\s*4\.4|\s*4\.5|\n\s*4\.|\n\s*DURACI)',
        bloque,
        re.S | re.I,
    )
    nombre_43 = re.sub(r'\s+', ' ', nombre_match.group(1)).strip() if nombre_match else ''

    nombre = nombre_43 or encabezado
    norma = encabezado or nombre_43
    if not nombre and not cod_norma:
        return None

    horas = _HORAS.search(bloque)
    proceso_texto = _seccion_texto(bloque, r'4\.6\.1\s*CONOCIMIENTOS\s+DE\s+PROCESO', r'4\.6\.2\s*CONOCIMIENTOS|4\.7\s*CRITERIOS')
    saber_texto = _seccion_texto(
        bloque,
        r'4\.6\.2\s*(?:CONOCIMIENTOS\s+DEL\s+SABER|CONOCIMIENTO[S]?\s+(?:DE\s+)?CONCEPTOS\s+Y\s+PRINCIPIOS|SABERES)',
        r'4\.7\s*CRITERIOS|4\.8\s*PERFIL',
    )
    criterios_texto = _seccion_texto(bloque, r'4\.7\s*CRITERIOS\s+DE\s+EVALUACI[ÓO]N', r'4\.8\s*PERFIL|4\.9|6\.\s*CONTROL')

    return {
        'nombre': nombre,
        'norma': norma,
        'codigo_norma': cod_norma,
        'horas': _numero(horas.group(1)) if horas else 0,
        'tipo': _tipo(nombre) if _tipo(nombre) != 'tecnica' else _tipo(norma),
        'resultados': _resultados(bloque),
        'conocimientos_proceso': _extraer_vinetas(proceso_texto),
        'conocimientos_saber': _extraer_vinetas(saber_texto),
        'criterios_evaluacion': _extraer_vinetas(criterios_texto),
        'perfil_instructor': _perfil_instructor(bloque),
    }


def parsear_programa(ruta):
    """Lee el PDF oficial y devuelve competencias, horas, contenidos y criterios."""
    texto = _texto_pdf(ruta)
    bloques = MARCA_COMPETENCIA.split(texto)
    competencias = [c for c in (_competencia(bloque) for bloque in bloques[1:]) if c]
    if not competencias:
        raise ValueError(
            'El PDF no tiene la estructura del Programa de Formación del SENA: '
            'no se encontró ninguna sección "CONTENIDOS CURRICULARES DE LA COMPETENCIA".'
        )

    lectivas = [c for c in competencias if c['tipo'] != 'productiva']
    por_tipo = lambda tipo: round(sum(c['horas'] for c in lectivas if c['tipo'] == tipo))
    return {
        'metadata': _metadatos(texto),
        'competencias': competencias,
        'resumen': {
            'competencias': len(competencias),
            'competencias_lectivas': len(lectivas),
            'resultados': sum(len(c['resultados']) for c in competencias),
            'horas_lectivas_declaradas': round(sum(c['horas'] for c in lectivas)),
            'horas_productiva_declarada': round(
                sum(c['horas'] for c in competencias if c['tipo'] == 'productiva')
            ),
            'horas_tecnicas': por_tipo('tecnica'),
            'horas_transversales': por_tipo('transversal'),
            'horas_ingles': por_tipo('ingles'),
        },
    }
