"""Estadísticas de juicios de una ficha (página Estadísticas).

Funciones puras sobre los juicios y aprendices ya consultados. Las métricas
académicas consideran solo a los aprendices en formación; el desglose de
estados incluye a todos para mostrar cuántos siguen o salieron. Cada
aprendiz se resume en una sola pasada, sin recorrer de nuevo todos los
juicios por cada uno.
"""

from collections import Counter, defaultdict

from app.services.emparejamiento_juicios import es_aprobado
from app.services.juicios_aprendiz import tipo_competencia

RANGOS = ('0-25', '26-50', '51-75', '76-99', '100')


def _pct(parte, total):
    return round(parte / total * 100) if total else 0


def distribucion_aprobacion(porcentajes):
    """Aprendices por rango de juicios aprobados."""
    rangos = dict.fromkeys(RANGOS, 0)
    for pct in porcentajes:
        if pct == 100:
            rangos['100'] += 1
        elif pct >= 76:
            rangos['76-99'] += 1
        elif pct >= 51:
            rangos['51-75'] += 1
        elif pct >= 26:
            rangos['26-50'] += 1
        else:
            rangos['0-25'] += 1
    return rangos


def _por_instructor(juicios):
    stats = {}
    for j in juicios:
        datos = stats.setdefault(j.funcionario_registro or 'Sin Registro', {
            'total': 0, 'aprobados': 0, 'no_aprobados': 0, 'tecnica': 0, 'transversal': 0, 'ingles': 0,
            'evaluados': set(), 'con_aprobacion': set(),
        })
        datos['total'] += 1
        datos['evaluados'].add(j.aprendiz_id)
        datos[tipo_competencia(j)] += 1
        if es_aprobado(j.juicio):
            datos['aprobados'] += 1
            datos['con_aprobacion'].add(j.aprendiz_id)
        else:
            datos['no_aprobados'] += 1
    for datos in stats.values():
        datos['total_aprendices'] = len(datos.pop('evaluados'))
        datos['total_aprendices_aprobados'] = len(datos.pop('con_aprobacion'))
    return stats


def _por_competencia(juicios, aprendices_por_id):
    competencias = {}
    for j in juicios:
        nombre = j.competencia or 'Sin nombre'
        datos = competencias.setdefault(nombre, {'nombre': nombre, 'tipo': tipo_competencia(j), 'total': 0, 'aprobados': 0,
                                                 'aprendices': set(), 'resultados': set(), 'aprobados_ids': set()})
        datos['total'] += 1
        datos['aprendices'].add(j.aprendiz_id)
        if j.resultado_aprendizaje:
            datos['resultados'].add(j.resultado_aprendizaje)
        if es_aprobado(j.juicio):
            datos['aprobados'] += 1
            datos['aprobados_ids'].add(j.aprendiz_id)
    for datos in competencias.values():
        datos['pct'] = _pct(datos['aprobados'], datos['total'])
        datos['num_aprendices'] = len(datos.pop('aprendices'))
        datos['pendientes'] = datos['total'] - datos['aprobados']
        datos['resultados_lista'] = sorted(datos.pop('resultados'))
        aprobados = [aprendices_por_id[i] for i in datos.pop('aprobados_ids') if i in aprendices_por_id]
        datos['aprendices_aprobados_lista'] = sorted(
            ({'id': a.id, 'nombre_completo': f'{a.nombre} {a.apellidos}', 'documento': a.documento} for a in aprobados),
            key=lambda a: a['nombre_completo'])
    return competencias


def analizar_juicios_ficha(juicios, aprendices):
    """Todas las cifras de la página Estadísticas a partir de juicios y aprendices de la ficha."""
    estados = Counter(a.estado for a in aprendices)
    en_formacion = {a.id: a for a in aprendices if a.en_formacion}
    juicios = [j for j in juicios if j.aprendiz_id in en_formacion]

    pendientes_por_aprendiz, criticos = Counter(), Counter()
    por_aprendiz = defaultdict(lambda: [0, 0])  # [total, aprobados]
    meses = {}
    for j in juicios:
        aprobado = es_aprobado(j.juicio)
        por_aprendiz[j.aprendiz_id][0] += 1
        por_aprendiz[j.aprendiz_id][1] += int(aprobado)
        if not aprobado:
            pendientes_por_aprendiz[j.aprendiz_id] += 1
            criticos[j.resultado_aprendizaje] += 1
        if j.fecha_juicio:
            mes = meses.setdefault(j.fecha_juicio.strftime('%Y-%m'), {'total': 0, 'aprobados': 0})
            mes['total'] += 1
            mes['aprobados'] += int(aprobado)

    competencias = _por_competencia(juicios, en_formacion)
    aprobados_total = sum(a for _, a in por_aprendiz.values())
    tipos = Counter(tipo_competencia(j) for j in juicios)
    tipos_aprobados = Counter(tipo_competencia(j) for j in juicios if es_aprobado(j.juicio))
    return {
        'estados': dict(estados),
        'total_aprendices': len(aprendices),
        'instructores_stats': _por_instructor(juicios),
        'top_aprendices': [{'aprendiz': en_formacion[i], 'pendientes': n} for i, n in pendientes_por_aprendiz.most_common(10)],
        'top_resultados': criticos.most_common(5),
        'pct_global': _pct(aprobados_total, len(juicios)),
        'competencias_stats': sorted(competencias.values(), key=lambda c: (-c['pendientes'], c['pct'])),
        'timeline': sorted(meses.items()),
        'resumen': {
            'total_aprendices_con_juicios': len(por_aprendiz),
            'total_competencias': len(competencias),
            'total_resultados': len({j.resultado_aprendizaje for j in juicios if j.resultado_aprendizaje}),
            'aprendices_con_todos': sum(1 for t, a in por_aprendiz.values() if a == t),
            'aprendices_sin_ninguno': sum(1 for t, a in por_aprendiz.values() if a == 0 and t),
            'promedio_juicios_por_aprendiz': round(len(juicios) / len(por_aprendiz), 1) if por_aprendiz else 0,
            'transversales_vistas': tipos['transversal'],
            'transversales_faltantes': tipos['transversal'] - tipos_aprobados['transversal'],
            'ingles_aprobados': tipos_aprobados['ingles'],
            'ingles_faltantes': tipos['ingles'] - tipos_aprobados['ingles'],
        },
        'distribucion_aprobacion': distribucion_aprobacion(round(a / t * 100) for t, a in por_aprendiz.values()),
        'mejores_competencias': sorted(competencias.values(), key=lambda c: c['pct'], reverse=True)[:5],
        'peores_competencias': sorted(competencias.values(), key=lambda c: c['pct'])[:5],
    }
