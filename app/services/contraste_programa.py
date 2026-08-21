"""Contraste entre la planeación pedagógica y el diseño curricular oficial.

Responde tres preguntas que ninguno de los dos documentos contesta solo: si la
planeación reparte las horas que el programa exige, si dejó competencias o
resultados sin planear, y qué intensidad horaria implica el calendario de la
ficha.
"""

from __future__ import annotations

import re

from app.services.emparejamiento_juicios import clave_resultado


SEMANAS_POR_MES = 4.345
TOLERANCIA_HORAS = 0.05
UMBRAL_SOLAPE = 0.60
MINIMO_PALABRAS_COMUNES = 2


def _vacio():
    return {
        'disponible': False,
        'horas': {},
        'competencias': [],
        'competencias_sin_planear': [],
        'resultados_sin_planear': [],
        'intensidad': {},
        'diccionario_pedagogico': {},
        'mapa_competencias': {},
    }


def _codigo_norma_unidad(unidad):
    for campo in ('rap_codigo', 'rap', 'competencia'):
        encontrado = re.search(r'\b(\d{7,10})\b', str(unidad.get(campo) or ''))
        if encontrado:
            return encontrado.group(1)
    return ''


def _horas_planeadas(unidades):
    """Agrupa las unidades de la planeación por competencia tal como la rotula.

    La planeación puede usar varios rótulos para una misma competencia oficial;
    aquí se conserva cada rótulo por separado y el emparejamiento posterior los
    reúne bajo la competencia del programa que les corresponde.
    """
    acumulado = {}
    for unidad in unidades or []:
        nombre = (unidad.get('competencia') or '').strip()
        clave = clave_resultado(nombre)
        codigo = _codigo_norma_unidad(unidad)
        identificador = clave or codigo
        if not identificador:
            continue
        dato = acumulado.setdefault(identificador, {
            'nombre': nombre,
            'clave': clave,
            'codigo': codigo,
            'horas': 0.0,
            'resultados': set(),
        })
        if codigo and not dato['codigo']:
            dato['codigo'] = codigo
        dato['horas'] += max(float(unidad.get('horas_total') or 0), 0)
        rap = clave_resultado(unidad.get('rap'))
        if rap:
            dato['resultados'].add(rap)
    return acumulado, list(acumulado.values())


def _estado_horas(diferencia, referencia):
    if not referencia:
        return 'sin_referencia'
    if abs(diferencia) <= referencia * TOLERANCIA_HORAS:
        return 'coincide'
    return 'sobra' if diferencia > 0 else 'falta'


def _resultados_faltantes(competencia, planeados):
    faltantes = []
    for resultado in competencia['resultados']:
        clave = clave_resultado(resultado['nombre'])
        if clave and not any(clave in planeado or planeado in clave for planeado in planeados):
            faltantes.append({
                'competencia': competencia['nombre'],
                'numero': resultado['numero'],
                'nombre': resultado['nombre'],
            })
    return faltantes


def _intensidad(programa, meses_lectivos):
    horas = programa['metadata'].get('horas_lectiva') or programa['resumen']['horas_lectivas_declaradas']
    if not horas or not meses_lectivos:
        return {}
    horas_mes = horas / meses_lectivos
    return {
        'horas_lectivas': round(horas),
        'meses': meses_lectivos,
        'horas_mes': round(horas_mes),
        'horas_semana': round(horas_mes / SEMANAS_POR_MES, 1),
    }


def _similitud_tokens(t1, t2):
    """Solapamiento de palabras significativas entre dos rótulos.

    Exige al menos dos palabras en común: el programa titula competencias con
    una sola palabra ("FISICA", "TIC", "INGLES") y, con una coincidencia
    suelta, cualquier texto que la mencione daría un solapamiento perfecto.
    """
    if not t1 or not t2:
        return 0.0
    stop = {'de', 'la', 'del', 'las', 'los', 'el', 'en', 'para', 'y', 'a', 'con', 'por', 'al', 'segun'}
    s1 = {w for w in clave_resultado(t1).split() if w not in stop and len(w) > 2}
    s2 = {w for w in clave_resultado(t2).split() if w not in stop and len(w) > 2}
    if not s1 or not s2:
        return 0.0
    comunes = s1 & s2
    if len(comunes) < MINIMO_PALABRAS_COMUNES:
        return 0.0
    return len(comunes) / min(len(s1), len(s2))


