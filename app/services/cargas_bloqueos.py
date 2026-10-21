"""Bloqueos de archivos entre procesos, compatibles con Windows y Linux."""

import os
from contextlib import contextmanager
from pathlib import Path

from flask import current_app

from app.services.cargas_errores import ErrorCarga


def directorio_privado():
    ruta = Path(current_app.config['UPLOAD_FOLDER']) / '.cargas'
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


@contextmanager
def bloquear(nombre):
    ruta = directorio_privado() / (nombre + '.lock')
    with open(ruta, 'a+b') as archivo:
        try:
            if os.fstat(archivo.fileno()).st_size == 0:
                archivo.write(b'0')
                archivo.flush()
            archivo.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(archivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ErrorCarga('carga_ocupada', 'La carga está atendiendo otra solicitud. Espere y vuelva a consultar.', 409) from exc
        try:
            yield
        finally:
            archivo.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(archivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(archivo, fcntl.LOCK_UN)
