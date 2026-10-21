"""Limpieza de temporales y reconciliación de enlaces tras un fallo."""

import json
from pathlib import Path

from flask import current_app

from app import db
from app.helpers import utc_now
from app.models import ArchivoFichaVersion, Entrega, MaterialFicha, PlanMejoramiento, RegistroAsistencia, Tarea
from app.models.carga import CargaArchivo, EnvioCarga
from app.services.cargas_bloqueos import bloquear, directorio_privado
from app.services.cargas_errores import ErrorCarga


def archivo_referenciado(ruta):
    for modelo, columna in ((ArchivoFichaVersion, ArchivoFichaVersion.ruta_archivo),
            (Entrega, Entrega.archivo_url), (MaterialFicha, MaterialFicha.url_archivo),
            (PlanMejoramiento, PlanMejoramiento.evidencia_url),
            (RegistroAsistencia, RegistroAsistencia.soporte_url), (Tarea, Tarea.material_apoyo_url)):
        if db.session.query(modelo.id).filter(columna == ruta).first():
            return True
    return False


def _limpiar_archivos(carga):
    directorio = directorio_privado()
    diario = directorio / (carga.id + '.json')
    if diario.exists():
        raiz = Path(current_app.config['UPLOAD_FOLDER']).resolve()
        for nombre in json.loads(diario.read_text(encoding='utf-8')):
            # .part se renombra antes de la transacción; ambas rutas pueden
            # sobrevivir si el proceso terminó entre la escritura y el commit.
            for relativa in {nombre, nombre.removesuffix('.part')}:
                ruta = (raiz / relativa).resolve()
                if ruta.is_relative_to(raiz) and not archivo_referenciado(relativa):
                    ruta.unlink(missing_ok=True)
        diario.unlink(missing_ok=True)
    (directorio / (carga.id + '.part')).unlink(missing_ok=True)


def limpiar_cargas():
    cargas = CargaArchivo.query.filter(CargaArchivo.vence_en <= utc_now(),
                                      CargaArchivo.estado.notin_(['vencido', 'limpiado'])).all()
    eliminadas = 0
    for carga in cargas:
        try:
            with bloquear(carga.id):
                envio = db.session.get(EnvioCarga, carga.envio_id) if carga.envio_id else None
                if envio and envio.estado in {'encolado', 'procesando', 'confirmando'}:
                    continue
                _limpiar_archivos(carga)
                if not envio:
                    carga.estado = 'vencido'
                else:
                    carga.estado = 'limpiado'
                db.session.commit()
                eliminadas += 1
        except (OSError, ValueError, ErrorCarga):
            db.session.rollback()
            current_app.logger.warning('No se pudo limpiar el temporal de carga %s; se volverá a intentar.', carga.id)
    return eliminadas
