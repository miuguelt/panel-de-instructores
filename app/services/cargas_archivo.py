"""Adaptación de referencias verificadas al servicio único de archivos."""

import json
import os
import shutil
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.services.cargas_bloqueos import directorio_privado
from app.services.cargas_errores import ErrorCarga


class ArchivoReanudable(FileStorage):
    def __init__(self, carga):
        self.carga_id = carga.id
        self._limite_verificado = current_app.config['MAX_RESUMABLE_UPLOAD_BYTES']
        self.hash_sha256_verificado = carga.hash_sha256
        self.ruta_carga = directorio_privado() / (carga.id + '.part')
        if not self.ruta_carga.is_file() or self.ruta_carga.stat().st_size != carga.tamano:
            raise ErrorCarga('archivo_incompleto', 'No se pudo verificar el archivo guardado. Informe al administrador.', 500)
        super().__init__(stream=open(self.ruta_carga, 'rb'), filename=carga.nombre,
                         content_type=carga.tipo, content_length=carga.tamano)

    def save(self, dst, buffer_size=1024 * 1024):
        """Publica un enlace atómico; conserva el temporal para recuperarse."""
        destino = Path(dst).resolve()
        raiz = Path(current_app.config['UPLOAD_FOLDER']).resolve()
        relativa = destino.relative_to(raiz).as_posix()
        diario = directorio_privado() / (self.carga_id + '.json')
        enlaces = json.loads(diario.read_text(encoding='utf-8')) if diario.exists() else []
        if relativa not in enlaces:
            enlaces.append(relativa)
        parcial = diario.with_suffix('.json.tmp')
        with open(parcial, 'w', encoding='utf-8') as archivo:
            json.dump(enlaces, archivo)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(parcial, diario)
        try:
            os.link(self.ruta_carga, destino)
        except FileExistsError:
            raise
        except OSError:
            if shutil.disk_usage(raiz).free < self.content_length + current_app.config['CARGAS_RESERVA_BYTES']:
                raise ErrorCarga('sin_espacio', 'El servidor no tiene espacio para confirmar el archivo.', 507)
            self.stream.seek(0)
            with open(destino, 'xb') as archivo:
                shutil.copyfileobj(self.stream, archivo, buffer_size)
                archivo.flush()
                os.fsync(archivo.fileno())
