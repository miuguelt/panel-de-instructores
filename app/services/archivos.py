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
import re
from enum import Enum
from pathlib import Path
from uuid import uuid4

from flask import current_app, send_from_directory
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
    # Contenedores ZIP sin entradas o divididos en volúmenes: no empiezan con
    # la firma de registro local. Sin estas dos firmas, `check_magic` rechaza
    # archivos válidos que Office y los compresores generan de forma legítima.
    (b'PK\x05\x06', 0, {'zip', 'xlsx', 'docx', 'pptx'}),
    (b'PK\x07\x08', 0, {'zip', 'xlsx', 'docx', 'pptx'}),
    (b'Rar!\x1a\x07', 0, {'rar'}),
    (b'Rar!\x1a\x07\x01\x00', 0, {'rar'}),
    (b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1', 0, {'xls', 'doc', 'ppt'}),
]

# 1 KB en vez de 32 B: algunos PDF válidos traen basura o un BOM antes de
# '%PDF' y con una lectura de 32 bytes se rechazaban como corruptos.
_MAX_MAGIC_READ = 1024

# Extensiones que el navegador puede abrir embebidas sin riesgo de ejecutar
# script en el origen de la aplicación. Cualquier otra se fuerza como adjunto
# aunque la vista pida `inline=1`.
EXTENSIONES_INLINE: set[str] = {'png', 'jpg', 'jpeg', 'pdf'}

# `{prefijo_}{uuid12}_{nombre original}`: se usa para devolverle al usuario el
# nombre con el que subió el archivo en vez del nombre técnico del disco.
_PREFIJO_TECNICO = re.compile(r'(?:^|_)[0-9a-f]{12}_')


def _magic_coincide(contenido: bytes, extension: str) -> bool:
    """Verifica si los primeros bytes del contenido corresponden a la extensión."""
    if extension == 'pdf':
        # La cabecera puede estar desplazada; la especificación solo exige que
        # aparezca al principio del archivo, no en el byte 0 exacto.
        return b'%PDF' in contenido
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


def _borrar_silencioso(ruta: str) -> None:
    """Elimina un archivo temporal ignorando que ya no exista."""
    try:
        os.remove(ruta)
    except OSError:
        pass


def mimetype_de(extension: str) -> str:
    """MIME canónico de una extensión permitida.

    No se delega en el módulo `mimetypes`: la imagen base `python:3.12-slim` no
    trae la tabla completa de `/etc/mime.types`, así que docx/xlsx/pptx salían
    como `application/octet-stream` y algunos navegadores móviles se negaban a
    abrir el archivo descargado.
    """
    esperados = MIME_POR_EXTENSION.get((extension or '').lower())
    if not esperados:
        return 'application/octet-stream'
    return sorted(esperados)[0]


