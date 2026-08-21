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


def tareas_visibles(ficha_id, corte_id=None, ver_todas=False, instructor_id=None):
    """Devuelve solo las tareas que el usuario puede consultar en una ficha."""
    consulta = Tarea.query.filter_by(ficha_id=ficha_id)
    if corte_id is not None:
        consulta = consulta.filter(Tarea.corte_id == corte_id)
    if instructor_id is not None:
        consulta = consulta.filter(Tarea.instructor_id == instructor_id)
    elif not current_user.es_admin and not ver_todas:
        # Al consultar un corte concreto, todos los instructores autorizados
        # pueden ver el contenido compartido; la edición sigue restringida al
        # creador mediante puede_gestionar_tarea().
        if corte_id is None:
            consulta = consulta.filter(Tarea.instructor_id == current_user.id)
    return consulta


def puede_gestionar_tarea(tarea):
    """El administrador ve todas; cada instructor gestiona solo sus tareas."""
    if not tarea or not current_user.is_authenticated:
        return False
    if tarea.corte and not tarea.corte.esta_activo:
        return False
    return current_user.es_admin or tarea.instructor_id == current_user.id


def puede_ver_tarea(tarea):
    """Permite consultar una tarea compartida sin conceder permisos de edición."""
    if not tarea or not current_user.is_authenticated:
        return False
    if puede_gestionar_tarea(tarea):
        return True
    return bool(tarea.corte and tarea.corte.compartido and puede_gestionar_ficha(tarea.ficha))


def puede_gestionar_corte(corte):
    """Solo el creador o un administrador modifica datos de un corte activo."""
    if not corte or not current_user.is_authenticated:
        return False
    if not corte.esta_activo:
        return False
    return current_user.es_admin or corte.instructor_id == current_user.id


def puede_administrar_corte(corte):
    """Permite al responsable cambiar el estado del corte."""
    if not corte or not current_user.is_authenticated:
        return False
    return current_user.es_admin or corte.instructor_id == current_user.id
