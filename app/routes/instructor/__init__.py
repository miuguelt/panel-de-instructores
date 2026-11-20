from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, flash
from flask_login import current_user
from sqlalchemy import func, or_

from app import db
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.models.ficha import Ficha
from app.models.ficha_instructor import FichaInstructor
from app.models.tarea import Entrega
from app.services.alertas import actualizar_alertas_ficha
from app.services.aseo import ajustar_turno_por_asistencia
from app.services.asistencia import contar_sesiones_registradas
from app.services.importacion_ficha import importar_archivo
from app.services.permisos import tareas_visibles
from app.services.ranking import actualizar_participacion_ficha
from app.services.trabajos_grupales import obtener_destinatarios_y_entregas_grupales
from app.services.versiones_archivos import crear_version

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


def _faltas_por_aprendiz(ficha_id, corte_id=None):
    """Cuenta faltas por aprendiz y estado en una sola consulta agregada.

    Devuelve ``{aprendiz_id: {estado: cantidad}}``. Antes cada aprendiz costaba
    dos COUNT independientes, asi que una ficha de 30 aprendices emitia 60
    consultas solo para pintar el semaforo.
    """
    consulta = (
        db.session.query(
            RegistroAsistencia.aprendiz_id,
            RegistroAsistencia.estado,
            func.count(RegistroAsistencia.id),
        )
        .join(SesionAsistencia, RegistroAsistencia.sesion_id == SesionAsistencia.id)
        .filter(
            SesionAsistencia.ficha_id == ficha_id,
            RegistroAsistencia.estado.in_(ESTADOS_FALTA),
        )
    )
    if corte_id is not None:
        consulta = consulta.filter(SesionAsistencia.corte_id == corte_id)
    filas = consulta.group_by(RegistroAsistencia.aprendiz_id, RegistroAsistencia.estado).all()
    conteo = {}
    for aprendiz_id, estado, cantidad in filas:
        conteo.setdefault(aprendiz_id, {})[estado] = cantidad
    return conteo


def _ultima_entrega_por_aprendiz(tareas):
    """Mapa ``{(tarea_id, aprendiz_id): entrega mas reciente}`` en una consulta."""
    ids_tareas = [t.id for t in tareas]
    if not ids_tareas:
        return {}
    entregas = (
        Entrega.query
        .filter(Entrega.tarea_id.in_(ids_tareas))
        .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
        .all()
    )
    ultimas = {}
    for entrega in entregas:
        ultimas.setdefault((entrega.tarea_id, entrega.aprendiz_id), entrega)
    return ultimas


def calcular_semaforo(ficha_id, aprendices, config, ahora=None, corte_id=None):
    """Nivel de riesgo, faltas y tareas pendientes de cada aprendiz de la ficha.

    Las vistas de asistencia y de alertas mostraban el mismo semaforo
    resolviendolo aprendiz por aprendiz (dos COUNT mas un SELECT por tarea).
    Aqui se resuelve con tres consultas para toda la ficha.
    """
    ahora = ahora or datetime.utcnow()
    total_sesiones = contar_sesiones_registradas(ficha_id, corte_id=corte_id)
    faltas = _faltas_por_aprendiz(ficha_id, corte_id=corte_id)
    tareas_ficha = tareas_visibles(ficha_id, corte_id=corte_id).all()
    ultimas_entregas = _ultima_entrega_por_aprendiz(tareas_ficha)
    destinatarios_grupales, entregas_grupales = (
        obtener_destinatarios_y_entregas_grupales(
            ficha_id, [tarea.id for tarea in tareas_ficha]
        )
    )
    ids_grupales = {tarea.id for tarea in tareas_ficha if tarea.es_grupal}
    for clave in list(ultimas_entregas):
        if clave[0] in ids_grupales:
            ultimas_entregas.pop(clave)
    ultimas_entregas.update(entregas_grupales)

    stats_map = {}
    for aprendiz in aprendices:
        conteo = faltas.get(aprendiz.id, {})
        faltas_no_justificadas = conteo.get('FALTA', 0)
        total_faltas = sum(conteo.values())
        faltas_justificadas = total_faltas - faltas_no_justificadas
        pct_asistencia = (
            (total_sesiones - total_faltas) / total_sesiones * 100
            if total_sesiones > 0 else 100.0
        )

        tareas_pendientes = 0
        for tarea in tareas_ficha:
            if (
                tarea.es_grupal
                and aprendiz.id not in destinatarios_grupales.get(tarea.id, set())
            ):
                continue
            entrega = ultimas_entregas.get((tarea.id, aprendiz.id))
            if entrega and entrega.estado_revision == 'rechazada':
                tareas_pendientes += 1
            elif not entrega and tarea.fecha_limite and tarea.fecha_limite < ahora:
                tareas_pendientes += 1

        if faltas_no_justificadas >= config.umbral_rojo or tareas_pendientes >= 3:
            nivel = 'rojo'
        elif faltas_no_justificadas >= config.umbral_amarillo or tareas_pendientes >= 1:
            nivel = 'amarillo'
        else:
            nivel = 'verde'

        stats_map[aprendiz.id] = {
            'faltas_no_justificadas': faltas_no_justificadas,
            'faltas_justificadas': faltas_justificadas,
            'pct_asistencia': round(pct_asistencia, 1),
            'tareas_pendientes': tareas_pendientes,
            'nivel': nivel,
        }
    return stats_map, total_sesiones


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
    alertas_materiales_observador,
    aprendices,
    asistencia,
    dashboard_fichas,
    juicios_estadisticas,
    tareas_entregas,
)
