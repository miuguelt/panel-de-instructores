"""
Servicio centralizado de gestión de archivos.

SSOT para toda operación de subida, validación, descarga y eliminación
de archivos en el sistema. Toda ruta que maneje archivos DEBE usar este
servicio y no implementar su propia lógica de validación o almacenamiento.

Uso:
    from app.services.archivos import ArchivoService, TiposCarpeta

    resultado = ArchivoService.guardar(
        archivo=request.files['campo'],
        carpeta=TiposCarpeta.MATERIALES,
        subcarpeta=str(ficha_id),
        prefijo_extra=aprendiz.documento,
    )
    # resultado.url  -> "materiales_ficha/3/abc_original.pdf"
    # resultado.ruta -> "C:/.../uploads/materiales_ficha/3/abc_original.pdf"

Eliminación:
    ArchivoService.eliminar(url_relativa)
"""

from __future__ import annotations

import os
import struct
from enum import Enum
from pathlib import Path
from typing import Optional
from uuid import uuid4

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


class ErrorArchivo(Exception):
    """Error controlado en operaciones con archivos."""


class ErrorExtension(ErrorArchivo):
    """Extensión de archivo no permitida."""


class ErrorMimeType(ErrorArchivo):
    """Tipo MIME no coincide con la extensión declarada."""


class ErrorTamano(ErrorArchivo):
    """Archivo excede el límite de tamaño."""


class ErrorArchivoVacio(ErrorArchivo):
    """No se envió archivo o está vacío."""


