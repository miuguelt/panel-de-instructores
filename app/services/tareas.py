"""Servicio de dominio para la gestión y ciclo de vida de tareas formativas."""

from __future__ import annotations

from datetime import datetime
from itertools import groupby
from typing import Any, Dict, List, Optional, Tuple

from app import db
from app.models.ficha import Ficha
from app.models.corte import Corte
from app.models.tarea import (
    MODALIDAD_EVIDENCIA,
    MODALIDADES_TAREA,
    Tarea,
)
from app.services.archivos import ArchivoService, ErrorArchivo, TiposCarpeta
from app.services.permisos import puede_gestionar_ficha, puede_gestionar_tarea


class DatosTareaInvalidos(ValueError):
    """El formulario de la tarea no cumple las validaciones mínimas."""


def leer_datos_tarea(form: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza y valida el formulario que comparten la creación y la edición."""
    titulo = form.get('titulo', '').strip()
    if not titulo:
        raise DatosTareaInvalidos('El título es obligatorio.')

    modalidad = form.get('modalidad', MODALIDAD_EVIDENCIA).strip()
    if modalidad not in MODALIDADES_TAREA:
        modalidad = MODALIDAD_EVIDENCIA

    fecha_limite = None
    fecha_limite_str = form.get('fecha_limite', '')
    if fecha_limite_str:
        try:
            fecha_limite = datetime.strptime(fecha_limite_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            raise DatosTareaInvalidos('La fecha límite no tiene un formato válido.')

    return {
        'titulo': titulo,
        'descripcion': form.get('descripcion', '').strip(),
        'enlace_externo': form.get('enlace_externo', '').strip() or None,
        'fecha_limite': fecha_limite,
        'modalidad': modalidad,
        'requiere_archivo': modalidad == MODALIDAD_EVIDENCIA and 'requiere_archivo' in form,
    }


def guardar_material_apoyo(archivo: Any, ficha_id: int, instructor_id: int) -> str:
    """Guarda el material de apoyo de una tarea y devuelve su URL relativa."""
    resultado = ArchivoService.guardar(
        archivo=archivo,
        carpeta=TiposCarpeta.MATERIALES_TAREA,
        subcarpeta=f'ficha_{ficha_id}/instructor_{instructor_id}',
        prefijo_extra=f'tarea_{instructor_id}',
        check_magic=True,
    )
    return resultado.url


def obtener_tarea_gestionable(ficha_id: int, tarea_id: int) -> Tuple[Optional[Ficha], Optional[Tarea]]:
    """Devuelve la ficha y tarea si el usuario actual puede operarla dentro de esa ficha."""
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        return None, None
    tarea = db.session.get(Tarea, tarea_id)
    if not tarea or tarea.ficha_id != ficha_id or not puede_gestionar_tarea(tarea):
        return ficha, None
    return ficha, tarea


def agrupar_tareas_por_corte_e_instructor(
    lista_tareas: List[Tarea],
    cortes_lista: List[Corte],
) -> List[Dict[str, Any]]:
    """Agrupa tareas por corte pedagógico y por instructor responsable para el tablero agrupado."""
    orden_cortes = {c.id: i for i, c in enumerate(cortes_lista)}
    tareas_ordenadas = sorted(
        lista_tareas,
        key=lambda t: (
            orden_cortes.get(t.corte_id, len(orden_cortes)),
            (t.creador.nombre or '').lower() if t.creador else '',
            -(t.creada_en.timestamp() if t.creada_en else 0.0),
        ),
    )
    grupos: List[Dict[str, Any]] = []
    for _corte_gid, tareas_corte_iter in groupby(tareas_ordenadas, key=lambda t: t.corte_id):
        tareas_corte = list(tareas_corte_iter)
        subgrupos: List[Dict[str, Any]] = []
        for _inst_id, tareas_inst_iter in groupby(tareas_corte, key=lambda t: t.instructor_id):
            tareas_inst = list(tareas_inst_iter)
            subgrupos.append({
                'instructor': tareas_inst[0].creador,
                'tareas': tareas_inst,
            })
        grupos.append({
            'corte': tareas_corte[0].corte,
            'instructores': subgrupos,
            'total': len(tareas_corte),
        })
    return grupos


def eliminar_tarea_con_archivos(tarea: Tarea) -> str:
    """Elimina la tarea con sus entregas y los archivos físicos asociados en disco."""
    titulo = tarea.titulo
    archivos = [
        entrega.archivo_url
        for entrega in tarea.entregas.all()
        if entrega.archivo_url
    ]
    if tarea.material_apoyo_url:
        archivos.append(tarea.material_apoyo_url)

    db.session.delete(tarea)
    db.session.commit()

    for url in archivos:
        ArchivoService.eliminar(url)

    return titulo
