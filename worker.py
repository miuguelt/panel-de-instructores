"""Worker de importaciones Excel para ejecutar como servicio de Compose."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from redis import Redis
from werkzeug.datastructures import FileStorage

from app.models import ImportacionJob, Ficha
from app.services.alertas import actualizar_alertas_ficha
from app.services.importacion_ficha import importar_archivo
from app.services.ranking import actualizar_participacion_ficha
from app.services.archivos import resolver_archivo_subido
from app import db
from app.services.importacion_jobs import _cliente_redis
from wsgi import app

log = logging.getLogger(__name__)


def _resultado_resumido(resultado):
    return {
        clave: resultado.get(clave, 0)
        for clave in (
            'nuevos', 'actualizados', 'juicios_nuevos',
            'juicios_repetidos', 'sesiones_creadas',
        )
    } | {'errores': len(resultado.get('errores', []))}


def _procesar(job_id):
    with app.app_context():
        job = db.session.get(ImportacionJob, int(job_id))
        if not job or job.estado != 'encolado':
            return
        archivo_path = job.archivo_path

        job.estado = 'procesando'
        job.iniciado_en = datetime.utcnow()
        db.session.commit()

        try:
            ficha = db.session.get(Ficha, job.ficha_id)
            if not ficha:
                raise RuntimeError(f'La ficha {job.ficha_id} ya no existe.')
            _raiz, _relativa, _candidatos = resolver_archivo_subido(job.archivo_path)
            with open(job.archivo_path, 'rb') as stream:
                archivo = FileStorage(stream=stream, filename=job.nombre_archivo)
                resultado = importar_archivo(archivo, ficha, job.instructor_id)

            # Este commit confirma los datos académicos antes de recalcular
            # módulos secundarios. Si estos fallan, la importación permanece.
            db.session.commit()
            actualizar_alertas_ficha(ficha.id)
            actualizar_participacion_ficha(ficha.id)

            job.estado = 'completado'
            job.resultado = json.dumps(_resultado_resumido(resultado), ensure_ascii=False)
            job.terminado_en = datetime.utcnow()
            db.session.commit()
            log.info('Importación #%s completada: %s', job.id, job.resultado)
        except Exception as exc:
            db.session.rollback()
            job = db.session.get(ImportacionJob, int(job_id))
            if job:
                job.estado = 'error'
                job.error = f'{type(exc).__name__}: {exc}'
                job.terminado_en = datetime.utcnow()
                db.session.commit()
            log.exception('Falló la importación #%s', job_id)
        finally:
            try:
                if archivo_path and os.path.isfile(archivo_path):
                    os.remove(archivo_path)
            except OSError:
                log.warning('No se pudo eliminar el archivo temporal del trabajo %s', job_id)
            db.session.remove()


def main():
    redis_client: Redis = _cliente_redis()
    queue_name = app.config['IMPORT_QUEUE_NAME']
    log.info('Worker de importaciones escuchando en %s', queue_name)
    while True:
        _nombre, job_id = redis_client.blpop(queue_name, timeout=30) or (None, None)
        if job_id:
            _procesar(job_id)


if __name__ == '__main__':
    main()
