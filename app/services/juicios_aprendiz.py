"""Análisis de los juicios evaluativos de un aprendiz.

Funciones puras: reciben los juicios ya consultados y devuelven las cifras que
muestran el panel del aprendiz y su reporte en PDF. La regla de aprobación es
la canónica (:func:`es_aprobado`), igual en todas las vistas.
"""

from app.services.emparejamiento_juicios import es_aprobado

TIPOS = ('tecnica', 'transversal', 'ingles')


def _pct(parte, total):
    return round(parte / total * 100) if total else 0


def deduplicar_juicios(juicios):
    """Un juicio por (competencia, resultado); prefiere el aprobado y luego el que tiene evaluador."""
    elegidos = {}
    for juicio in juicios:
        clave = ((juicio.competencia or '').strip().upper(), (juicio.resultado_aprendizaje or '').strip().upper())
        actual = elegidos.get(clave)
        if actual is None:
            elegidos[clave] = juicio
            continue
        nuevo_aprobado, actual_aprobado = es_aprobado(juicio.juicio), es_aprobado(actual.juicio)
        if (nuevo_aprobado and not actual_aprobado) or (
                nuevo_aprobado == actual_aprobado and juicio.funcionario_registro and not actual.funcionario_registro):
            elegidos[clave] = juicio
    return list(elegidos.values())


def _estadisticas(juicios):
    stats = {'total': 0, 'aprobados': 0}
    for tipo in TIPOS:
        stats[tipo] = stats[f'{tipo}_aprobada'] = 0
    pendientes, aprobados = [], []
    for juicio in juicios:
        aprobado = es_aprobado(juicio.juicio)
        tipo = juicio.tipo_competencia or 'tecnica'
        stats['total'] += 1
        stats[tipo] = stats.get(tipo, 0) + 1
        if aprobado:
            stats['aprobados'] += 1
            stats[f'{tipo}_aprobada'] = stats.get(f'{tipo}_aprobada', 0) + 1
            aprobados.append(juicio)
        else:
            pendientes.append(juicio)
    stats['pct_total'] = _pct(stats['aprobados'], stats['total'])
    for tipo in TIPOS:
        stats[f'pct_{tipo}'] = _pct(stats[f'{tipo}_aprobada'], stats[tipo])
    return stats, pendientes, aprobados


def _competencias(juicios):
    competencias = {}
    for juicio in juicios:
        nombre = juicio.competencia or 'Sin nombre'
        datos = competencias.setdefault(nombre, {
            'nombre': nombre, 'tipo': juicio.tipo_competencia or 'tecnica',
            'total': 0, 'aprobados': 0, 'pendientes': 0, 'fecha_ultima': juicio.fecha_juicio, 'raps': [],
        })
        aprobado = es_aprobado(juicio.juicio)
        datos['total'] += 1
        datos['aprobados' if aprobado else 'pendientes'] += 1
        if juicio.fecha_juicio and (not datos['fecha_ultima'] or juicio.fecha_juicio > datos['fecha_ultima']):
            datos['fecha_ultima'] = juicio.fecha_juicio
        datos['raps'].append({
            'rap': juicio.resultado_aprendizaje or 'Sin descripción',
            'juicio': juicio.juicio or 'POR EVALUAR',
            'es_aprobado': aprobado,
            'fecha': juicio.fecha_juicio.strftime('%d/%m/%Y') if juicio.fecha_juicio else 'Pendiente',
            'evaluador': juicio.funcionario_registro or 'Sin registro',
        })
    for datos in competencias.values():
        datos['pct'] = _pct(datos['aprobados'], datos['total'])
        datos['estado_label'] = 'Completada' if datos['pct'] == 100 else ('En Progreso' if datos['pct'] > 0 else 'Pendiente')
    return sorted(competencias.values(), key=lambda c: (c['tipo'], c['nombre']))


def _linea_tiempo(juicios):
    meses = {}
    for juicio in juicios:
        if juicio.fecha_juicio:
            mes = meses.setdefault(juicio.fecha_juicio.strftime('%Y-%m'), {'total': 0, 'aprobados': 0})
            mes['total'] += 1
            mes['aprobados'] += int(es_aprobado(juicio.juicio))
    return sorted(meses.items())


def _instructores(juicios):
    instructores = {}
    for juicio in juicios:
        datos = instructores.setdefault(juicio.funcionario_registro or 'Sin registro',
                                        {'total': 0, 'aprobados': 0, 'pendientes': 0})
        datos['total'] += 1
        datos['aprobados' if es_aprobado(juicio.juicio) else 'pendientes'] += 1
    for datos in instructores.values():
        datos['pct'] = _pct(datos['aprobados'], datos['total'])
    return instructores


def analizar_juicios(juicios):
    """Cifras del aprendiz: totales, competencias, línea de tiempo, instructores y resumen."""
    stats, pendientes, aprobados = _estadisticas(juicios)
    competencias = _competencias(juicios)
    instructores = _instructores(juicios)
    fechas = [j.fecha_juicio for j in juicios if j.fecha_juicio]
    # Los documentos numéricos no se muestran como nombre de evaluador.
    evaluadores = sorted({j.funcionario_registro for j in juicios
                          if j.funcionario_registro and any(c.isalpha() for c in j.funcionario_registro)})
    return {
        'stats_juicios': stats,
        'juicios_pendientes': pendientes,
        'juicios_aprobados': aprobados,
        'evaluadores': evaluadores,
        'competencias': competencias,
        'timeline': _linea_tiempo(juicios),
        'instructores': instructores,
        'resumen': {
            'total_competencias': len(competencias),
            'total_instructores': len(instructores),
            'promedio_por_instructor': round(stats['total'] / len(instructores), 1) if instructores else 0,
            'primera_evaluacion': min(fechas) if fechas else None,
            'ultima_evaluacion': max(fechas) if fechas else None,
            'dias_entre_evaluaciones': (max(fechas) - min(fechas)).days if len(fechas) >= 2 else 0,
        },
    }
