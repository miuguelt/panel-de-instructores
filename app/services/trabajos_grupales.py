"""Consultas y validaciones para los trabajos asignados a grupos."""

from collections import defaultdict
from datetime import datetime
from typing import Iterable, Optional, Tuple

from app import db
from app.helpers import utc_now
from app.models.aprendiz import Aprendiz
from app.models.grupo import Grupo, GrupoAprendiz, tarea_grupo
from app.models.tarea import MODALIDAD_CLASE, Entrega, Tarea


TIPO_ASIGNACION_INDIVIDUAL = 'individual'
TIPO_ASIGNACION_GRUPAL = 'grupal'


class DatosAsignacionTareaInvalidos(ValueError):
    """La asignación de una tarea no corresponde con el modo solicitado."""


def validar_destinatarios_tarea(
    ficha_id: int,
    tipo_asignacion: str,
    modalidad: str,
    grupos_ids: Optional[Iterable[int]] = None,
) -> Tuple[bool, list[Grupo]]:
    """Valida y resuelve los destinatarios de una tarea para una ficha.

    Retorna ``(es_grupal, grupos)`` para que el llamador asigne el resultado a
    ``Tarea.es_grupal`` y ``Tarea.grupos`` antes de confirmar la transacción.
    """
    modo = (tipo_asignacion or '').strip().lower()
    if modo not in (TIPO_ASIGNACION_INDIVIDUAL, TIPO_ASIGNACION_GRUPAL):
        raise DatosAsignacionTareaInvalidos(
            'Selecciona si la tarea es individual o grupal.'
        )

    if modo == TIPO_ASIGNACION_INDIVIDUAL:
        return False, []

    if modalidad == MODALIDAD_CLASE:
        raise DatosAsignacionTareaInvalidos(
            'Las actividades que se revisan en clase no pueden asignarse como trabajo grupal.'
        )

    if grupos_ids is None:
        valores = []
    elif isinstance(grupos_ids, (str, int)):
        valores = [grupos_ids]
    else:
        valores = list(grupos_ids)

    try:
        ids = [int(valor) for valor in valores]
    except (TypeError, ValueError) as exc:
        raise DatosAsignacionTareaInvalidos(
            'La selección de grupos no es válida.'
        ) from exc

    if not ids:
        raise DatosAsignacionTareaInvalidos(
            'Selecciona al menos un grupo para asignar el trabajo.'
        )
    if len(set(ids)) != len(ids):
        raise DatosAsignacionTareaInvalidos(
            'Cada grupo solo puede seleccionarse una vez.'
        )

    grupos_en_ficha = Grupo.query.filter(
        Grupo.id.in_(ids),
        Grupo.ficha_id == ficha_id,
        Grupo.activo.is_(True),
    ).all()
    grupos_por_id = {grupo.id: grupo for grupo in grupos_en_ficha}
    if len(grupos_por_id) != len(ids):
        raise DatosAsignacionTareaInvalidos(
            'Todos los grupos seleccionados deben estar activos y pertenecer a esta ficha.'
        )

    return True, [grupos_por_id[grupo_id] for grupo_id in ids]


