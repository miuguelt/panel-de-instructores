"""Validación de preferencias, procesamiento de fotos y escritura con revisión."""

from copy import deepcopy
from io import BytesIO
import json
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app import db
from app.features.personalizacion_aprendiz.models import PersonalizacionAprendiz


DEFAULTS = {
    'avatar': '💻', 'accent': '#39a900', 'themeName': 'sena', 'motto': '',
    'alias': '', 'background': 'plain', 'sectionOrder': [], 'viewMode': 'tabs',
}
AVATARES = {'💻', '🚀', '⚡', '🎯', '🧠', '🎨', '🔬', '🦊', '🦁', '🦉', '🌟', '💡', '🛡️', '⚙️', '📚', '🏆'}
TEMAS = {
    'sena': '#39a900', 'indigo': '#2563eb', 'cyan': '#0891b2', 'purple': '#7c3aed',
    'amber': '#d97706', 'emerald': '#059669', 'rose': '#e11d48', 'slate': '#475569',
}
SECCIONES = {
    'seccion-progreso', 'seccion-portafolio-digital', 'seccion-grupo-trabajo',
    'seccion-juicios', 'seccion-aseo', 'seccion-curva-rendimiento',
    'seccion-ranking', 'seccion-liga-grupos', 'seccion-tareas',
}
MAX_FOTO_BYTES = 2 * 1024 * 1024
MAX_FOTO_PIXELES = 16_000_000


class ConflictoPersonalizacion(ValueError):
    """La revisión enviada ya fue reemplazada por otro guardado."""


class FotoDemasiadoGrande(ValueError):
    """La foto supera el tamaño permitido antes de procesarla."""


def validar_preferencias(texto):
    """Exige un objeto completo sin campos académicos ni valores fuera del catálogo."""
    if not isinstance(texto, str) or len(texto) > 8192:
        raise ValueError('Envía las preferencias del panel en un formato válido.')
    try:
        preferencias = json.loads(texto)
    except (ValueError, TypeError) as exc:
        raise ValueError('No se pudieron leer las preferencias. Vuelve a cargar el panel.') from exc
    if not isinstance(preferencias, dict) or set(preferencias) != set(DEFAULTS):
        raise ValueError('Las preferencias deben contener únicamente las opciones de personalización del panel.')
    for campo in ('avatar', 'accent', 'themeName', 'motto', 'alias', 'background', 'viewMode'):
        if not isinstance(preferencias[campo], str):
            raise ValueError('Cada opción de personalización debe tener el tipo de dato esperado.')
    if preferencias['avatar'] not in AVATARES:
        raise ValueError('Elige un avatar disponible en el panel.')
    if TEMAS.get(preferencias['themeName']) != preferencias['accent']:
        raise ValueError('Elige uno de los colores disponibles en el panel.')
    for campo, limite in (('motto', 80), ('alias', 30)):
        valor = preferencias[campo]
        if len(valor) > limite or any(ord(caracter) < 32 or ord(caracter) == 127 for caracter in valor):
            etiqueta = 'lema' if campo == 'motto' else 'alias'
            raise ValueError(f'El {etiqueta} debe tener hasta {limite} caracteres y no incluir caracteres de control.')
        preferencias[campo] = valor.strip()
    if preferencias['background'] not in ('plain', 'dots', 'grid'):
        raise ValueError('Elige un fondo disponible en el panel.')
    if preferencias['viewMode'] not in ('tabs', 'cascade'):
        raise ValueError('Elige una vista disponible en el panel.')
    orden = preferencias['sectionOrder']
    if (
        not isinstance(orden, list) or len(orden) > len(SECCIONES)
        or any(not isinstance(seccion, str) or seccion not in SECCIONES for seccion in orden)
        or len(set(orden)) != len(orden)
    ):
        raise ValueError('El orden del panel debe incluir secciones disponibles sin repetirlas.')
    return preferencias


def validar_revision(texto):
    """La revisión no admite negativos, decimales, booleanos ni desbordamiento SQL."""
    if not isinstance(texto, str) or not texto.isascii() or not texto.isdigit() or len(texto) > 10:
        raise ValueError('La revisión del panel no es válida. Vuelve a cargar la página.')
    revision = int(texto)
    if revision > 2_147_483_646:
        raise ValueError('La revisión del panel no es válida. Vuelve a cargar la página.')
    return revision


def normalizar_foto(archivo):
    """Comprueba los bytes reales y genera un JPEG sin metadatos de hasta 512 px."""
    contenido = archivo.stream.read(MAX_FOTO_BYTES + 1)
    if len(contenido) > MAX_FOTO_BYTES:
        raise FotoDemasiadoGrande('La foto supera 2 MiB. Reduce su tamaño y vuelve a intentarlo.')
    if not contenido:
        raise ValueError('La foto está vacía. Selecciona una imagen JPEG, PNG o WebP.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(contenido)) as imagen:
                if imagen.format not in ('JPEG', 'PNG', 'WEBP'):
                    raise ValueError('La foto debe ser una imagen JPEG, PNG o WebP.')
                if imagen.width * imagen.height > MAX_FOTO_PIXELES:
                    raise ValueError('La foto supera 16 megapíxeles. Reduce sus dimensiones.')
                imagen.verify()
            with Image.open(BytesIO(contenido)) as imagen:
                normalizada = ImageOps.exif_transpose(imagen).convert('RGBA')
                normalizada.thumbnail((512, 512), Image.Resampling.LANCZOS)
                fondo = Image.new('RGB', normalizada.size, 'white')
                fondo.paste(normalizada, mask=normalizada.getchannel('A'))
                salida = BytesIO()
                fondo.save(salida, 'JPEG', quality=85, optimize=True)
                return salida.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError('No se pudo leer la foto. Selecciona una imagen JPEG, PNG o WebP válida.') from exc


def obtener_personalizacion(aprendiz_id):
    """Consulta preferencias sin crear registros ni modificar la foto."""
    return db.session.get(PersonalizacionAprendiz, aprendiz_id, populate_existing=True)


def preferencias_publicas(registro):
    """Devuelve copias independientes para no alterar los valores persistidos o iniciales."""
    return deepcopy(registro.preferencias if registro else DEFAULTS)


def guardar_personalizacion(aprendiz_id, preferencias, revision, foto=None, quitar_foto=False):
    """Confirma un único guardado; una revisión obsoleta nunca sobrescribe datos."""
    if revision == 0:
        registro = PersonalizacionAprendiz(
            aprendiz_id=aprendiz_id, preferencias=preferencias, revision=1, foto=foto,
        )
        db.session.add(registro)
        try:
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            if obtener_personalizacion(aprendiz_id) is not None:
                raise ConflictoPersonalizacion(
                    'Tu panel cambió en otra sesión. Recarga las preferencias antes de guardar.'
                ) from exc
            raise
    else:
        valores = {'preferencias': preferencias, 'revision': revision + 1}
        if foto is not None or quitar_foto:
            valores['foto'] = None if quitar_foto else foto
        resultado = db.session.execute(
            update(PersonalizacionAprendiz)
            .where(PersonalizacionAprendiz.aprendiz_id == aprendiz_id,
                   PersonalizacionAprendiz.revision == revision)
            .values(**valores),
        )
        if resultado.rowcount != 1:
            db.session.rollback()
            raise ConflictoPersonalizacion(
                'Tu panel cambió en otra sesión. Recarga las preferencias antes de guardar.'
            )
        db.session.commit()
    return obtener_personalizacion(aprendiz_id)