def _contenida(una, otra):
    """Contención de texto exigiendo que lo contenido tenga entidad propia.

    Sin el mínimo de palabras, un título como "FISICA" quedaría contenido en
    "programas de actividad física" y se llevaría una competencia ajena.
    """
    if not una or not otra:
        return False
    corta, larga = (una, otra) if len(una) <= len(otra) else (otra, una)
    if len(corta.split()) < MINIMO_PALABRAS_COMUNES:
        return False
    return corta in larga


def _puntaje(competencia, entrada):
    """Qué tan probable es que un rótulo de la planeación sea esta competencia.

    Devuelve 3 para una coincidencia exacta o por código de norma, 2 para
    contención de texto y el solapamiento de palabras cuando supera el umbral.
    """
    clave_nom = clave_resultado(competencia.get('nombre'))
    clave_nor = clave_resultado(competencia.get('norma'))
    codigo = str(competencia.get('codigo_norma') or '')
    clave_plan = entrada['clave']
    codigo_plan = str(entrada.get('codigo') or '')

    if codigo and codigo_plan and (codigo == codigo_plan):
        return 3.0
    if clave_plan and clave_plan in (clave_nom, clave_nor):
        return 3.0
    if _contenida(clave_nom, clave_plan) or _contenida(clave_nor, clave_plan):
        return 2.0

    # Coincidencia por RAPs contenidos en la competencia
    raps_programa = [clave_resultado(r.get('nombre')) for r in competencia.get('resultados', [])]
    raps_planeados = entrada.get('resultados', set())
    if raps_programa and raps_planeados:
        raps_coincidentes = 0
        for rp in raps_planeados:
            if any(_similitud_tokens(rp, prog_r) > 0.5 or _contenida(prog_r, rp) for prog_r in raps_programa):
                raps_coincidentes += 1
        if raps_coincidentes > 0:
            return 2.5 + min(raps_coincidentes * 0.2, 0.5)

    solape = max(_similitud_tokens(clave_nom, clave_plan),
                 _similitud_tokens(clave_nor, clave_plan))
    return solape if solape > UMBRAL_SOLAPE else 0.0


def _emparejar_planeadas(competencias, entradas):
    """Reparte los rótulos de la planeación entre las competencias del programa.

    Una competencia puede recibir varios rótulos (la planeación suele partirla
    en dos), pero ningún rótulo se cuenta dos veces: se resuelven primero las
    coincidencias más fuertes para que una similitud débil no le robe el rótulo
    a la competencia que sí lo nombra.
    """
    candidatos = []
    for indice, competencia in enumerate(competencias):
        for entrada in entradas:
            puntaje = _puntaje(competencia, entrada)
            if puntaje:
                candidatos.append((puntaje, indice, entrada))
    candidatos.sort(key=lambda dato: (-dato[0], dato[1]))

    asignadas = {indice: [] for indice in range(len(competencias))}
    usadas = set()
    for puntaje, indice, entrada in candidatos:
        if id(entrada) in usadas:
            continue
        usadas.add(id(entrada))
        asignadas[indice].append(entrada)
    return asignadas