# ---------------------------------------------------------------------------
# Mapa de extensión -> MIME type esperado (para validación por content-type)
# ---------------------------------------------------------------------------
MIME_POR_EXTENSION: dict[str, set[str]] = {
    'pdf': {'application/pdf'},
    'png': {'image/png'},
    'jpg': {'image/jpeg'},
    'jpeg': {'image/jpeg'},
    'zip': {'application/zip', 'application/x-zip-compressed'},
    'rar': {'application/vnd.rar', 'application/x-rar-compressed'},
    'xlsx': {'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
    'xls': {'application/vnd.ms-excel'},
    'doc': {'application/msword'},
    'docx': {'application/vnd.openxmlformats-officedocument.wordprocessingml.document'},
    'pptx': {'application/vnd.openxmlformats-officedocument.presentationml.presentation'},
    'ppt': {'application/vnd.ms-powerpoint'},
}

# ---------------------------------------------------------------------------
# Cabeceras mágicas (magic bytes) para validación de contenido real
# ---------------------------------------------------------------------------
# (bytes_iniciales, offset, extensiones)
_MAGIC: list[tuple[bytes, int, set[str]]] = [
    (b'%PDF', 0, {'pdf'}),
    (b'\x89PNG\r\n\x1a\n', 0, {'png'}),
    (b'\xff\xd8\xff', 0, {'jpg', 'jpeg'}),
    (b'PK\x03\x04', 0, {'zip', 'xlsx', 'docx', 'pptx'}),
    (b'PK\x03\x04', 0, {'zip'}),  # zip genérico
    (b'Rar!\x1a\x07', 0, {'rar'}),
    (b'Rar!\x1a\x07\x01\x00', 0, {'rar'}),
    (b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1', 0, {'xls', 'doc', 'ppt'}),
]

_MAX_MAGIC_READ = 32  # bytes a leer para detectar magic


def _magic_coincide(contenido: bytes, extension: str) -> bool:
    """Verifica si los primeros bytes del contenido corresponden a la extensión."""
    for firma, offset, extensiones in _MAGIC:
        if extension in extensiones:
            start = offset
            end = start + len(firma)
            if contenido[start:end] == firma:
                return True
    return False


def _extension_valida(extension: str) -> bool:
    """Valida contra la whitelist de config."""
    permitidas: set[str] = current_app.config.get('ALLOWED_EXTENSIONS', set())
    return extension in permitidas


# ---------------------------------------------------------------------------
# Subdirectorios canónicos (todos relativos a UPLOAD_FOLDER)
# ---------------------------------------------------------------------------
class TiposCarpeta(str, Enum):
    """Subdirectorios estandarizados dentro de UPLOAD_FOLDER."""
    MATERIALES_TAREA = 'materiales'
    MATERIALES_FICHA = 'materiales_ficha'
    ENTREGAS = 'entregas'
    JUSTIFICACIONES = 'justificaciones'

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Resultado de una operación de guardado
# ---------------------------------------------------------------------------
class ResultadoGuardar:
    """Objeto inmutable con el resultado de guardar un archivo."""
    __slots__ = ('url', 'ruta', 'nombre_original', 'nombre_archivo', 'tamano')

    def __init__(
        self,
        url: str,
        ruta: str,
        nombre_original: str,
        nombre_archivo: str,
        tamano: int,
    ):
        self.url = url
        self.ruta = ruta
        self.nombre_original = nombre_original
        self.nombre_archivo = nombre_archivo
        self.tamano = tamano


# ===================================================================
#  SERVICIO PÚBLICO
# ===================================================================
class ArchivoService:
    """Servicio único para operaciones con archivos subidos."""

    # ------------------------------------------------------------------
    # VALIDACIÓN
    # ------------------------------------------------------------------
    @staticmethod
    def validar_extension(archivo: FileStorage) -> str:
        """Valida que el archivo tenga una extensión permitida.

        Returns:
            La extensión en minúsculas (sin punto).

        Raises:
            ErrorArchivoVacio: Si no hay archivo o filename vacío.
            ErrorExtension: Si la extensión no está en ALLOWED_EXTENSIONS.
        """
        if not archivo or not archivo.filename:
            raise ErrorArchivoVacio('No se seleccionó ningún archivo.')

        ext = (
            archivo.filename.rsplit('.', 1)[-1].lower()
            if '.' in archivo.filename
            else ''
        )
        if not ext:
            raise ErrorExtension('El archivo no tiene extensión.')

        if not _extension_valida(ext):
            raise ErrorExtension(
                f'El tipo de archivo .{ext} no está permitido. '
                f'Extensiones aceptadas: {", ".join(sorted(current_app.config.get("ALLOWED_EXTENSIONS", set())))}.'
            )
        return ext

    @staticmethod
    def validar_mime(archivo: FileStorage, extension: str) -> None:
        """Valida que el Content-Type coincida con la extensión declarada.

        Esta validación es informativa (el cliente puede mentir en el header),
        pero ayuda a detectar errores evidentes.

        Raises:
            ErrorMimeType: Si el MIME no coincide.
        """
        if not archivo.content_type:
            return
        esperados = MIME_POR_EXTENSION.get(extension)
        if esperados and archivo.content_type not in esperados:
            raise ErrorMimeType(
                f'El tipo de contenido ({archivo.content_type}) no coincide '
                f'con la extensión .{extension}.'
            )

    @staticmethod
    def validar_magic_bytes(archivo: FileStorage, extension: str) -> None:
        """Valida la cabecera real del archivo contra la extensión.

        Lee hasta 32 bytes del stream y los compara contra firmas conocidas.
        Resetea el stream después de la lectura.

        Raises:
            ErrorArchivo: Si los magic bytes no coinciden.
        """
        archivo.stream.seek(0)
        contenido = archivo.stream.read(_MAX_MAGIC_READ)
        archivo.stream.seek(0)

        if not _magic_coincide(contenido, extension):
            raise ErrorArchivo(
                f'El contenido del archivo no corresponde a una extensión .{extension}. '
                'El archivo podría estar corrupto o tener una extensión incorrecta.'
            )

    @staticmethod
    def validar_no_vacio(archivo: FileStorage) -> None:
        """Verifica que el archivo tenga contenido.

        Raises:
            ErrorArchivoVacio: Si el archivo está vacío.
        """
        archivo.stream.seek(0, os.SEEK_END)
        tamano = archivo.stream.tell()
        archivo.stream.seek(0)
        if tamano == 0:
            raise ErrorArchivoVacio('El archivo está vacío.')

    @staticmethod
    def validar(archivo: FileStorage, check_mime: bool = True, check_magic: bool = True) -> str:
        """Valida un archivo completo contra todos los criterios.

        Args:
            archivo: El archivo subido.
            check_mime: Si se valida Content-Type header.
            check_magic: Si se validan magic bytes.

        Returns:
            La extensión validada en minúsculas.
        """
        ArchivoService.validar_no_vacio(archivo)
        ext = ArchivoService.validar_extension(archivo)
        if check_mime:
            ArchivoService.validar_mime(archivo, ext)
        if check_magic:
            ArchivoService.validar_magic_bytes(archivo, ext)
        return ext

    # ------------------------------------------------------------------
    # GENERACIÓN DE NOMBRE
    # ------------------------------------------------------------------
    @staticmethod
    def generar_nombre(archivo: FileStorage, prefijo_extra: str = '') -> str:
        """Genera un nombre único y seguro: [{extra}_]{uuid[:12]}_{nombre_original}

        Args:
            archivo: Archivo subido.
            prefijo_extra: Prefijo opcional (ej. documento del aprendiz).

        Returns:
            Nombre de archivo sanitizado con prefijo UUID.
        """
        nombre_original = secure_filename(archivo.filename)
        uuid_prefijo = uuid4().hex[:12]
        if prefijo_extra:
            return f'{prefijo_extra}_{uuid_prefijo}_{nombre_original}'
        return f'{uuid_prefijo}_{nombre_original}'

    # ------------------------------------------------------------------
    # GUARDADO
    # ------------------------------------------------------------------
    @staticmethod
    def guardar(
        archivo: FileStorage,
        carpeta: TiposCarpeta,
        subcarpeta: str = '',
        prefijo_extra: str = '',
        check_mime: bool = True,
        check_magic: bool = False,
    ) -> ResultadoGuardar:
        """Valida, genera nombre único y guarda un archivo en disco.

        Args:
            archivo: FileStorage de Flask (request.files['campo']).
            carpeta: Subdirectorio canónico (TiposCarpeta).
            subcarpeta: Subdirectorio adicional (ej. str(ficha_id)).
            prefijo_extra: Prefijo opcional en el nombre (ej. documento).
            check_mime: Validar Content-Type header.
            check_magic: Validar magic bytes (default False por rendimiento).

        Returns:
            ResultadoGuardar con url, ruta absoluta, nombre original y tamaño.

        Raises:
            ErrorArchivoVacio: Si no hay archivo.
            ErrorExtension: Extensión no permitida.
            ErrorMimeType: Content-Type no coincide.
            ErrorArchivo: Magic bytes no coinciden / otro error.
        """
        ext = ArchivoService.validar(archivo, check_mime=check_mime, check_magic=check_magic)

        nombre_original = secure_filename(archivo.filename)
        nombre_archivo = ArchivoService.generar_nombre(archivo, prefijo_extra)

        # Construir ruta
        partes = [current_app.config['UPLOAD_FOLDER'], str(carpeta)]
        if subcarpeta:
            partes.append(str(subcarpeta))
        directorio = os.path.join(*partes)
        os.makedirs(directorio, exist_ok=True)

        ruta_completa = os.path.join(directorio, nombre_archivo)
        archivo.save(ruta_completa)

        tamano = os.path.getsize(ruta_completa)

        # URL relativa (para BD)
        partes_url = [str(carpeta)]
        if subcarpeta:
            partes_url.append(str(subcarpeta))
        partes_url.append(nombre_archivo)
        url = '/'.join(partes_url)

        return ResultadoGuardar(
            url=url,
            ruta=ruta_completa,
            nombre_original=nombre_original,
            nombre_archivo=nombre_archivo,
            tamano=tamano,
        )

    # ------------------------------------------------------------------
    # ELIMINACIÓN
    # ------------------------------------------------------------------
    @staticmethod
    def eliminar(url_relativa: str) -> bool:
        """Elimina un archivo del disco dada su URL relativa.

        Args:
            url_relativa: Ruta relativa a UPLOAD_FOLDER (ej. 'materiales_ficha/3/file.pdf').

        Returns:
            True si se eliminó, False si no existía.
        """
        ruta = os.path.join(current_app.config['UPLOAD_FOLDER'], url_relativa)
        try:
            if os.path.isfile(ruta):
                os.remove(ruta)
                return True
            return False
        except OSError:
            current_app.logger.warning('No se pudo eliminar el archivo: %s', ruta)
            return False

    # ------------------------------------------------------------------
    # CONSULTA
    # ------------------------------------------------------------------
    @staticmethod
    def obtener_tamano(url_relativa: str) -> int:
        """Retorna el tamaño en bytes de un archivo subido, o 0 si no existe."""
        ruta = os.path.join(current_app.config['UPLOAD_FOLDER'], url_relativa)
        try:
            return os.path.getsize(ruta)
        except OSError:
            return 0

    @staticmethod
    def existe(url_relativa: str) -> bool:
        """Verifica si un archivo existe en disco."""
        ruta = os.path.join(current_app.config['UPLOAD_FOLDER'], url_relativa)
        return os.path.isfile(ruta)

    @staticmethod
    def ruta_absoluta(url_relativa: str) -> str:
        """Convierte URL relativa a ruta absoluta."""
        return os.path.join(current_app.config['UPLOAD_FOLDER'], url_relativa)


def resolver_archivo_subido(filename: str):
    """Resuelve una ruta histórica o actual dentro de ``UPLOAD_FOLDER``.

    Los registros antiguos pueden contener separadores Windows (``\\``),
    mientras que los nuevos usan URLs relativas con ``/``. La validación se
    hace después de normalizar ambos formatos y siempre exige que el archivo
    permanezca dentro de la carpeta de cargas.

    Raises:
        FileNotFoundError: Si la ruta sale de uploads o el archivo no existe.
    """
    raiz = Path(current_app.config['UPLOAD_FOLDER']).resolve()
    valor = str(filename or '').strip()
    if not valor:
        raise FileNotFoundError(filename)

    valor_normalizado = valor.replace('\\', os.sep).replace('/', os.sep)
    solicitada = Path(valor_normalizado)
    destino = solicitada.resolve() if solicitada.is_absolute() else (raiz / solicitada).resolve()
    try:
        relativa = destino.relative_to(raiz)
    except ValueError as exc:
        raise FileNotFoundError(filename) from exc
    if not destino.is_file():
        raise FileNotFoundError(filename)

    candidatos = {
        valor,
        str(destino),
        str(relativa),
        relativa.as_posix(),
        str(relativa).replace('\\', '/'),
        str(relativa).replace('/', '\\'),
    }
    return raiz, relativa, candidatos
