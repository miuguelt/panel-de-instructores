"""Servicio de dominio para la gestión y ciclo de vida de tareas formativas."""

from __future__ import annotations

from datetime import datetime
from itertools import groupby
from typing import Any, Dict, List, Optional, Tuple

from app import db
from app.helpers import utc_now
from app.models.ficha import Ficha
from app.models.corte import Corte
from app.models.aprendiz import Aprendiz
from app.models.alertas import PlanMejoramiento
from sqlalchemy import case, func
from app.models.tarea import (
    Entrega,
    MODALIDAD_EVIDENCIA,
    MODALIDADES_TAREA,
    ProrrogaTarea,
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



def formatear_tiempo_humano(segundos: float) -> str:
    """Formatea una cantidad de segundos en una expresión legible en español de Colombia."""
    segundos_pos = max(0.0, float(segundos))
    if segundos_pos >= 86400:
        dias = int(segundos_pos // 86400)
        horas = int((segundos_pos % 86400) // 3600)
        texto_dias = f'{dias} día' if dias == 1 else f'{dias} días'
        if horas > 0:
            texto_horas = f'{horas} hora' if horas == 1 else f'{horas} horas'
            return f'{texto_dias} y {texto_horas}'
        return texto_dias
    elif segundos_pos >= 3600:
        horas = int(segundos_pos // 3600)
        minutos = int((segundos_pos % 3600) // 60)
        texto_horas = f'{horas} hora' if horas == 1 else f'{horas} horas'
        if minutos > 0:
            return f'{texto_horas} y {minutos} min'
        return texto_horas
    elif segundos_pos >= 60:
        minutos = int(segundos_pos // 60)
        return f'{minutos} minuto' if minutos == 1 else f'{minutos} minutos'
    else:
        return 'menos de un minuto'


def calcular_progreso_tiempo_tarea(
    tarea: Any,
    ahora: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Calcula el porcentaje de tiempo transcurrido y tiempo restante para finalizar la tarea."""
    if ahora is None:
        ahora = utc_now()

    fecha_limite = getattr(tarea, 'fecha_limite', None)
    creada_en = getattr(tarea, 'creada_en', None) or ahora

    if not fecha_limite:
        return {
            'porcentaje': 0,
            'porcentaje_restante': 100,
            'estado': 'sin_limite',
            'texto_tiempo': 'Sin fecha límite',
            'detalle': 'Esta actividad no tiene fecha límite programada',
            'vencida': False,
            'sin_limite': True,
            'tiempo_restante_segundos': None,
            'fecha_inicio': creada_en,
            'fecha_limite': None,
        }

    if ahora >= fecha_limite:
        segundos_vencida = (ahora - fecha_limite).total_seconds()
        texto_pasado = formatear_tiempo_humano(segundos_vencida)
        return {
            'porcentaje': 100,
            'porcentaje_restante': 0,
            'estado': 'vencida',
            'texto_tiempo': f'Vencida hace {texto_pasado}',
            'detalle': 'El plazo de entrega ya expiró (100% transcurrido)',
            'vencida': True,
            'sin_limite': False,
            'tiempo_restante_segundos': 0.0,
            'fecha_inicio': creada_en,
            'fecha_limite': fecha_limite,
        }

    duracion_total = (fecha_limite - creada_en).total_seconds()
    if duracion_total <= 0:
        return {
            'porcentaje': 100,
            'porcentaje_restante': 0,
            'estado': 'vencida',
            'texto_tiempo': 'Plazo finalizado',
            'detalle': 'Fecha límite alcanzada',
            'vencida': True,
            'sin_limite': False,
            'tiempo_restante_segundos': 0.0,
            'fecha_inicio': creada_en,
            'fecha_limite': fecha_limite,
        }

    if ahora < creada_en:
        segundos_restantes = (fecha_limite - ahora).total_seconds()
        return {
            'porcentaje': 0,
            'porcentaje_restante': 100,
            'estado': 'normal',
            'texto_tiempo': f'Quedan {formatear_tiempo_humano(segundos_restantes)}',
            'detalle': 'Plazo completo disponible (0% transcurrido)',
            'vencida': False,
            'sin_limite': False,
            'tiempo_restante_segundos': segundos_restantes,
            'fecha_inicio': creada_en,
            'fecha_limite': fecha_limite,
        }

    transcurrido = (ahora - creada_en).total_seconds()
    restante = (fecha_limite - ahora).total_seconds()
    porcentaje = min(100, max(0, round((transcurrido / duracion_total) * 100)))
    porcentaje_restante = max(0, 100 - porcentaje)

    if restante <= 86400 or porcentaje >= 85:
        estado = 'urgente'
    elif restante <= 172800 or porcentaje >= 65:
        estado = 'atencion'
    else:
        estado = 'normal'

    texto_restante = formatear_tiempo_humano(restante)
    return {
        'porcentaje': porcentaje,
        'porcentaje_restante': porcentaje_restante,
        'estado': estado,
        'texto_tiempo': f'Quedan {texto_restante}',
        'detalle': f'{porcentaje}% del tiempo transcurrido ({porcentaje_restante}% restante)',
        'vencida': False,
        'sin_limite': False,
        'tiempo_restante_segundos': restante,
        'fecha_inicio': creada_en,
        'fecha_limite': fecha_limite,
    }


def obtener_estadisticas_entregas_tareas(
    tareas_ids: List[int],
) -> Dict[int, Dict[str, int]]:
    """Calcula en una sola consulta las estadísticas de entregas para un conjunto de tareas."""
    if not tareas_ids:
        return {}

    filas = db.session.query(
        Entrega.tarea_id,
        func.count(Entrega.id).label('total'),
        func.sum(case((Entrega.calificada.is_(True), 1), else_=0)).label('calificadas'),
        func.sum(case((Entrega.calificada.is_(False), 1), else_=0)).label('pendientes'),
    ).filter(
        Entrega.tarea_id.in_(tareas_ids)
    ).group_by(
        Entrega.tarea_id
    ).all()

    return {
        int(fila.tarea_id): {
            'total': int(fila.total or 0),
            'calificadas': int(fila.calificadas or 0),
            'pendientes': int(fila.pendientes or 0),
        }
        for fila in filas
    }


def agrupar_tareas_por_instructor(
    lista_tareas: List[Tarea],
    current_user_id: Optional[int] = None,
    estadisticas_entregas: Optional[Dict[int, Dict[str, int]]] = None,
    ahora: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Agrupa tareas por instructor responsable, ordenando al usuario actual de primero."""
    if ahora is None:
        ahora = utc_now()
    if estadisticas_entregas is None:
        estadisticas_entregas = {}

    for tarea in lista_tareas:
        if not hasattr(tarea, '_progreso_tiempo_cache'):
            tarea._progreso_tiempo_cache = calcular_progreso_tiempo_tarea(tarea, ahora=ahora)
        tarea.stats_entregas = estadisticas_entregas.get(
            tarea.id, {'total': 0, 'calificadas': 0, 'pendientes': 0}
        )

    def _clave_orden(t: Tarea):
        es_mio = 0 if (current_user_id and t.instructor_id == current_user_id) else 1
        nombre_inst = (t.creador.nombre or '').lower() if t.creador else 'zzzz'
        limite_ts = t.fecha_limite.timestamp() if t.fecha_limite else float('inf')
        return (es_mio, nombre_inst, limite_ts, -(t.creada_en.timestamp() if t.creada_en else 0.0))

    tareas_ordenadas = sorted(lista_tareas, key=_clave_orden)

    grupos: List[Dict[str, Any]] = []
    for _inst_id, tareas_inst_iter in groupby(tareas_ordenadas, key=lambda t: t.instructor_id):
        tareas_inst = list(tareas_inst_iter)
        instructor = tareas_inst[0].creador
        es_actual = bool(current_user_id and instructor and instructor.id == current_user_id)

        total_tareas = len(tareas_inst)
        tareas_activas = sum(
            1 for t in tareas_inst
            if getattr(t, '_progreso_tiempo_cache', {}).get('estado') in ('normal', 'atencion', 'urgente')
        )
        tareas_urgentes = sum(
            1 for t in tareas_inst
            if getattr(t, '_progreso_tiempo_cache', {}).get('estado') == 'urgente'
        )
        tareas_vencidas = sum(
            1 for t in tareas_inst
            if getattr(t, '_progreso_tiempo_cache', {}).get('estado') == 'vencida'
        )
        tareas_sin_limite = sum(
            1 for t in tareas_inst
            if getattr(t, '_progreso_tiempo_cache', {}).get('estado') == 'sin_limite'
        )
        total_entregas = sum(t.stats_entregas.get('total', 0) for t in tareas_inst)
        pendientes_calificar = sum(t.stats_entregas.get('pendientes', 0) for t in tareas_inst)
        calificadas = sum(t.stats_entregas.get('calificadas', 0) for t in tareas_inst)

        grupos.append({
            'instructor': instructor,
            'es_actual': es_actual,
            'nombre': instructor.nombre if instructor else 'Instructor no asignado',
            'email': getattr(instructor, 'email', '') if instructor else '',
            'total_tareas': total_tareas,
            'tareas_activas': tareas_activas,
            'tareas_urgentes': tareas_urgentes,
            'tareas_vencidas': tareas_vencidas,
            'tareas_sin_limite': tareas_sin_limite,
            'total_entregas': total_entregas,
            'pendientes_calificar': pendientes_calificar,
            'calificadas': calificadas,
            'tareas': tareas_inst,
        })

    return grupos


def agrupar_tareas_por_corte_e_instructor(
    lista_tareas: List[Tarea],
    cortes_lista: List[Corte],
    estadisticas_entregas: Optional[Dict[int, Dict[str, int]]] = None,
    ahora: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Agrupa tareas por corte pedagógico y por instructor responsable para el tablero agrupado."""
    if ahora is None:
        ahora = utc_now()
    if estadisticas_entregas is None:
        estadisticas_entregas = {}

    for tarea in lista_tareas:
        if not hasattr(tarea, '_progreso_tiempo_cache'):
            tarea._progreso_tiempo_cache = calcular_progreso_tiempo_tarea(tarea, ahora=ahora)
        tarea.stats_entregas = estadisticas_entregas.get(
            tarea.id, {'total': 0, 'calificadas': 0, 'pendientes': 0}
        )

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


def conceder_prorroga_tarea(
    tarea_id: int,
    aprendiz_id: int,
    instructor_id: int,
    nueva_fecha_limite: datetime,
    motivo: Optional[str] = None,
) -> ProrrogaTarea:
    """Otorga o actualiza una prórroga individual para la entrega de una tarea."""
    prorroga = ProrrogaTarea.query.filter_by(tarea_id=tarea_id, aprendiz_id=aprendiz_id).first()
    if prorroga:
        prorroga.nueva_fecha_limite = nueva_fecha_limite
        prorroga.motivo = motivo.strip() if motivo else None
        prorroga.instructor_id = instructor_id
        prorroga.actualizada_en = utc_now()
    else:
        prorroga = ProrrogaTarea(
            tarea_id=tarea_id,
            aprendiz_id=aprendiz_id,
            instructor_id=instructor_id,
            nueva_fecha_limite=nueva_fecha_limite,
            motivo=motivo.strip() if motivo else None,
            creada_en=utc_now(),
        )
        db.session.add(prorroga)

    db.session.commit()

    tarea = db.session.get(Tarea, tarea_id)
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if tarea and aprendiz:
        from app.services.alertas import registrar_notificacion
        fecha_fmt = nueva_fecha_limite.strftime('%d/%m/%Y %H:%M')
        mensaje = (
            f'Se te ha concedido una prórroga para entregar la evidencia "{tarea.titulo}" '
            f'hasta el {fecha_fmt}.'
        )
        if motivo:
            mensaje += f' Motivo: {motivo.strip()}.'
        registrar_notificacion(
            destinatario_tipo='aprendiz',
            destinatario_id=aprendiz.id,
            mensaje=mensaje,
            tipo='tarea',
            clave=f'prorroga:{tarea.id}:{aprendiz.id}:{nueva_fecha_limite.isoformat()}',
            ficha_id=tarea.ficha_id,
            url=f'/aprendiz/{tarea.ficha_id}/panel?documento={aprendiz.documento}',
        )
        db.session.commit()

    return prorroga


def revocar_prorroga_tarea(tarea_id: int, aprendiz_id: int) -> bool:
    """Revoca la prórroga individual concedida a un aprendiz para una tarea."""
    prorroga = ProrrogaTarea.query.filter_by(tarea_id=tarea_id, aprendiz_id=aprendiz_id).first()
    if prorroga:
        db.session.delete(prorroga)
        db.session.commit()
        return True
    return False


def obtener_prorrogas_tarea(tarea_id: int) -> Dict[int, ProrrogaTarea]:
    """Retorna un diccionario {aprendiz_id: ProrrogaTarea} para una tarea dada."""
    prorrogas = ProrrogaTarea.query.filter_by(tarea_id=tarea_id).all()
    return {p.aprendiz_id: p for p in prorrogas}


def obtener_planes_de_tarea(tarea_id: int) -> Dict[int, PlanMejoramiento]:
    """Retorna un diccionario {aprendiz_id: PlanMejoramiento} para planes activos vinculados a una tarea."""
    planes = PlanMejoramiento.query.filter_by(tarea_id=tarea_id).order_by(
        PlanMejoramiento.fecha_creacion.desc()
    ).all()
    # Tomar el plan más reciente por aprendiz
    resultado: Dict[int, PlanMejoramiento] = {}
    for plan in planes:
        resultado.setdefault(plan.aprendiz_id, plan)
    return resultado

