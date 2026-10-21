"""Servicio unificado de recuperación de fuentes para una ficha.

Orquesta la recuperación integral de los tres documentos oficiales de la ficha:
1. Reporte de Juicios Evaluativos (SOFIA Plus)
2. Planeación Pedagógica del Proyecto Formativo (GFPI-F-134)
3. Programa de Formación Curricular (Diseño SENA en PDF)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import current_app

from app import db
from app.models.archivo_ficha import (
    ArchivoFichaVersion,
    TIPO_PLANEACION,
    TIPO_PROGRAMA,
    TIPO_REPORTE_JUICIOS,
)
from app.models.ficha import Ficha
from app.services.importacion_jobs import encolar_recalculo_resumen
from app.services.recuperacion_planeacion import asegurar_version_planeacion
from app.services.recuperacion_programa import asegurar_version_programa
from app.services.recuperacion_reportes import asegurar_version_reporte
from app.services.versiones_archivos import ultima_version


def recuperar_fuentes_ficha(
    ficha_o_id: Any, instructor_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Recupera o asegura los tres documentos oficiales de la ficha en una sola operación."""
    if isinstance(ficha_o_id, int):
        ficha = db.session.get(Ficha, ficha_o_id)
    else:
        ficha = ficha_o_id

    if not ficha:
        return {'ok': False, 'mensaje': 'Ficha no encontrada.', 'nuevas': [], 'total_nuevas': 0}

    # Estado previo antes de intentar recuperar
    tenia_reporte = bool(ultima_version(ficha.id, TIPO_REPORTE_JUICIOS, solo_procesadas=True, recuperar_reporte=False))
    tenia_planeacion = bool(ultima_version(ficha.id, TIPO_PLANEACION, solo_procesadas=True))
    tenia_programa = bool(ultima_version(ficha.id, TIPO_PROGRAMA, solo_procesadas=True))

    version_reporte = asegurar_version_reporte(ficha, instructor_id=instructor_id)
    version_planeacion = asegurar_version_planeacion(ficha, instructor_id=instructor_id)
    version_programa = asegurar_version_programa(ficha, instructor_id=instructor_id)

    nuevas: List[str] = []
    if not tenia_reporte and version_reporte:
        nuevas.append('Reporte de Juicios')
    if not tenia_planeacion and version_planeacion:
        nuevas.append('Planeación Pedagógica')
    if not tenia_programa and version_programa:
        nuevas.append('Programa de Formación')

    advertencias = []
    if nuevas:
        try:
            trabajo = encolar_recalculo_resumen(ficha.id, instructor_id or ficha.instructor_id)
            if trabajo is not None and trabajo.estado == 'error':
                advertencias.append('Las fuentes quedaron recuperadas, pero no fue posible iniciar la actualización de indicadores. Vuelva a intentarlo más tarde o informe al administrador.')
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Las fuentes de la ficha %s se recuperaron, pero falló la actualización de indicadores.', ficha.id)
            advertencias.append('Las fuentes quedaron recuperadas, pero no se confirmó la actualización de indicadores. Recargue la página más tarde.')

    return {
        'ok': True,
        'ficha_id': ficha.id,
        'reporte': version_reporte,
        'planeacion': version_planeacion,
        'programa': version_programa,
        'nuevas': nuevas,
        'total_nuevas': len(nuevas),
        'advertencias': advertencias,
        'recalculo_pendiente': bool(advertencias),
    }
