"""Ficha pedagógica de cada competencia para la vista de planeación.

Reúne en una sola entrada lo que el programa oficial exige (conocimientos,
criterios de evaluación, perfil del instructor) y lo que la ficha lleva hecho.
La correspondencia entre el rótulo de la planeación y la competencia oficial
ya la resolvió el contraste; aquí solo se consume, sin volver a adivinar por
parecido de nombres.
"""

from __future__ import annotations

from app.services.emparejamiento_juicios import clave_resultado


import re


def buscar_info_pedagogica(nombre, contraste):
    """Ubica la competencia oficial que corresponde a un rótulo de la planeación."""
    contraste = contraste or {}
    diccionario = contraste.get('diccionario_pedagogico') or {}
    mapa = contraste.get('mapa_competencias') or {}
    if not nombre or not (diccionario or mapa):
        return None
    clave = clave_resultado(nombre)
    directo = (mapa.get(nombre) or mapa.get(clave)
               or diccionario.get(nombre) or diccionario.get(clave))
    if directo:
        return directo

    # Búsqueda por código de norma incrustado en el texto (ej. 240201526)
    cod_match = re.search(r'\b(\d{7,10})\b', str(nombre))
    if cod_match and cod_match.group(1) in diccionario:
        return diccionario[cod_match.group(1)]

    # Búsqueda por inclusión de subcadenas clave
    for k, v in diccionario.items():
        if k and len(k) > 5 and (k in clave or clave in k):
            return v
    return None


def enriquecer_con_pedagogia(linea, contraste):
    """Adjunta el contenido curricular a cada competencia y resultado de la línea."""
    diccionario = (contraste or {}).get('diccionario_pedagogico') or {}
    if not diccionario and not (contraste or {}).get('mapa_competencias'):
        return
    for comp in linea.get('competencias', []):
        info = buscar_info_pedagogica(comp.get('nombre'), contraste)
        if info:
            comp['codigo_norma'] = info.get('codigo_norma', '')
            comp['norma'] = info.get('norma', comp.get('nombre'))
            comp['conocimientos_proceso'] = info.get('conocimientos_proceso', [])
            comp['conocimientos_saber'] = info.get('conocimientos_saber', [])
            comp['criterios_evaluacion'] = info.get('criterios_evaluacion', [])
            comp['perfil_instructor'] = info.get('perfil_instructor', {})
            comp['horas_programa'] = info.get('horas', 0)
            comp['resultados_programa'] = info.get('resultados', [])

    for item in linea.get('resultados', []):
        codigo = item.get('rap_codigo') or ''
        info = diccionario.get(codigo) or buscar_info_pedagogica(item.get('competencia'), contraste)
        if info:
            item['codigo_norma'] = info.get('codigo_norma', '')
            item['norma'] = info.get('norma', item.get('competencia'))
            item['criterios_evaluacion'] = info.get('criterios_evaluacion', [])
            item['conocimientos_proceso'] = info.get('conocimientos_proceso', [])
            item['conocimientos_saber'] = info.get('conocimientos_saber', [])
            item['perfil_instructor'] = info.get('perfil_instructor', {})


