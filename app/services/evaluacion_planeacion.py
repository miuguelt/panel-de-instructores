"""Seguimiento de juicios emitidos por aprendiz, RAP y tramo de planeación."""

from datetime import date, datetime

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
        fecha_fin = competencia.get('fecha_plan_fin')
        fecha_limite = fecha_fin.strftime('%d/%m/%Y') if fecha_fin else None
        catalogo[identificador] = {
            'nombre': competencia['nombre'], 'fase': competencia.get('fase') or '',
            'periodo': competencia.get('etiqueta_trimestre') or '',
            'fecha_limite': fecha_limite,
            'resumen': resumen, 'resultados': resultados, 'aprendices': filas,
        }
    return catalogo


def analizar_competencias_vencidas(linea, hoy=None):
    """Identifica qué competencias ya debieron evaluarse según su fecha planeada."""
    hoy = hoy or date.today()
    if not linea or not linea.get('competencias'):
        return {
            'competencias': [],
            'items': [],
            'total_deberian_evaluarse': 0,
            'con_pendientes': 0,
            'al_dia': 0,
            'total_aprendices_pendientes': 0,
        }

    items = []
    for competencia in linea['competencias']:
        fecha_fin = competencia.get('fecha_plan_fin')
        if not fecha_fin or fecha_fin > hoy:
            continue

        resumen = competencia.get('evaluacion_resumen') or {
            'total': 0, 'evaluados': 0, 'pendientes': 0,
            'parciales': 0, 'sin_evaluar': 0, 'aprobados': 0,
            'evaluaciones_pendientes': 0,
        }
        total_aprendices = resumen.get('total', 0)
        pendientes = resumen.get('pendientes', 0)
        evaluados = resumen.get('evaluados', 0)
        dias_vencida = max((hoy - fecha_fin).days, 0)
        esta_al_dia = (pendientes == 0 and total_aprendices > 0)
        pct_evaluado = round((evaluados / total_aprendices) * 100) if total_aprendices else 0

        if total_aprendices == 0:
            estado_eval = 'Sin aprendices'
            tono_eval = 'neutral'
        elif esta_al_dia:
            estado_eval = 'Evaluada al 100%'
            tono_eval = 'success'
        elif evaluados > 0:
            estado_eval = f'{pendientes} pendientes ({pct_evaluado}% evaluado)'
            tono_eval = 'warning'
        else:
            estado_eval = f'{pendientes} sin evaluar (0%)'
            tono_eval = 'danger'

        items.append({
            'nombre': competencia['nombre'],
            'fase': competencia.get('fase') or 'Sin fase',
            'etiqueta_trimestre': competencia.get('etiqueta_trimestre') or '',
            'fecha_debio_evaluarse': fecha_fin,
            'fecha_debio_evaluarse_str': fecha_fin.strftime('%d/%m/%Y'),
            'dias_vencida': dias_vencida,
            'total_aprendices': total_aprendices,
            'aprendices_evaluados': evaluados,
            'aprendices_pendientes': pendientes,
            'parciales': resumen.get('parciales', 0),
            'sin_evaluar': resumen.get('sin_evaluar', 0),
            'evaluaciones_pendientes': resumen.get('evaluaciones_pendientes', 0),
            'porcentaje_evaluado': pct_evaluado,
            'esta_al_dia': esta_al_dia,
            'estado_eval': estado_eval,
            'tono_eval': tono_eval,
            'resultados_total': competencia.get('resultados_total') or len(competencia.get('resultados', [])),
            'seguimiento_id': competencia.get('seguimiento_id'),
            'instructores': competencia.get('instructores', []),
            'exigible': competencia.get('exigible', True),
        })

    items.sort(key=lambda x: (
        1 if x['esta_al_dia'] else 0,
        x['fecha_debio_evaluarse'],
        x['nombre'],
    ))

    con_pendientes = sum(1 for x in items if not x['esta_al_dia'] and x['total_aprendices'] > 0)
    al_dia = sum(1 for x in items if x['esta_al_dia'])
    total_aprendices_pendientes = sum(x['aprendices_pendientes'] for x in items)

    return {
        'competencias': items,
        'items': items,
        'total_deberian_evaluarse': len(items),
        'con_pendientes': con_pendientes,
        'al_dia': al_dia,
        'total_aprendices_pendientes': total_aprendices_pendientes,
    }

