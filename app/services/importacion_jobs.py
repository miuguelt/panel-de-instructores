"""Cola Redis para importaciones pesadas de reportes Excel."""

from __future__ import annotations

import os

import redis


class ColaImportacionesNoDisponible(RuntimeError):
    """Redis no está configurado o no acepta trabajos."""


def _cliente_redis(socket_timeout=3):
    """Crea y verifica un cliente Redis.

    Las publicaciones web usan un timeout corto. El worker pasa un timeout
    mayor que el BLPOP para que una cola vacía no se confunda con una caída de
    Redis.
    """
    redis_url = (os.getenv('REDIS_URL') or '').strip().strip('"').strip("'")
    if not redis_url or redis_url.startswith('memory://'):
        raise ColaImportacionesNoDisponible('REDIS_URL no está configurada para la cola.')
    cliente = None
    try:
        from app import _encode_redis_url
        redis_url = _encode_redis_url(redis_url)
        cliente = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=socket_timeout,
            health_check_interval=30,
        )
        # Redis.from_url() solo construye el cliente. El ping es obligatorio
        # para que el worker no muera después, sin diagnóstico, al ejecutar
        # BLPOP contra un host/puerto equivocado o con una contraseña inválida.
        cliente.ping()
        return cliente
    except Exception as exc:
        if cliente is not None:
            try:
                cliente.close()
            except Exception:
                pass
        destino = _redis_destino(redis_url)
        raise ColaImportacionesNoDisponible(
            f'Redis no responde en {destino}: {type(exc).__name__}: {exc}'
        ) from exc


def _redis_destino(redis_url=None):
    """Resume el endpoint Redis sin imprimir sus credenciales."""
    from urllib.parse import urlsplit

    raw = (redis_url if redis_url is not None else os.getenv('REDIS_URL') or '')
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return 'NO_DEFINIDO'
    try:
        from app import _encode_redis_url
        raw = _encode_redis_url(raw)
    except Exception:
        pass
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname or 'sin-host'
        port = parsed.port or (6379 if parsed.scheme in ('redis', 'rediss') else 'sin-puerto')
        return f'{parsed.scheme or "sin-scheme"}://{host}:{port}{parsed.path or ""}'
    except Exception as exc:
        return f'INVALIDO ({type(exc).__name__}: {exc})'


def encolar_importacion(job_id: int, queue_name: str) -> None:
    """Publica un ID de trabajo; el worker lo procesa de forma durable."""
    try:
        cliente = _cliente_redis()
        cliente.rpush(queue_name, str(job_id))
        cliente.close()
    except ColaImportacionesNoDisponible:
        raise
    except Exception as exc:
        raise ColaImportacionesNoDisponible(
            f'No se pudo publicar el trabajo en Redis: {exc}'
        ) from exc


def encolar_recalculo_resumen(ficha_id: int, instructor_id: int):
    """Encola el snapshot de una ficha después de aceptar sus documentos."""
    from datetime import datetime

    from flask import current_app

    from app import db
    from app.models import ImportacionJob

    trabajo = ImportacionJob(
        ficha_id=ficha_id,
        instructor_id=instructor_id,
        tipo_trabajo='resumen_ficha',
        archivo_path='',
        nombre_archivo='resumen calculado',
        estado='encolado',
    )
    db.session.add(trabajo)
    db.session.commit()
    try:
        encolar_importacion(trabajo.id, current_app.config['IMPORT_QUEUE_NAME'])
    except ColaImportacionesNoDisponible as exc:
        trabajo.estado = 'error'
        trabajo.error = str(exc)
        trabajo.terminado_en = datetime.utcnow()
        db.session.commit()
        current_app.logger.warning(
            'No se pudo encolar el resumen de ficha %s: %s', ficha_id, exc,
        )
    return trabajo