def construir_catalogo(linea, contraste):
    """Indexa cada competencia por todos sus rótulos para abrir la ficha."""
    catalogo = {}
    dict_ped = (contraste or {}).get('diccionario_pedagogico') or {}
    for clave, comp in dict_ped.items():
        if not clave:
            continue
        item_entry = {
            'nombre': comp.get('nombre') or clave,
            'norma': comp.get('norma') or comp.get('nombre') or '',
            'codigo_norma': str(comp.get('codigo_norma') or ''),
            'tipo': comp.get('tipo') or 'tecnica',
            'horas_programa': comp.get('horas') or 0,
            'horas_planeadas': 0,
            'conocimientos_proceso': comp.get('conocimientos_proceso') or [],
            'conocimientos_saber': comp.get('conocimientos_saber') or [],
            'criterios_evaluacion': comp.get('criterios_evaluacion') or [],
            'perfil_instructor': comp.get('perfil_instructor') or {},
            'resultados_programa': comp.get('resultados') or [],
            'resultados_planeados': [],
        }
        catalogo[clave] = item_entry
        catalogo[clave_resultado(clave)] = item_entry
        if comp.get('codigo_norma'):
            catalogo[str(comp['codigo_norma'])] = item_entry

    # El programa titula varias competencias distinto a como las escribe la
    # planeación (por ejemplo "COMUNICACIÓN" contra el nombre largo de la
    # norma). El contraste ya resolvió esa correspondencia: se registran sus
    # nombres como alias para que la ficha pedagógica abra desde cualquiera.
    for alias, comp in ((contraste or {}).get('mapa_competencias') or {}).items():
        entrada = catalogo.get(str(comp.get('codigo_norma') or '')) \
            or catalogo.get(clave_resultado(comp.get('nombre')))
        if entrada is not None:
            catalogo.setdefault(alias, entrada)
            catalogo.setdefault(clave_resultado(alias), entrada)

    for comp in (linea or {}).get('competencias', []):
        nom = comp.get('nombre') or ''
        clave_nom = clave_resultado(nom)
        entry = catalogo.get(clave_nom) or catalogo.get(nom)
        if not entry and comp.get('codigo_norma'):
            entry = catalogo.get(str(comp['codigo_norma']))
        if not entry:
            entry = {
                'nombre': nom,
                'norma': comp.get('norma') or nom,
                'codigo_norma': str(comp.get('codigo_norma') or ''),
                'tipo': 'tecnica' if comp.get('exigible') else 'transversal',
                'horas_programa': comp.get('horas_programa') or comp.get('horas') or 0,
                'conocimientos_proceso': comp.get('conocimientos_proceso') or [],
                'conocimientos_saber': comp.get('conocimientos_saber') or [],
                'criterios_evaluacion': comp.get('criterios_evaluacion') or [],
                'perfil_instructor': comp.get('perfil_instructor') or {},
                'resultados_programa': comp.get('resultados_programa') or [],
                'resultados_planeados': [],
            }
            catalogo[clave_nom] = entry

        entry['horas_planeadas'] = comp.get('horas') or 0
        entry['horas_directas'] = comp.get('horas_directas') or 0
        entry['horas_independientes'] = comp.get('horas_independientes') or 0
        entry['porcentaje_avance'] = comp.get('porcentaje_avance') or 0
        entry['estado_label'] = comp.get('estado_label') or ''
        entry['estado_tono'] = comp.get('estado_tono') or 'neutral'
        entry['etiqueta_trimestre'] = comp.get('etiqueta_trimestre') or ''
        entry['instructores'] = comp.get('instructores') or []
        entry['dias_desfase'] = comp.get('dias_desfase') or 0
        entry['fecha_primera_aprobacion'] = comp.get('fecha_primera_aprobacion').strftime('%d/%m/%Y') if comp.get('fecha_primera_aprobacion') else None
        entry['fecha_cierre_real'] = comp.get('fecha_cierre_real').strftime('%d/%m/%Y') if comp.get('fecha_cierre_real') else None

        if comp.get('conocimientos_proceso') and not entry.get('conocimientos_proceso'):
            entry['conocimientos_proceso'] = comp['conocimientos_proceso']
        if comp.get('conocimientos_saber') and not entry.get('conocimientos_saber'):
            entry['conocimientos_saber'] = comp['conocimientos_saber']
        if comp.get('criterios_evaluacion') and not entry.get('criterios_evaluacion'):
            entry['criterios_evaluacion'] = comp['criterios_evaluacion']
        if comp.get('perfil_instructor') and not entry.get('perfil_instructor'):
            entry['perfil_instructor'] = comp['perfil_instructor']

        entry['resultados_planeados'] = [
            {
                'rap': r.get('rap'),
                'rap_codigo': r.get('rap_codigo'),
                'actividad': r.get('actividad'),
                'horas_total': r.get('horas_total'),
                'horas_directas': r.get('horas_directas'),
                'horas_independientes': r.get('horas_independientes'),
                'porcentaje_avance': r.get('porcentaje_avance'),
                'aprendices_aprobados': r.get('aprendices_aprobados'),
                'estado_label': r.get('estado_label'),
                'estado_tono': r.get('estado_tono'),
                'instructores': r.get('instructores') or [],
                'evaluadores': [e['nombre'] for e in (r.get('evaluadores') or [])],
            }
            for r in comp.get('resultados', [])
        ]
        catalogo[nom] = entry
        catalogo[clave_nom] = entry
        if entry.get('codigo_norma'):
            catalogo[str(entry['codigo_norma'])] = entry
        if comp.get('norma'):
            catalogo[clave_resultado(comp['norma'])] = entry

    return catalogo
