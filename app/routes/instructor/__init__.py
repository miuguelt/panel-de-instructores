from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, flash
from flask_login import current_user
from sqlalchemy import or_

from app import db
from app.models.ficha import Ficha
from app.models.ficha_instructor import FichaInstructor
from app.services.alertas import actualizar_alertas_ficha
from app.services.aseo import ajustar_turno_por_asistencia  # noqa: F401 (los módulos lo usan vía _pkg)
from app.services.importacion_ficha import importar_archivo  # noqa: F401 (los módulos lo usan vía _pkg)
from app.services.ranking import actualizar_participacion_ficha
from app.services.versiones_archivos import crear_version  # noqa: F401 (los módulos lo usan vía _pkg)

instructor_bp = Blueprint(
    'instructor',
    __name__,
    template_folder='../../templates/instructor',
)

ESTADOS_FALTA = ('FALTA', 'FALTA_JUSTIFICADA', 'EXCUSA_MEDICA')
MAX_LONGITUD_CALIFICACION = 10
ZONA_HORARIA_BOGOTA = ZoneInfo('America/Bogota')


def _validar_calificacion(valor, obligatoria=False):
    """Normaliza una nota y valida el límite definido por ``Entrega``."""
    calificacion = (valor or '').strip()
    if obligatoria and not calificacion:
        return None, 'La nota es obligatoria.'
    if len(calificacion) > MAX_LONGITUD_CALIFICACION:
        return None, f'La nota no puede superar {MAX_LONGITUD_CALIFICACION} caracteres.'
    return calificacion or None, None


def _actualizar_resumenes_despues_de_evaluar(ficha_id):
    """Ejecuta cálculos secundarios sin convertirlos en un fallo de la evaluación."""
    errores = []
    for nombre, funcion in (
        ('alertas', actualizar_alertas_ficha),
        ('ranking', actualizar_participacion_ficha),
    ):
        try:
            funcion(ficha_id)
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                'La evaluación quedó guardada, pero falló la actualización de %s para ficha %s.',
                nombre,
                ficha_id,
            )
            errores.append(nombre)
    return errores


# El semáforo de riesgo vive en el servicio para que Alertas, Asistencia y la
# Visión general muestren el mismo nivel para cada aprendiz.
from app.services.resumen_ficha import (  # noqa: E402, F401
    _faltas_por_aprendiz,
    _ultima_entrega_por_aprendiz,
    calcular_semaforo,
)


def obtener_fichas():
    if current_user.es_admin:
        return Ficha.query.order_by(Ficha.codigo).all()
    return Ficha.query.outerjoin(FichaInstructor, FichaInstructor.ficha_id == Ficha.id).filter(
        or_(Ficha.instructor_id == current_user.id,
               FichaInstructor.instructor_id == current_user.id)
    ).distinct().order_by(Ficha.codigo).all()


def _actualizar_indicadores_carga(ficha_id, corte_id=None):
    """Actualiza derivados sin invalidar una carga ya confirmada."""
    fallo = False
    try:
        actualizar_alertas_ficha(ficha_id)
    except Exception:
        db.session.rollback()
        fallo = True
        current_app.logger.exception('La carga quedó guardada, pero falló la actualización de alertas.')
    try:
        actualizar_participacion_ficha(ficha_id, corte_id=corte_id)
    except Exception:
        db.session.rollback()
        fallo = True
        current_app.logger.exception('La carga quedó guardada, pero falló la actualización del ranking.')
    if fallo:
        flash('La carga quedó guardada, pero no fue posible actualizar todos los indicadores. Recargue la página más tarde.', 'warning')


from . import (  # noqa: E402, F401
    actividades_evidencias,
    alertas_materiales,
    aprendices,
    asistencia,
    asistencia_reporte,
    competencias,
    dashboard,
    entregas,
    estadisticas,
    fichas,
    fichas_carga,
    historial_aprendiz,
    juicios,
    observador,
    tareas,
)
