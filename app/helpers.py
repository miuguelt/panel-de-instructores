import re

from app.services.archivos import ArchivoService


_INSTRUCTOR_DOCUMENT_PATTERN = re.compile(
    r'^\s*(?:C\.?\s*C\.?|CC)\s*[:#-]?\s*'
    r'(?:\d[\d.\s-]*\d|\d+)\s*(?:[–—-]\s*|:\s*)?',
    re.IGNORECASE,
)
_LEADING_DOCUMENT_PATTERN = re.compile(
    r'^\s*\d[\d.\s-]{4,}\d\s*[–—-]\s*',
)


def strip_document_id(value):
    """Remove a leading instructor document number for public display."""
    if value is None:
        return value

    text = str(value).strip()
    cleaned = _INSTRUCTOR_DOCUMENT_PATTERN.sub('', text, count=1)
    if cleaned == text:
        cleaned = _LEADING_DOCUMENT_PATTERN.sub('', text, count=1)

    return cleaned.strip(' :\t-–—') or 'Instructor'


def obtener_tamanos_materiales(materiales, upload_folder):
    """Deprecated: usar ArchivoService.obtener_tamano() directo."""
    return {m.id: ArchivoService.obtener_tamano(m.url_archivo) for m in materiales}