def nombre_original_desde_ruta(nombre_archivo: str) -> str:
    """Recupera el nombre legible quitando el prefijo técnico del disco.

    'tarea_9_ab12cd34ef56_Guia_JEE.docx' -> 'Guia_JEE.docx'
    """
    valor = Path(str(nombre_archivo or '')).name
    coincidencia = _PREFIJO_TECNICO.search(valor)
    if not coincidencia:
        return valor
    return valor[coincidencia.end():] or valor


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
        check_magic: bool = True,
    ) -> ResultadoGuardar:
        """Valida, genera nombre único y guarda un archivo en disco.

        La escritura es atómica: el contenido va primero a `<nombre>.part` y
        solo se renombra al destino final si llegó completo y con tamaño mayor
        que cero. Así una subida cortada (red del aprendiz, worker reciclado por
        gunicorn) nunca deja en `uploads/` un archivo de 0 bytes que la BD dé
        por bueno y que después se descargue vacío.

        Args:
            archivo: FileStorage de Flask (request.files['campo']).
            carpeta: Subdirectorio canónico (TiposCarpeta).
            subcarpeta: Subdirectorio adicional (ej. str(ficha_id)).
            prefijo_extra: Prefijo opcional en el nombre (ej. documento).
            check_mime: Validar Content-Type header.
            check_magic: Validar magic bytes.

        Returns:
            ResultadoGuardar con url, ruta absoluta, nombre original y tamaño.

        Raises:
            ErrorArchivoVacio: Si no hay archivo o llegó vacío.
            ErrorExtension: Extensión no permitida.
            ErrorMimeType: Content-Type no coincide.
            ErrorTamano: El archivo supera MAX_CONTENT_LENGTH.
            ErrorArchivo: Magic bytes no coinciden / fallo de escritura.
        """
        ext = ArchivoService.validar(archivo, check_mime=check_mime, check_magic=check_magic)

        nombre_original = secure_filename(archivo.filename)
        nombre_archivo = ArchivoService.generar_nombre(archivo, prefijo_extra)

        # Construir ruta
        partes = [current_app.config['UPLOAD_FOLDER'], str(carpeta)]
        if subcarpeta:
            partes.append(str(subcarpeta))
        directorio = os.path.join(*partes)
        try:
            os.makedirs(directorio, exist_ok=True)
        except OSError as exc:
            current_app.logger.error('No se pudo crear %s: %s', directorio, exc)
            raise ErrorArchivo(
                'El servidor no pudo preparar la carpeta de destino. '
                'Avisa a tu instructor e inténtalo de nuevo.'
            ) from exc

        ruta_completa = os.path.join(directorio, nombre_archivo)
        ruta_parcial = f'{ruta_completa}.part'
        limite = current_app.config.get('MAX_CONTENT_LENGTH') or 0

        try:
            archivo.stream.seek(0)
            archivo.save(ruta_parcial)
            tamano = os.path.getsize(ruta_parcial)
            if tamano == 0:
                raise ErrorArchivoVacio(
                    'El archivo llegó vacío al servidor. '
                    'Revisa tu conexión y vuelve a subirlo.'
                )
            if limite and tamano > limite:
                raise ErrorTamano(
                    f'El archivo pesa {tamano // (1024 * 1024)} MB y el máximo '
                    f'permitido es {limite // (1024 * 1024)} MB.'
                )
            os.replace(ruta_parcial, ruta_completa)
        except ErrorArchivo:
            _borrar_silencioso(ruta_parcial)
            raise
        except OSError as exc:
            _borrar_silencioso(ruta_parcial)
            current_app.logger.error('Fallo al escribir %s: %s', ruta_completa, exc)
            raise ErrorArchivo(
                'El servidor no pudo guardar el archivo. Inténtalo de nuevo.'
            ) from exc

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

    @staticmethod
    def guardar_crudo(
        archivo: FileStorage,
        carpeta: str,
        nombre_archivo: str,
    ) -> str:
        """Guarda un archivo sin la validación de extensión del estándar.

        Es la puerta para las importaciones Excel, que se procesan por su
        contenido y no encajan en `TiposCarpeta`. Conserva lo que sí es
        innegociable: escritura atómica y rechazo de un archivo vacío, para que
        el worker nunca abra un `.xls` truncado que el navegador dejó a medias.

        Returns:
            Ruta absoluta del archivo ya confirmado en disco.

        Raises:
            ErrorArchivoVacio: El archivo llegó vacío.
            ErrorArchivo: Fallo de escritura.
        """
        destino = os.path.join(current_app.config['UPLOAD_FOLDER'], carpeta)
        ruta_completa = os.path.join(destino, nombre_archivo)
        ruta_parcial = f'{ruta_completa}.part'
        try:
            os.makedirs(destino, exist_ok=True)
            archivo.stream.seek(0)
            archivo.save(ruta_parcial)
            if os.path.getsize(ruta_parcial) == 0:
                raise ErrorArchivoVacio(
                    'El archivo llegó vacío al servidor. '
                    'Revisa tu conexión y vuelve a subirlo.'
                )
            os.replace(ruta_parcial, ruta_completa)
        except ErrorArchivo:
            _borrar_silencioso(ruta_parcial)
            raise
        except OSError as exc:
            _borrar_silencioso(ruta_parcial)
            current_app.logger.error('Fallo al escribir %s: %s', ruta_completa, exc)
            raise ErrorArchivo(
                'El servidor no pudo guardar el archivo. Inténtalo de nuevo.'
            ) from exc
        return ruta_completa

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

    # ------------------------------------------------------------------
    # ENVÍO AL NAVEGADOR
    # ------------------------------------------------------------------
    @staticmethod
    def enviar(
        raiz,
        relativa: Path,
        nombre_descarga: str = '',
        inline: bool = False,
    ):
        """Devuelve la respuesta de descarga de un archivo ya resuelto.

        Punto único para toda descarga de `uploads/`. Frente al
        `send_from_directory` suelto que había en cada ruta añade:

        - `conditional=True`: emite ETag/Last-Modified y atiende `Range`, así
          una evidencia grande se reanuda en vez de reiniciarse, y una
          revisita responde 304 sin releer el archivo.
        - `download_name` legible: el aprendiz recibe `Guia_JEE.docx`, no el
          nombre técnico con UUID.
        - MIME explícito por extensión + `nosniff`, y `inline` limitado a
          imágenes y PDF: ningún adjunto se interpreta como HTML en el origen
          de la aplicación.
        - `Cache-Control: private`: los adjuntos nunca quedan en cachés
          intermedias compartidas (Traefik/Coolify).

        Args:
            raiz: Carpeta raíz de uploads (de `resolver_archivo_subido`).
            relativa: Ruta relativa dentro de la raíz.
            nombre_descarga: Nombre visible; por defecto el original inferido.
            inline: Pedir vista embebida (solo se concede a EXTENSIONES_INLINE).
        """
        extension = relativa.suffix.lstrip('.').lower()
        embebido = bool(inline) and extension in EXTENSIONES_INLINE
        nombre = nombre_descarga or nombre_original_desde_ruta(relativa.name)

        ruta_absoluta = Path(raiz) / relativa
        try:
            if ruta_absoluta.stat().st_size == 0:
                # No se aborta: el registro existe y el instructor debe poder
                # ver que el archivo quedó vacío. Pero sí queda en el log con
                # la ruta exacta para poder pedir la resubida.
                current_app.logger.warning(
                    'Descarga de archivo vacío (0 bytes): %s', relativa.as_posix()
                )
        except OSError:
            pass

        respuesta = send_from_directory(
            str(raiz),
            relativa.as_posix(),
            as_attachment=not embebido,
            download_name=nombre,
            mimetype=mimetype_de(extension),
            conditional=True,
            max_age=0,
        )
        respuesta.headers['X-Content-Type-Options'] = 'nosniff'
        respuesta.headers['Cache-Control'] = 'private, max-age=0, must-revalidate'
        return respuesta


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
