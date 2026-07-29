"""Cola Redis para importaciones pesadas de reportes Excel."""

from __future__ import annotations

import os

import redis


class ColaImportacionesNoDisponible(RuntimeError):
    """Redis no está configurado o no acepta trabajos."""


def _cliente_redis():
    redis_url = (os.getenv('REDIS_URL') or '').strip().strip('"').strip("'")
    if not redis_url or redis_url.startswith('memory://'):
        raise ColaImportacionesNoDisponible('REDIS_URL no está configurada para la cola.')
    try:
        from app import _encode_redis_url
        redis_url = _encode_redis_url(redis_url)
        return redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    except Exception as exc:
        raise ColaImportacionesNoDisponible(str(exc)) from exc


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
