"""Servicio de cálculo y posiciones de la Liga de Escuadrones y Retos Grupales."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from app.models.aprendiz import Aprendiz
from app.models.grupo import Grupo, GrupoAprendiz
from app.models.insignia import Insignia, InsigniaOtorgada
from app.models.tarea import Entrega


def obtener_liga_grupos(ficha_id: int, aprendiz_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Calcula la tabla de posiciones de la Liga de Escuadrones (grupos) de la ficha.

    Pondera formativamente:
    - Insignias/medallas grupales obtenidas (15.0 pts cada una).
    - Tareas grupales entregadas a tiempo (10.0 pts cada una).
    - Tareas grupales entregadas extemporáneas (5.0 pts cada una).
    - Tareas grupales con revisión aprobada / excelente.
    """
    grupos_activos = (
        Grupo.query
        .filter_by(ficha_id=ficha_id, activo=True)
        .all()
    )
    if not grupos_activos:
        return []

    grupos_ids = [g.id for g in grupos_activos]

    # Cargar aprendices asignados a los grupos
    miembros_map = defaultdict(list)
    asignaciones = (
        GrupoAprendiz.query
        .filter(GrupoAprendiz.grupo_id.in_(grupos_ids))
        .all()
    )
    aprendices_ids = {a.aprendiz_id for a in asignaciones}
    aprendices_dict = {}
    if aprendices_ids:
        aprendices_dict = {
            ap.id: ap
            for ap in Aprendiz.query.filter(Aprendiz.id.in_(aprendices_ids)).all()
        }
    for asig in asignaciones:
        if asig.aprendiz_id in aprendices_dict:
            miembros_map[asig.grupo_id].append(aprendices_dict[asig.aprendiz_id])

    # Insignias otorgadas a los grupos
    otorgamientos_g = (
        InsigniaOtorgada.query
        .join(Insignia)
        .filter(
            InsigniaOtorgada.grupo_id.in_(grupos_ids),
            Insignia.ficha_id == ficha_id,
        )
        .order_by(InsigniaOtorgada.fecha_obtencion.desc())
        .all()
    )
    insignias_por_grupo = defaultdict(list)
    for ot in otorgamientos_g:
        insignias_por_grupo[ot.grupo_id].append(ot.insignia)

    # Entregas grupales
    entregas_g = (
        Entrega.query
        .filter(Entrega.grupo_id.in_(grupos_ids))
        .all()
    )
    entregas_por_grupo = defaultdict(list)
    for ent in entregas_g:
        entregas_por_grupo[ent.grupo_id].append(ent)

    liga: List[Dict[str, Any]] = []
    for grupo in grupos_activos:
        miembros = miembros_map.get(grupo.id, [])
        insignias_grupo = insignias_por_grupo.get(grupo.id, [])
        entregas_grupo = entregas_por_grupo.get(grupo.id, [])

        entregadas_a_tiempo = sum(1 for e in entregas_grupo if e.entregada_a_tiempo)
        entregadas_con_retraso = sum(1 for e in entregas_grupo if not e.entregada_a_tiempo)

        # Cálculo transparente de puntaje colectivo
        puntos_medallas = len(insignias_grupo) * 15.0
        puntos_tareas = (entregadas_a_tiempo * 10.0) + (entregadas_con_retraso * 5.0)
        puntos_totales = round(puntos_medallas + puntos_tareas, 1)

        es_mi_grupo = bool(aprendiz_id and any(m.id == aprendiz_id for m in miembros))

        liga.append({
            'grupo': grupo,
            'Grupo': grupo,
            'id': grupo.id,
            'grupo_id': grupo.id,
            'nombre': grupo.nombre,
            'miembros': miembros,
            'total_miembros': len(miembros),
            'miembros_count': len(miembros),
            'total_insignias': len(insignias_grupo),
            'medallas_count': len(insignias_grupo),
            'insignias': insignias_grupo[:4],
            'total_entregas': len(entregas_grupo),
            'tareas_entregadas': len(entregas_grupo),
            'entregadas_a_tiempo': entregadas_a_tiempo,
            'entregadas_con_retraso': entregadas_con_retraso,
            'puntaje': puntos_totales,
            'puntaje_grupo': puntos_totales,
            'es_mi_grupo': es_mi_grupo,
        })

    # Ordenamiento por mérito: puntaje descendente, medallas, entregas a tiempo, nombre
    liga.sort(
        key=lambda item: (
            -item['puntaje'],
            -item['total_insignias'],
            -item['entregadas_a_tiempo'],
            item['nombre'].lower(),
        )
    )

    medallas_podio = {1: '🥇', 2: '🥈', 3: '🥉'}
    for pos, item in enumerate(liga, start=1):
        item['posicion'] = pos
        item['medalla'] = medallas_podio.get(pos, '')
        item['podio'] = medallas_podio.get(pos, '')

    return liga


def obtener_resumen_escuadron(
    ficha_id: int,
    aprendiz_id: int,
) -> Optional[Dict[str, Any]]:
    """Devuelve la información destacada del escuadrón al que pertenece el aprendiz."""
    liga = obtener_liga_grupos(ficha_id=ficha_id, aprendiz_id=aprendiz_id)
    for escuadron in liga:
        if escuadron.get('es_mi_grupo'):
            resumen = dict(escuadron)
            resumen['companeros'] = [
                getattr(m, 'nombre_completo', m.nombre) for m in escuadron.get('miembros', [])
            ]
            return resumen
    return None
