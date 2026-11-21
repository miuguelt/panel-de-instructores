"""Métricas de la cabecera del módulo de tareas.

Separa los plazos en grupos exclusivos para dibujarlos en una sola barra
apilada y cuenta las entregas que esperan calificación, que es la acción
principal del instructor en este módulo.
"""

from sqlalchemy import func, or_

from app import db
from app.models.aprendiz import ESTADOS_EN_FORMACION, Aprendiz
from app.models.tarea import MODALIDAD_EVIDENCIA, Entrega, Tarea

GRUPOS_PLAZO = (
    ('en_plazo', 'En plazo', 'success', ('normal', 'atencion')),
    ('por_vencer', 'Vencen en menos de 24 h', 'warning', ('urgente',)),
    ('vencidas', 'Vencidas', 'danger', ('vencida',)),
    ('sin_limite', 'Sin fecha límite', 'neutral', ('sin_limite',)),
)


def resumir_plazos(tareas):
    """Conteo exclusivo por plazo y segmentos ``(etiqueta, valor, tono)``."""
    conteo = {clave: 0 for clave, *_ in GRUPOS_PLAZO}
    for tarea in tareas:
        estado = tarea.progreso_tiempo['estado']
        for clave, _, _, estados in GRUPOS_PLAZO:
            if estado in estados:
                conteo[clave] += 1
                break
    segmentos = [(etiqueta, conteo[clave], tono) for clave, etiqueta, tono, _ in GRUPOS_PLAZO]
    return {'total': len(tareas), 'conteo': conteo, 'segmentos': segmentos}


def contar_por_calificar(tarea_ids):
    """Entregas de evidencias sin calificar de aprendices en formación."""
    if not tarea_ids:
        return 0
    return (
        db.session.query(func.count(Entrega.id))
        .join(Tarea, Entrega.tarea_id == Tarea.id)
        .join(Aprendiz, Entrega.aprendiz_id == Aprendiz.id)
        .filter(
            Tarea.id.in_(list(tarea_ids)),
            Tarea.modalidad == MODALIDAD_EVIDENCIA,
            or_(Entrega.calificada.is_(False), Entrega.estado_revision == 'pendiente'),
            Aprendiz.estado.in_(ESTADOS_EN_FORMACION),
        )
        .scalar()
    ) or 0
