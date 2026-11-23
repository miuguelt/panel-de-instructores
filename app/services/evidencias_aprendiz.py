"""Estado y plazo de las evidencias del aprendiz.

Reglas puras que antes vivían dentro de la ruta del panel: qué estado tiene
cada evidencia, cuánto falta para su plazo y cómo se anuncia ese tiempo.
"""

from datetime import datetime

from app.models.alertas import PlanMejoramiento
from app.models.tarea import Entrega, ProrrogaTarea, Tarea

DIA = 24 * 60 * 60
HORA = 60 * 60


def _plural(n, singular, plural):
    return f"{n} {singular if n == 1 else plural}"


def texto_duracion(segundos):
    """Duración legible: días y horas, horas y minutos, o minutos."""
    if segundos >= DIA:
        dias, horas = int(segundos // DIA), int((segundos % DIA) // HORA)
        texto = _plural(dias, 'día', 'días')
        return texto + (f" y {_plural(horas, 'hora', 'horas')}" if horas else '')
    if segundos >= HORA:
        horas, minutos = int(segundos // HORA), int((segundos % HORA) // 60)
        texto = _plural(horas, 'hora', 'horas')
        return texto + (f" y {_plural(minutos, 'minuto', 'minutos')}" if minutos else '')
    return _plural(max(1, int((segundos + 59) // 60)), 'minuto', 'minutos')


def estado_evidencia_tarea(entrega, limite, ahora):
    """pendiente, vencida, correccion, entregada o retraso."""
    if not entrega:
        return 'vencida' if limite and limite < ahora else 'pendiente'
    if entrega.estado_revision == 'rechazada':
        return 'correccion'
    if entrega.registrada_por_instructor or not limite or entrega.fecha_entrega <= limite:
        return 'entregada'
    return 'retraso'


def plazo_evidencia(tarea, entrega, estado, limite, ahora):
    """(progreso del plazo en %, clase visual, texto del tiempo) de una evidencia."""
    if not limite:
        return None, None, None
    restantes = (limite - ahora).total_seconds()
    if restantes > 0:
        clase = 'urgent' if restantes <= DIA else ('soon' if restantes <= 3 * DIA else 'normal')
        texto = 'Quedan ' + texto_duracion(restantes)
    else:
        clase = 'overdue'
        texto = 'Plazo vencido hace ' + texto_duracion(abs(restantes))
    entregada = bool(entrega) and estado in ('entregada', 'retraso')
    duracion = (limite - tarea.creada_en).total_seconds() if tarea.creada_en else 0
    if entregada:
        return (100 if duracion > 0 else None), 'complete', 'Evidencia entregada'
    if duracion > 0:
        progreso = max(0, min(100, round((ahora - tarea.creada_en).total_seconds() / duracion * 100)))
        return progreso, clase, texto
    return None, clase, texto


def tareas_del_aprendiz(ficha_id, aprendiz_id, ahora=None, tareas=None):
    """Evidencias individuales del aprendiz con su entrega, prórroga, plan, estado y plazo.

    Entregas, prórrogas y planes se cargan en tres consultas agregadas para no
    disparar una consulta por tarea. ``tareas`` permite pasar una lista ya
    filtrada (por ejemplo, solo las del instructor que consulta).
    """
    ahora = ahora or datetime.utcnow()
    if tareas is None:
        tareas = Tarea.query.filter_by(ficha_id=ficha_id).order_by(Tarea.fecha_limite).all()
    entregas, prorrogas, planes = {}, {}, {}
    if tareas:
        ids = [t.id for t in tareas]
        for entrega in (Entrega.query.filter(Entrega.aprendiz_id == aprendiz_id, Entrega.tarea_id.in_(ids))
                        .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc()).all()):
            entregas.setdefault(entrega.tarea_id, entrega)
        for prorroga in ProrrogaTarea.query.filter(ProrrogaTarea.aprendiz_id == aprendiz_id,
                                                   ProrrogaTarea.tarea_id.in_(ids)).all():
            prorrogas[prorroga.tarea_id] = prorroga
        for plan in (PlanMejoramiento.query.filter(PlanMejoramiento.aprendiz_id == aprendiz_id,
                                                   PlanMejoramiento.tarea_id.in_(ids))
                     .order_by(PlanMejoramiento.fecha_creacion.desc()).all()):
            planes.setdefault(plan.tarea_id, plan)

    resultado = []
    for tarea in tareas:
        if tarea.es_grupal:
            continue
        entrega, prorroga = entregas.get(tarea.id), prorrogas.get(tarea.id)
        limite = prorroga.nueva_fecha_limite if prorroga and prorroga.nueva_fecha_limite else tarea.fecha_limite
        estado = estado_evidencia_tarea(entrega, limite, ahora)
        progreso, clase, texto = plazo_evidencia(tarea, entrega, estado, limite, ahora)
        resultado.append({
            'tarea': tarea, 'entrega': entrega, 'estado': estado, 'prorroga': prorroga,
            'plan': planes.get(tarea.id), 'limite_efectivo': limite,
            'progreso_plazo': progreso, 'clase_plazo': clase, 'texto_tiempo_plazo': texto,
        })
    return resultado


def saludo_por_hora(hora):
    """Saludo según la hora de Colombia."""
    if 5 <= hora < 12:
        return '¡Buenos días'
    if 12 <= hora < 19:
        return '¡Buenas tardes'
    return '¡Buenas noches'
