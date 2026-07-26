from flask_login import current_user

from app.models.ficha_instructor import FichaInstructor
from app.models.tarea import Tarea


def puede_gestionar_ficha(ficha):
    """Permite al dueño, a un colaborador vinculado o a un administrador operar la ficha."""
    if not ficha or not current_user.is_authenticated:
        return False
    if current_user.es_admin or ficha.instructor_id == current_user.id:
        return True
    return FichaInstructor.query.filter_by(
        ficha_id=ficha.id, instructor_id=current_user.id
    ).first() is not None


def tareas_visibles(ficha_id):
    """Devuelve solo las tareas que el usuario puede consultar en una ficha."""
    consulta = Tarea.query.filter_by(ficha_id=ficha_id)
    if not current_user.es_admin:
        consulta = consulta.filter(Tarea.instructor_id == current_user.id)
    return consulta


def puede_gestionar_tarea(tarea):
    """El administrador ve todas; cada instructor gestiona solo sus tareas."""
    if not tarea or not current_user.is_authenticated:
        return False
    return current_user.es_admin or tarea.instructor_id == current_user.id