def obtener_trabajos_grupales(
    aprendiz: Aprendiz,
    ahora: Optional[datetime] = None,
) -> list[dict]:
    """Arma las asignaciones activas del aprendiz y su entrega compartida."""
    if not aprendiz or not aprendiz.id or not aprendiz.ficha_id:
        return []

    asignaciones = (
        db.session.query(Tarea, Grupo)
        .join(tarea_grupo, tarea_grupo.c.tarea_id == Tarea.id)
        .join(Grupo, Grupo.id == tarea_grupo.c.grupo_id)
        .join(GrupoAprendiz, GrupoAprendiz.grupo_id == Grupo.id)
        .filter(
            Tarea.es_grupal.is_(True),
            Tarea.ficha_id == aprendiz.ficha_id,
            Grupo.ficha_id == aprendiz.ficha_id,
            Grupo.activo.is_(True),
            GrupoAprendiz.aprendiz_id == aprendiz.id,
        )
        .order_by(Tarea.fecha_limite.is_(None), Tarea.fecha_limite, Tarea.id, Grupo.id)
        .all()
    )
    if not asignaciones:
        return []

    ids_tareas = {tarea.id for tarea, _grupo in asignaciones}
    ids_grupos = {grupo.id for _tarea, grupo in asignaciones}
    entregas = (
        Entrega.query
        .filter(
            Entrega.tarea_id.in_(ids_tareas),
            Entrega.grupo_id.in_(ids_grupos),
        )
        .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
        .all()
    )
    entregas_por_destinatario = {}
    for entrega in entregas:
        entregas_por_destinatario.setdefault(
            (entrega.tarea_id, entrega.grupo_id), entrega
        )

    fecha_actual = ahora or utc_now()
    trabajos = []
    for tarea, grupo in asignaciones:
        entrega = entregas_por_destinatario.get((tarea.id, grupo.id))
        limite = tarea.fecha_limite
        if entrega:
            if entrega.estado_revision == 'rechazada':
                estado = 'correccion'
            elif not limite or not entrega.fecha_entrega or entrega.fecha_entrega <= limite:
                estado = 'entregada'
            else:
                estado = 'retraso'
        elif limite and limite < fecha_actual:
            estado = 'vencida'
        else:
            estado = 'pendiente'

        trabajos.append({
            'tarea': tarea,
            'grupo': grupo,
            'entrega': entrega,
            'estado': estado,
            'limite_efectivo': limite,
        })

    return trabajos


def obtener_destinatarios_y_entregas_grupales(
    ficha_id: int,
    tarea_ids: Optional[Iterable[int]] = None,
) -> Tuple[dict[int, set[int]], dict[Tuple[int, int], Entrega]]:
    """Devuelve integrantes destinatarios y entregas compartidas por tarea.

    Las claves de la segunda respuesta son ``(tarea_id, aprendiz_id)`` para
    que los indicadores individuales reflejen la evidencia de su grupo.
    """
    consulta = (
        db.session.query(Tarea.id, Grupo.id, Aprendiz.id)
        .join(tarea_grupo, tarea_grupo.c.tarea_id == Tarea.id)
        .join(Grupo, Grupo.id == tarea_grupo.c.grupo_id)
        .join(GrupoAprendiz, GrupoAprendiz.grupo_id == Grupo.id)
        .join(Aprendiz, Aprendiz.id == GrupoAprendiz.aprendiz_id)
        .filter(
            Tarea.ficha_id == ficha_id,
            Tarea.es_grupal.is_(True),
            Grupo.ficha_id == ficha_id,
            Grupo.activo.is_(True),
            Aprendiz.ficha_id == ficha_id,
        )
    )
    if tarea_ids is not None:
        ids = list(tarea_ids)
        if not ids:
            return {}, {}
        consulta = consulta.filter(Tarea.id.in_(ids))

    asignaciones = consulta.all()
    destinatarios: dict[int, set[int]] = defaultdict(set)
    entregas_por_grupo = {}
    grupos_por_tarea: dict[int, set[int]] = defaultdict(set)
    for tarea_id, grupo_id, aprendiz_id in asignaciones:
        destinatarios[tarea_id].add(aprendiz_id)
        grupos_por_tarea[tarea_id].add(grupo_id)

    ids_tareas = set(grupos_por_tarea)
    ids_grupos = {
        grupo_id
        for grupo_ids in grupos_por_tarea.values()
        for grupo_id in grupo_ids
    }
    if ids_tareas and ids_grupos:
        entregas = (
            Entrega.query
            .filter(
                Entrega.tarea_id.in_(ids_tareas),
                Entrega.grupo_id.in_(ids_grupos),
            )
            .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
            .all()
        )
        for entrega in entregas:
            entregas_por_grupo.setdefault(
                (entrega.tarea_id, entrega.grupo_id), entrega
            )

    compartidas = {}
    for tarea_id, grupo_id, aprendiz_id in asignaciones:
        entrega = entregas_por_grupo.get((tarea_id, grupo_id))
        if entrega:
            compartidas[(tarea_id, aprendiz_id)] = entrega
    return dict(destinatarios), compartidas
