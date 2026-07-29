"""Worker de importaciones Excel para ejecutar como servicio de Compose."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime

from redis import Redis
from redis.exceptions import RedisError
from werkzeug.datastructures import FileStorage

from app.models import ImportacionJob, Ficha
from app.services.alertas import actualizar_alertas_ficha
from app.services.importacion_ficha import importar_archivo
from app.services.ranking import actualizar_participacion_ficha
from app.services.archivos import resolver_archivo_subido
from app import db
from app.services.importacion_jobs import _cliente_redis, _redis_destino
from wsgi import app

log = logging.getLogger(__name__)
WORKER_READY_FILE = '/tmp/adso-worker-ready'


def _entero_positivo_entorno(nombre, defecto):
    raw = os.getenv(nombre)
    if raw is None or not raw.strip():
        return defecto
    try:
        valor = int(raw)
        if valor > 0:
            return valor
    except (TypeError, ValueError):
        pass
    log.warning('%s=%r no es válido; se usará %s.', nombre, raw, defecto)
    return defecto


WORKER_BLPOP_TIMEOUT = _entero_positivo_entorno('WORKER_BLPOP_TIMEOUT', 30)
WORKER_SOCKET_TIMEOUT = _entero_positivo_entorno('WORKER_SOCKET_TIMEOUT', 35)
if WORKER_SOCKET_TIMEOUT <= WORKER_BLPOP_TIMEOUT:
    WORKER_SOCKET_TIMEOUT = WORKER_BLPOP_TIMEOUT + 5
    log.warning(
        'WORKER_SOCKET_TIMEOUT debe superar WORKER_BLPOP_TIMEOUT; se ajustó a %s segundos.',
        WORKER_SOCKET_TIMEOUT,
    )


def _resultado_resumido(resultado):
    return {
        clave: resultado.get(clave, 0)
        for clave in (
            'nuevos', 'actualizados', 'juicios_nuevos',
            'juicios_repetidos', 'sesiones_creadas',
        )
    } | {'errores': len(resultado.get('errores', []))}


def _conectar_redis():
    """Espera Redis al arrancar y deja el error completo en los logs."""
    max_intentos = int(os.getenv('WORKER_REDIS_RETRIES', '12'))
    espera = float(os.getenv('WORKER_REDIS_RETRY_DELAY', '5'))
    for intento in range(1, max_intentos + 1):
        try:
            cliente = _cliente_redis(socket_timeout=WORKER_SOCKET_TIMEOUT)
            log.info(
                'WORKER_REDIS_OK intento=%s destino=%s cola=%s socket_timeout=%ss',
                intento, _redis_destino(), app.config['IMPORT_QUEUE_NAME'],
                WORKER_SOCKET_TIMEOUT,
            )
            with open(WORKER_READY_FILE, 'w', encoding='utf-8') as marker:
                marker.write(f'pid={os.getpid()}\n')
            return cliente
        except Exception as exc:
            log.error(
                'WORKER_REDIS_ERROR intento=%s/%s destino=%s detalle=%s',
                intento, max_intentos, _redis_destino(), exc,
                exc_info=True,
            )
            if intento < max_intentos:
                time.sleep(espera)
    raise RuntimeError(
        f'El worker no pudo conectar con Redis después de {max_intentos} intentos. '
        f'Destino: {_redis_destino()}'
    )


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
    redis_client: Redis = _conectar_redis()
    queue_name = app.config['IMPORT_QUEUE_NAME']
    log.info(
        'WORKER_START pid=%s destino=%s cola=%s blpop_timeout=%ss socket_timeout=%ss',
        os.getpid(), _redis_destino(), queue_name,
        WORKER_BLPOP_TIMEOUT, WORKER_SOCKET_TIMEOUT,
    )
    while True:
        try:
            _nombre, job_id = (
                redis_client.blpop(queue_name, timeout=WORKER_BLPOP_TIMEOUT)
                or (None, None)
            )
        except RedisError as exc:
            log.error(
                'WORKER_REDIS_RUNTIME_ERROR destino=%s detalle=%s. Se reconectará.',
                _redis_destino(), exc, exc_info=True,
            )
            try:
                os.remove(WORKER_READY_FILE)
            except FileNotFoundError:
                pass
            try:
                redis_client.close()
            except RedisError:
                pass
            redis_client = _conectar_redis()
            continue
        if job_id:
            _procesar(job_id)


if __name__ == '__main__':
    main()
