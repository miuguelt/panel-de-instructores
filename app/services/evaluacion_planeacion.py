"""Seguimiento de juicios emitidos por aprendiz, RAP y tramo de planeación."""

from datetime import datetime

from app.services.emparejamiento_juicios import clave_resultado, texto_limpio


def evaluar_resultado(aprendices, juicios):
    """Cuenta personas; los registros administrativos no son evaluaciones."""
    vigentes = {}
    for juicio in juicios:
        estado = clave_resultado(juicio.juicio)
        if estado not in {'aprobado', 'aprobada', 'no aprobado', 'no aprobada', 'a', 'na'}:
            continue
        orden = (juicio.fecha_juicio or datetime.min, juicio.id or 0)
        anterior = vigentes.get(juicio.aprendiz_id)
        if anterior is None or orden > (anterior.fecha_juicio or datetime.min, anterior.id or 0):
            vigentes[juicio.aprendiz_id] = juicio

    filas = []
    for aprendiz in aprendices:
        juicio = vigentes.get(aprendiz.id)
        aprobado = bool(juicio and clave_resultado(juicio.juicio) in {'aprobado', 'aprobada', 'a'})
        filas.append({
            'id': aprendiz.id, 'nombre': aprendiz.nombre_completo,
            'documento': aprendiz.documento,
            'estado': 'evaluado' if juicio else 'pendiente',
            'aprobado': aprobado,
            'juicio': ('Aprobado (A)' if aprobado else 'No aprobado (NA)') if juicio else 'Por evaluar',
            'instructor': (texto_limpio(juicio.funcionario_registro) or 'No registrado') if juicio else None,
            'fecha': juicio.fecha_juicio.strftime('%d/%m/%Y') if juicio and juicio.fecha_juicio else None,
        })
    filas.sort(key=lambda fila: (clave_resultado(fila['nombre']), fila['documento']))
    evaluados = sum(fila['estado'] == 'evaluado' for fila in filas)
    return {'aprendices': filas, 'resumen': {
        'total': len(filas), 'evaluados': evaluados, 'pendientes': len(filas) - evaluados,
        'aprobados': sum(fila['aprobado'] for fila in filas),
    }}


def construir_seguimiento(linea):
    """Conserva cada tramo y sus RAP; una persona se cuenta una sola vez."""
    catalogo = {}
    for indice, competencia in enumerate(linea['competencias']):
        resultados = []
        personas = {}
        for numero, resultado in enumerate(competencia.get('resultados', [])):
            evaluacion = resultado.get('evaluacion') or {'aprendices': [], 'resumen': {
                'total': 0, 'evaluados': 0, 'pendientes': 0, 'aprobados': 0}}
            resultados.append({
                'id': str(numero), 'nombre': resultado.get('rap') or 'Resultado sin denominación',
                'codigo': resultado.get('rap_codigo') or '',
                'actividad': resultado.get('actividad') or '',
                'instructores_planeados': resultado.get('instructores') or [],
                **evaluacion,
            })
            for fila in evaluacion['aprendices']:
                persona = personas.setdefault(fila['id'], {
                    'id': fila['id'], 'nombre': fila['nombre'], 'documento': fila['documento'],
                    'resultados': [],
                })
                persona['resultados'].append({'rap_id': str(numero), **fila})

        filas = list(personas.values())
        for persona in filas:
            evaluados = sum(fila['estado'] == 'evaluado' for fila in persona['resultados'])
            persona['evaluados'] = evaluados
            persona['total'] = len(resultados)
            persona['estado'] = 'evaluado' if evaluados == len(resultados) else ('parcial' if evaluados else 'pendiente')
            persona['aprobado'] = all(fila['aprobado'] for fila in persona['resultados'])
        filas.sort(key=lambda fila: (clave_resultado(fila['nombre']), fila['documento']))
        evaluados = sum(fila['estado'] == 'evaluado' for fila in filas)
        resumen = {
            'total': len(filas), 'evaluados': evaluados, 'pendientes': len(filas) - evaluados,
            'parciales': sum(fila['estado'] == 'parcial' for fila in filas),
            'sin_evaluar': sum(fila['estado'] == 'pendiente' for fila in filas),
            'aprobados': sum(fila['aprobado'] for fila in filas),
            'evaluaciones_pendientes': sum(fila['total'] - fila['evaluados'] for fila in filas),
        }
        identificador = f'tramo-{indice}'
        competencia['seguimiento_id'] = identificador
        competencia['evaluacion_resumen'] = resumen
        catalogo[identificador] = {
            'nombre': competencia['nombre'], 'fase': competencia.get('fase') or '',
            'periodo': competencia.get('etiqueta_trimestre') or '',
            'resumen': resumen, 'resultados': resultados, 'aprendices': filas,
        }
    return catalogo
