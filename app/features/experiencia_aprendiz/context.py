"""Proyección del recorrido a partir de entregas y juicios persistidos."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone


COLOMBIA = timezone(timedelta(hours=-5))
HITOS = {
    'primera_entrega': ('Primer paso', 'Guardaste tu primera evidencia digital.'),
    'cinco_entregas': ('Cinco pasos', 'Ya registraste cinco evidencias digitales.'),
    'diez_entregas': ('Avance sostenido', 'Ya registraste diez evidencias digitales.'),
    'veinte_entregas': ('Camino construido', 'Ya registraste veinte evidencias digitales.'),
}


def fecha_colombiana(fecha):
    """Las fechas SQL sin zona representan UTC, igual que las fechas conscientes."""
    return (fecha.replace(tzinfo=timezone.utc) if fecha.tzinfo is None else fecha).astimezone(COLOMBIA)


def porcentaje(valor, total):
    return min(100, max(0, int(valor / total * 100 + 0.5))) if total else 0


def estado_evidencia(item):
    """Separa la recepción del archivo de la revisión y del juicio oficial."""
    entrega = item.get('entrega')
    aula = item['tarea'].es_actividad_clase
    if entrega is None:
        if aula:
            return {'status': 'class', 'title': 'Actividad en clase',
                    'help': 'Consulta las indicaciones. Tu instructor registra el cumplimiento en el aula.'}
        if item['estado'] == 'vencida':
            return {'status': 'pending', 'title': 'Plazo vencido',
                    'help': 'Consulta las opciones de entrega y, si necesitas orientación, habla con tu instructor.'}
        return {'status': 'pending', 'title': 'Por entregar',
                'help': 'Prepara tu archivo o enlace y envíalo desde esta actividad.'}
    if entrega.estado_revision == 'rechazada':
        return {'status': 'changes', 'title': 'Requiere ajustes',
                'help': 'Lee los comentarios y vuelve a enviar tu evidencia con los ajustes solicitados.'}
    if aula or entrega.registrada_por_instructor:
        return {'status': 'class', 'title': 'Cumplimiento en clase',
                'help': 'Tu instructor registró esta actividad. No requiere una entrega digital.'}
    if entrega.estado_revision == 'aprobada':
        return {'status': 'approved', 'title': 'Revisión aprobada',
                'help': 'Consulta los comentarios de revisión. El juicio oficial se consulta en Juicios.'}
    return {'status': 'review', 'title': 'Recibida · En revisión',
            'help': 'Tu evidencia quedó registrada. Puedes consultar o editar la entrega mientras esperas la revisión.'}


def siguiente_accion(tareas, trabajos):
    """Una corrección precede pendientes; el plazo efectivo ordena las actividades."""
    pendientes = [(item, 'evidencias') for item in tareas
                  if item['estado'] in ('pendiente', 'correccion', 'vencida')]
    pendientes.extend((item, 'grupo') for item in trabajos
                      if item['estado'] in ('pendiente', 'correccion', 'vencida'))
    if pendientes:
        item, tab = min(pendientes, key=lambda par: (
            0 if par[0]['estado'] == 'correccion' else 1,
            fecha_colombiana(par[0]['limite_efectivo']).timestamp()
            if par[0].get('limite_efectivo') else float('inf'), par[0]['tarea'].id,
        ))
        aula = item['tarea'].es_actividad_clase
        if item['estado'] == 'correccion':
            motivo = 'Revisa los comentarios de tu instructor y prepara los ajustes solicitados.'
            boton = 'Revisar ajustes'
        elif aula:
            motivo = 'Consulta las indicaciones y prepara la actividad con tu instructor en clase.'
            boton = 'Consultar actividad'
        else:
            motivo = 'Continúa con esta evidencia y envía tu archivo o enlace.'
            boton = 'Preparar evidencia'
        if item.get('limite_efectivo'):
            motivo += ' Fecha límite: ' + fecha_colombiana(item['limite_efectivo']).strftime('%d/%m/%Y %H:%M') + '.'
        return {'title': item['tarea'].titulo, 'reason': motivo, 'tab': tab,
                'taskId': item['tarea'].id if tab == 'evidencias' else None, 'button': boton}
    for item in reversed(tareas):
        entrega = item.get('entrega')
        if entrega and entrega.feedback and entrega.estado_revision in ('aprobada', 'rechazada'):
            return {'title': item['tarea'].titulo, 'reason': 'Tu instructor dejó comentarios. Revísalos para orientar tu próximo avance.',
                    'tab': 'evidencias', 'taskId': item['tarea'].id, 'button': 'Leer comentarios'}
    for item in tareas:
        if estado_evidencia(item)['status'] == 'review':
            return {'title': item['tarea'].titulo, 'reason': 'Tu evidencia quedó recibida y está pendiente de revisión.',
                    'tab': 'evidencias', 'taskId': item['tarea'].id, 'button': 'Consultar entrega'}
    return {'title': 'Consulta tu recorrido de formación',
            'reason': 'Revisa tus resultados de aprendizaje y acuerda tu siguiente avance con el instructor.',
            'tab': 'juicios', 'taskId': None, 'button': 'Consultar resultados'}


def construir_experiencia(tareas, trabajos, stats, competencias, grupo, preferencias,
                         revision, hitos, ahora=None):
    """Genera datos serializables sin consultar ni alterar el estado académico."""
    ahora = fecha_colombiana(ahora or datetime.now(timezone.utc))
    lunes = ahora.date() - timedelta(days=ahora.weekday())
    domingo = lunes + timedelta(days=6)
    digitales = [item for item in tareas if not item['tarea'].es_actividad_clase]
    semana = 0
    evidencias = {'submitted': 0, 'review': 0, 'changes': 0, 'approved': 0}
    for item in digitales:
        entrega = item.get('entrega')
        if not entrega or entrega.registrada_por_instructor:
            continue
        evidencias['submitted'] += 1
        estado = estado_evidencia(item)['status']
        evidencias[estado] += 1
        if entrega.fecha_entrega:
            fecha = fecha_colombiana(entrega.fecha_entrega)
            if lunes <= fecha.date() <= domingo and fecha <= ahora:
                semana += 1
    preferencias = deepcopy(preferencias)
    resume = preferencias['resume']
    if resume and resume['taskId'] is not None and resume['taskId'] not in {item['tarea'].id for item in tareas}:
        preferencias['resume'] = None
    equipo = None
    if grupo:
        propios = [item for item in trabajos if item['grupo'].id == grupo.id]
        if propios:
            completados = sum(item['estado'] in ('entregada', 'retraso') for item in propios)
            equipo = {'name': grupo.nombre, 'completed': completados, 'total': len(propios),
                      'pct': porcentaje(completados, len(propios))}
    return {
        'ok': True,
        'preferences': preferencias, 'revision': revision,
        'next_action': siguiente_accion(tareas, trabajos),
        'weekly': {'count': semana, 'target': preferencias['weeklyGoal'],
                   'percent': porcentaje(semana, preferencias['weeklyGoal']),
                   'start': lunes.isoformat(), 'end': domingo.isoformat()},
        'progress': {'approved': stats['aprobados'], 'total': stats['total'],
                     'pct': porcentaje(stats['aprobados'], stats['total'])},
        'evidence': evidencias, 'team': equipo,
        'milestones': [{'title': HITOS[hito][0], 'description': HITOS[hito][1]}
                       for hito in HITOS if hito in hitos],
        'competencies': [{'name': comp['nombre'], 'approved': comp['aprobados'],
                          'total': comp['total'], 'pct': porcentaje(comp['aprobados'], comp['total'])}
                         for comp in competencias],
    }
