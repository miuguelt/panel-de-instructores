"""Persistencia y consulta de versiones de archivos de una ficha."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from flask import current_app
from sqlalchemy import func
from werkzeug.utils import secure_filename

from app import db
from app.models.archivo_ficha import (
    ArchivoFichaVersion,
    TIPO_PLANEACION,
    TIPO_PROGRAMA,
    TIPO_REPORTE_JUICIOS,
)
from app.services.archivos import ArchivoDuplicado, ArchivoService


TIPOS_VERSIONADOS = {TIPO_PLANEACION, TIPO_REPORTE_JUICIOS, TIPO_PROGRAMA}
EXTENSION_POR_TIPO = {TIPO_PROGRAMA: '.pdf'}


def _hash_stream(stream):
    stream.seek(0)
    digest = hashlib.sha256()
    while True:
        bloque = stream.read(1024 * 1024)
        if not bloque:
            break
        digest.update(bloque)
    stream.seek(0)
    return digest.hexdigest()


def crear_version(archivo, ficha_id, instructor_id, tipo, metadata=None, permitir_existente=False):
    """Guarda un archivo en la ruta persistente y crea su registro de versión."""
    if tipo not in TIPOS_VERSIONADOS:
        raise ValueError(f'Tipo de archivo no soportado: {tipo}.')
    predeterminada = EXTENSION_POR_TIPO.get(tipo, '.xlsx')
    nombre_original = secure_filename(archivo.filename or '') or f'{tipo}{predeterminada}'
    extension = Path(nombre_original).suffix.lower() or predeterminada
    ultimo = db.session.query(func.max(ArchivoFichaVersion.version)).filter_by(
        ficha_id=ficha_id, tipo=tipo
    ).scalar() or 0
    numero_version = int(ultimo) + 1
    nombre_disco = f'v{numero_version}_{uuid4().hex}_{nombre_original}'
    carpeta = f'fichas/{ficha_id}/{tipo}'
    hash_sha256 = _hash_stream(archivo.stream)
    existente = ArchivoFichaVersion.query.filter_by(
        ficha_id=ficha_id,
        tipo=tipo,
        hash_sha256=hash_sha256,
    ).order_by(ArchivoFichaVersion.version.desc()).first()
    if existente:
        if permitir_existente:
            archivo.stream.seek(0)
            return existente
        raise ArchivoDuplicado(
            f'Este archivo ya fue cargado como versión {existente.version}; '
            'no se creó una versión duplicada.'
        )
    ruta = ArchivoService.guardar_crudo(
        archivo,
        carpeta=carpeta,
        nombre_archivo=nombre_disco,
    )
    tamano = Path(ruta).stat().st_size
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, default=str)
    version = ArchivoFichaVersion(
        ficha_id=ficha_id,
        instructor_id=instructor_id,
        tipo=tipo,
        version=numero_version,
        nombre_archivo=nombre_original,
        ruta_archivo=f'{carpeta}/{nombre_disco}',
        hash_sha256=hash_sha256,
        tamano_bytes=tamano,
        estado='pendiente',
        metadata_json=metadata_json,
    )
    db.session.add(version)
    db.session.flush()
    archivo.stream.seek(0)
    return version


def actualizar_estado(version, estado, detalle=None, metadata=None):
    version.estado = estado
    version.detalle = detalle
    if metadata is not None:
        version.metadata_json = json.dumps(metadata, ensure_ascii=False, default=str)


def versiones_ficha(ficha_id, tipo=None):
    consulta = ArchivoFichaVersion.query.filter_by(ficha_id=ficha_id)
    if tipo:
        consulta = consulta.filter_by(tipo=tipo)
    return consulta.order_by(
        ArchivoFichaVersion.tipo,
        ArchivoFichaVersion.version.desc(),
    ).all()


def ultima_version(ficha_id, tipo, solo_procesadas=False):
    consulta = ArchivoFichaVersion.query.filter_by(ficha_id=ficha_id, tipo=tipo)
    if solo_procesadas:
        consulta = consulta.filter(ArchivoFichaVersion.estado == 'procesado')
    return consulta.order_by(ArchivoFichaVersion.version.desc()).first()


def ruta_version(version):
    raiz = Path(current_app.config['UPLOAD_FOLDER']).resolve()
    ruta = (raiz / version.ruta_archivo).resolve()
    try:
        ruta.relative_to(raiz)
    except ValueError as exc:
        raise FileNotFoundError(version.ruta_archivo) from exc
    if not ruta.is_file():
        raise FileNotFoundError(version.ruta_archivo)
    return raiz, ruta.relative_to(raiz)
