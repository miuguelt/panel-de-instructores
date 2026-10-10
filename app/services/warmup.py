"""Precalentamiento de snapshots y vistas calculadas para el inicio del servidor."""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from flask import Flask

from app.models.ficha import Ficha
from app.services.resultados_persistidos import precargar_resultados_ficha

log = logging.getLogger(__name__)


def precargar_todas_las_fichas(
    app: Optional[Flask] = None,
    hoy: Optional[date] = None,
) -> Dict[str, int]:
    """Calcula y persiste los snapshots de fases, panorama y TyT para todas las fichas.

    Evita que la primera petición tras el despliegue sufra latencias altas
    al procesar documentos y juicios de forma sincrónica.
    """
    def _ejecutar() -> Dict[str, int]:
        fichas = Ficha.query.order_by(Ficha.id).all()
        exitosas = 0
        fallidas = 0
        for ficha in fichas:
            try:
                precargar_resultados_ficha(ficha.id, hoy=hoy)
                exitosas += 1
            except Exception as exc:
                fallidas += 1
                log.warning(
                    'No se pudo precargar la ficha %s (%s): %s',
                    getattr(ficha, 'id', None),
                    getattr(ficha, 'codigo', 'sin_codigo'),
                    exc,
                )
        return {'total': len(fichas), 'exitosas': exitosas, 'fallidas': fallidas}

    if app is not None:
        with app.app_context():
            return _ejecutar()
    return _ejecutar()