def contrastar_con_programa(unidades_planeacion, programa, meses_lectivos=0):
    """Compara horas y cobertura de la planeación frente al programa oficial."""
    if not programa or not programa.get('competencias'):
        return _vacio()

    planeadas, planeadas_unicas = _horas_planeadas(unidades_planeacion)
    lectivas = [c for c in programa['competencias'] if c['tipo'] != 'productiva']
    asignadas = _emparejar_planeadas(lectivas, planeadas_unicas)
    por_competencia = {id(comp): asignadas[indice] for indice, comp in enumerate(lectivas)}
    comparadas = []
    sin_planear = []
    resultados_sin_planear = []
    diccionario_pedagogico = {}
    # Correspondencia resuelta: nombre tal como lo escribe la planeación ->
    # competencia oficial. Sin esto, cada consumidor repite la búsqueda por
    # nombre y falla en las competencias que el programa titula distinto.
    mapa_competencias = {}

    for competencia in programa['competencias']:
        cod = competencia.get('codigo_norma') or ''
        nom = competencia.get('nombre') or ''
        diccionario_pedagogico[cod] = competencia
        diccionario_pedagogico[clave_resultado(nom)] = competencia
        if competencia.get('norma'):
            diccionario_pedagogico[clave_resultado(competencia['norma'])] = competencia

        if competencia['tipo'] == 'productiva':
            continue

        rotulos = por_competencia.get(id(competencia)) or []
        if not rotulos:
            sin_planear.append({
                'nombre': competencia['nombre'],
                'norma': competencia.get('norma', competencia['nombre']),
                'codigo_norma': competencia['codigo_norma'],
                'horas': competencia['horas'],
                'tipo': competencia['tipo'],
                'resultados': len(competencia['resultados']),
                'conocimientos_proceso': competencia.get('conocimientos_proceso', []),
                'conocimientos_saber': competencia.get('conocimientos_saber', []),
                'criterios_evaluacion': competencia.get('criterios_evaluacion', []),
                'perfil_instructor': competencia.get('perfil_instructor', {}),
            })
            continue

        for rotulo in rotulos:
            nombre_planeado = rotulo.get('nombre') or ''
            if nombre_planeado:
                mapa_competencias[nombre_planeado] = competencia
                mapa_competencias[clave_resultado(nombre_planeado)] = competencia

        encontrada = {
            'nombre': rotulos[0].get('nombre') or '',
            'horas': sum(rotulo['horas'] for rotulo in rotulos),
            'resultados': set().union(*(rotulo['resultados'] for rotulo in rotulos)),
            'rotulos': [rotulo.get('nombre') or '' for rotulo in rotulos],
        }
        diferencia = round(encontrada['horas'] - competencia['horas'], 1)
        comparadas.append({
            'nombre': competencia['nombre'],
            'norma': competencia.get('norma', competencia['nombre']),
            'codigo_norma': competencia['codigo_norma'],
            'tipo': competencia['tipo'],
            'horas_programa': round(competencia['horas']),
            'horas_planeacion': round(encontrada['horas']),
            'diferencia': diferencia,
            'estado': _estado_horas(diferencia, competencia['horas']),
            'resultados_programa': len(competencia['resultados']),
            'resultados_planeacion': len(encontrada['resultados']),
            'rotulos_planeacion': encontrada['rotulos'],
            'resultados_lista': competencia.get('resultados', []),
            'conocimientos_proceso': competencia.get('conocimientos_proceso', []),
            'conocimientos_saber': competencia.get('conocimientos_saber', []),
            'criterios_evaluacion': competencia.get('criterios_evaluacion', []),
            'perfil_instructor': competencia.get('perfil_instructor', {}),
        })
        resultados_sin_planear.extend(_resultados_faltantes(competencia, encontrada['resultados']))

    horas_plan = round(sum(dato['horas'] for dato in planeadas_unicas))
    horas_programa = programa['metadata'].get('horas_lectiva') or programa['resumen']['horas_lectivas_declaradas']
    return {
        'disponible': True,
        'horas': {
            'programa_lectiva': round(horas_programa),
            'programa_total': round(programa['metadata'].get('horas_total') or 0),
            'programa_productiva': round(programa['metadata'].get('horas_productiva') or 0),
            'planeacion': horas_plan,
            'diferencia': round(horas_plan - horas_programa),
            'estado': _estado_horas(horas_plan - horas_programa, horas_programa),
            'tecnicas': programa['resumen']['horas_tecnicas'],
            'transversales': programa['resumen']['horas_transversales'],
            'ingles': programa['resumen']['horas_ingles'],
        },
        'competencias': sorted(comparadas, key=lambda dato: dato['diferencia']),
        'competencias_sin_planear': sin_planear,
        'resultados_sin_planear': resultados_sin_planear,
        'intensidad': _intensidad(programa, meses_lectivos),
        'diccionario_pedagogico': diccionario_pedagogico,
        'mapa_competencias': mapa_competencias,
    }
