"""Persistencia de experiencia y unión permanente de hitos obtenidos por entregas."""

from copy import deepcopy

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import db
from app.features.experiencia_aprendiz.models import ExperienciaAprendiz
from app.features.personalizacion_aprendiz.service import ConflictoPersonalizacion, validar_revision
from app.models.tarea import Tarea


DEFAULTS = {
    'weeklyGoal': 2, 'notificationMode': 'all', 'rankingVisible': True,
    'reducedMotion': False, 'density': 'comfortable', 'resume': None,
}
TABS = {'resumen', 'evidencias', 'grupo', 'juicios', 'rendimiento', 'convivencia'}
HITOS = (
    (1, 'primera_entrega'), (5, 'cinco_entregas'),
    (10, 'diez_entregas'), (20, 'veinte_entregas'),
)


def validar_preferencias(preferencias, ficha_id):
    """Valida tipos exactos y limita la reanudación a tareas individuales de la ficha."""
    if not isinstance(preferencias, dict) or set(preferencias) != set(DEFAULTS):
        raise ValueError('Envía únicamente las seis preferencias de experiencia del panel.')
    meta = preferencias['weeklyGoal']
    if type(meta) is not int or not 0 <= meta <= 20:
        raise ValueError('La meta semanal debe ser un número entero entre 0 y 20; 0 la desactiva.')
    modo = preferencias['notificationMode']
    if not isinstance(modo, str) or modo not in ('all', 'important', 'quiet'):
        raise ValueError('Elige todas las notificaciones, solo las importantes o el modo silencioso.')
    if type(preferencias['rankingVisible']) is not bool or type(preferencias['reducedMotion']) is not bool:
        raise ValueError('Las opciones de clasificación y movimiento deben estar activadas o desactivadas.')
    densidad = preferencias['density']
    if not isinstance(densidad, str) or densidad not in ('comfortable', 'compact'):
        raise ValueError('Elige una presentación cómoda o compacta para el panel.')
    resume = preferencias['resume']
    if resume is not None:
        if (not isinstance(resume, dict) or set(resume) != {'tab', 'taskId'}
                or not isinstance(resume['tab'], str) or resume['tab'] not in TABS):
            raise ValueError('El punto de reanudación debe indicar una sección disponible del panel.')
        tarea_id = resume['taskId']
        if tarea_id is not None:
            if type(tarea_id) is not int or not 1 <= tarea_id <= 2_147_483_647 or resume['tab'] != 'evidencias':
                raise ValueError('Para reanudar una tarea individual, selecciona la sección Evidencias.')
            tarea = db.session.get(Tarea, tarea_id)
            if tarea is None or tarea.ficha_id != ficha_id or tarea.es_grupal:
                raise ValueError('La tarea para reanudar debe ser individual y pertenecer a tu ficha.')
    return deepcopy(preferencias)


def leer_experiencia(aprendiz_id):
    """La lectura devuelve un estado independiente y no crea preferencias ni hitos."""
    registro = db.session.get(ExperienciaAprendiz, aprendiz_id, populate_existing=True)
    return {
        'preferences': deepcopy(registro.preferences if registro else DEFAULTS),
        'revision': registro.revision if registro else 0,
    }


def guardar_experiencia(aprendiz_id, preferences, revision, ficha_id):
    """Guarda preferencias completas con CAS y sin cambiar los hitos ya obtenidos."""
    try:
        preferencias = validar_preferencias(preferences, ficha_id)
        if type(revision) is not int:
            raise ValueError('La revisión del panel debe ser un número entero. Recarga la página.')
        revision = validar_revision(str(revision))
        if revision == 0:
            registro = ExperienciaAprendiz(
                aprendiz_id=aprendiz_id, preferences=preferencias, revision=1, logros=[],
            )
            db.session.add(registro)
            try:
                db.session.commit()
            except IntegrityError as exc:
                db.session.rollback()
                if db.session.get(ExperienciaAprendiz, aprendiz_id) is not None:
                    raise ConflictoPersonalizacion(
                        'Tu experiencia cambió en otra sesión. Recarga las preferencias antes de guardar.'
                    ) from exc
                raise
        else:
            resultado = db.session.execute(
                update(ExperienciaAprendiz)
                .where(ExperienciaAprendiz.aprendiz_id == aprendiz_id,
                       ExperienciaAprendiz.revision == revision)
                .values(preferences=preferencias, revision=revision + 1),
            )
            if resultado.rowcount != 1:
                db.session.rollback()
                raise ConflictoPersonalizacion(
                    'Tu experiencia cambió en otra sesión. Recarga las preferencias antes de guardar.'
                )
            db.session.commit()
        return leer_experiencia(aprendiz_id)
    except SQLAlchemyError:
        db.session.rollback()
        raise


def registrar_hitos(aprendiz_id, total_entregadas):
    """Conserva hitos logrados aunque el conteo cambie, sin subir la revisión del panel."""
    if type(total_entregadas) is not int or total_entregadas < 0:
        raise ValueError('El total de entregas debe ser un número entero mayor o igual a cero.')
    obtenidos = {nombre for limite, nombre in HITOS if total_entregadas >= limite}
    try:
        while True:
            registro = db.session.get(ExperienciaAprendiz, aprendiz_id, populate_existing=True)
            anteriores = registro.logros if registro else []
            conservados = set(anteriores) | obtenidos
            nuevos = [nombre for _limite, nombre in HITOS if nombre in conservados]
            if nuevos == anteriores:
                return list(anteriores)
            if registro is None:
                db.session.add(ExperienciaAprendiz(
                    aprendiz_id=aprendiz_id, preferences=deepcopy(DEFAULTS), revision=1, logros=nuevos,
                ))
                try:
                    db.session.commit()
                    return nuevos
                except IntegrityError:
                    db.session.rollback()
                    if db.session.get(ExperienciaAprendiz, aprendiz_id) is None:
                        raise
                    continue
            resultado = db.session.execute(
                update(ExperienciaAprendiz)
                .where(ExperienciaAprendiz.aprendiz_id == aprendiz_id,
                       ExperienciaAprendiz.logros == anteriores)
                .values(logros=nuevos)
                .execution_options(synchronize_session=False),
            )
            if resultado.rowcount != 1:
                db.session.rollback()
                continue
            db.session.commit()
            return nuevos
    except SQLAlchemyError:
        db.session.rollback()
        raise
