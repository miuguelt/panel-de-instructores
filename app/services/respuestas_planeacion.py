"""Contexto de ficha y respuestas HTTP del módulo de planeación."""

from flask import current_app, jsonify, redirect, request, url_for

from app import db
from app.models import Ficha
from app.services.permisos import puede_gestionar_ficha
from app.services.programa_formacion import parsear_programa
from app.services.resultados_persistidos import obtener_contenido_documento


def ficha_autorizada(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    return ficha if ficha and puede_gestionar_ficha(ficha) else None


def metadata_ficha(ficha):
    return {
        'codigo_programa': ficha.codigo_programa,
        'nombre_programa': ficha.nombre_programa,
    }


def mensaje_recuperacion(resultado):
    """Describe las fuentes recuperadas sin afirmar que se actualizó el análisis."""
    return (
        f'Se recuperaron exitosamente {resultado["total_nuevas"]} archivo(s): {", ".join(resultado["nuevas"])}.'
        if resultado['total_nuevas'] > 0
        else 'No se encontraron nuevos archivos para recuperar o ya están al día.'
    )


def programa_vigente(version_programa):
    """Lee el programa cargado sin interrumpir la vista si el PDF quedó ilegible."""
    if not version_programa:
        return None
    try:
        return obtener_contenido_documento(
            version_programa, parsear_programa, parser_version='programa-v1',
        )
    except Exception:
        current_app.logger.exception(
            'No se pudo leer el programa de formación de la versión %s', version_programa.id
        )
        return None


def es_xhr():
    """Indica si la subida fue interceptada por el cliente con XHR."""
    return request.headers.get('X-Requested-With', '').lower() == 'xmlhttprequest'


def respuesta_carga(ficha_id, ok, mensaje, status=200):
    """Devuelve JSON para la subida con progreso y redirección para HTML plano."""
    if es_xhr():
        cuerpo = {'ok': ok, 'message': mensaje}
        if ok:
            cuerpo['redirect'] = url_for('planeacion.analisis', ficha_id=ficha_id)
        return jsonify(cuerpo), status
    return redirect(url_for('planeacion.analisis', ficha_id=ficha_id))
