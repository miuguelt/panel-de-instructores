"""Vistas de contraste entre planeación pedagógica y juicios evaluativos."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import db
from app.models import (
    ArchivoFichaVersion,
    ETIQUETAS_TIPO,
    Ficha,
    TIPO_PLANEACION,
    TIPO_PROGRAMA,
    TIPO_REPORTE_JUICIOS,
)
from app.services.archivos import ArchivoService, ErrorArchivo, resolver_archivo_subido
from app.services.carga_documentos import procesar_carga_unificada
from app.services.importacion_ficha import ErrorImportacion
from app.services.panorama_planeacion import construir_panorama
from app.services.permisos import puede_gestionar_ficha
from app.services.planeacion import comparar_fuentes, parsear_planeacion
from app.services.programa_formacion import parsear_programa
from app.services.versiones_archivos import (
    actualizar_estado,
    crear_version,
    ultima_version,
    versiones_ficha,
)


planeacion_bp = Blueprint('planeacion', __name__)


def _ficha_autorizada(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    return ficha if ficha and puede_gestionar_ficha(ficha) else None


def _metadata_ficha(ficha):
    return {
        'codigo_programa': ficha.codigo_programa,
        'nombre_programa': ficha.nombre_programa,
    }


def _programa_vigente(version_programa):
    """Lee el programa cargado sin tumbar la vista si el PDF quedó ilegible."""
    if not version_programa:
        return None
    try:
        ruta = Path(current_app.config['UPLOAD_FOLDER']) / version_programa.ruta_archivo
        return parsear_programa(ruta)
    except Exception:
        current_app.logger.exception(
            'No se pudo leer el programa de formación de la versión %s', version_programa.id
        )
        return None


def _es_xhr():
    """Indica si la subida fue interceptada por el cliente con XHR."""
    return request.headers.get('X-Requested-With', '').lower() == 'xmlhttprequest'


def _respuesta_carga(ficha_id, ok, mensaje, status=200):
    """Devuelve JSON para la subida con progreso y redirect para HTML plano."""
    if _es_xhr():
        cuerpo = {'ok': ok, 'message': mensaje}
        if ok:
            cuerpo['redirect'] = url_for('planeacion.analisis', ficha_id=ficha_id)
        return jsonify(cuerpo), status
    return redirect(url_for('planeacion.analisis', ficha_id=ficha_id))


@planeacion_bp.route('/fichas/<int:ficha_id>/planeacion')
@login_required
def analisis(ficha_id):
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    version_planeacion = ultima_version(ficha_id, TIPO_PLANEACION, solo_procesadas=True)
    version_reporte = ultima_version(ficha_id, TIPO_REPORTE_JUICIOS, solo_procesadas=True)
    version_programa = ultima_version(ficha_id, TIPO_PROGRAMA, solo_procesadas=True)
    programa = _programa_vigente(version_programa)
    contenido = None
    panorama = None
    error_planeacion = None
    if version_planeacion:
        try:
            ruta = Path(current_app.config['UPLOAD_FOLDER']) / version_planeacion.ruta_archivo
            contenido = parsear_planeacion(ruta)
            panorama = construir_panorama(
                ficha,
                contenido,
                version_planeacion=version_planeacion,
                version_reporte=version_reporte,
                programa=programa,
            )
        except (OSError, ValueError, KeyError) as exc:
            error_planeacion = f'No se pudo leer la última planeación: {exc}'
        except Exception:
            # Un Excel válido no debe tumbar toda la pantalla por una celda
            # inesperada o por una variación de datos importados. Se deja el
            # detalle en logs y se conserva el historial descargable.
            current_app.logger.exception(
                'Error inesperado al construir el análisis de la planeación de la ficha %s',
                ficha_id,
            )
            error_planeacion = (
                'No se pudo construir el análisis de la última planeación. '
                'La versión cargada se conserva; revisa el log del servidor o vuelve a cargar el archivo.'
            )

    return render_template(
        'instructor/planeacion.html',
        ficha=ficha,
        analisis=panorama.get('analisis') if panorama else None,
        calendario=panorama.get('calendario') if panorama else None,
        linea=panorama.get('linea') if panorama else None,
        proyeccion=panorama.get('proyeccion') if panorama else None,
        diagnostico=panorama.get('diagnostico', []) if panorama else [],
        veredicto=panorama.get('veredicto') if panorama else None,
        contraste=panorama.get('contraste') if panorama else None,
        catalogo_pedagogico=panorama.get('catalogo_pedagogico', {}) if panorama else {},
        desempeno_ficha=panorama.get('desempeno_ficha') if panorama else None,
        radar=panorama.get('radar') if panorama else None,
        heatmap_docente=panorama.get('heatmap_docente') if panorama else None,
        curva_svg=panorama.get('curva_svg') if panorama else None,
        fases_progreso=panorama.get('fases_progreso', []) if panorama else [],
        programa=programa,
        version_programa=version_programa,
        contenido_planeacion=contenido,
        version_planeacion=version_planeacion,
        version_reporte=version_reporte,
        # Última carga de cada tipo sin importar su estado: la tarjeta de
        # subida debe permitir descargar lo cargado aunque no se haya procesado.
        carga_planeacion=ultima_version(ficha_id, TIPO_PLANEACION),
        carga_reporte=ultima_version(ficha_id, TIPO_REPORTE_JUICIOS),
        carga_programa=ultima_version(ficha_id, TIPO_PROGRAMA),
        versiones=versiones_ficha(ficha_id),
        etiquetas_tipo=ETIQUETAS_TIPO,
        error_planeacion=error_planeacion,
        importacion_id=request.args.get('importacion_id', type=int),
        hoy=panorama.get('hoy') if panorama else None,
    )


@planeacion_bp.route('/fichas/<int:ficha_id>/planeacion/cargar', methods=['POST'])
@login_required
def cargar_planeacion(ficha_id):
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    archivo = request.files.get('archivo_planeacion')
    if not archivo or not archivo.filename.lower().endswith('.xlsx'):
        mensaje = 'Selecciona la planeación pedagógica en formato .xlsx.'
        flash(mensaje, 'error')
        return _respuesta_carga(ficha_id, False, mensaje, status=422)

    version = None
    try:
        version = crear_version(archivo, ficha_id, current_user.id, TIPO_PLANEACION)
        ruta = Path(current_app.config['UPLOAD_FOLDER']) / version.ruta_archivo
        contenido = parsear_planeacion(ruta)
        alineacion = comparar_fuentes(contenido['metadata'], _metadata_ficha(ficha))
        motivos_alineacion = list(alineacion['motivos'])
        if not alineacion['codigo_planeacion']:
            motivos_alineacion.append('La planeación no contiene el código del programa.')
        if not alineacion['codigo_ficha']:
            motivos_alineacion.append(
                f'La ficha {ficha.codigo} no tiene registrado el código del programa; complétalo antes de cargar la planeación.'
            )
        if motivos_alineacion:
            raise ErrorImportacion(
                f'Carga bloqueada para proteger los datos. La planeación pedagógica no '
                f'corresponde a la ficha {ficha.codigo}: '
                + ' '.join(motivos_alineacion)
            )
        actualizar_estado(version, 'procesado', metadata=contenido['metadata'])
        db.session.commit()
        mensaje = (
            f'Planeación cargada como versión {version.version}. '
            f'Se identificaron {contenido["resumen"]["resultados"]} resultados y '
            f'{contenido["resumen"]["horas_total"]:g} horas planificadas.'
        )
        flash(mensaje, 'success')
        return _respuesta_carga(ficha_id, True, mensaje)
    except (ErrorArchivo, ErrorImportacion, ValueError, OSError) as exc:
        db.session.rollback()
        if version:
            ArchivoService.eliminar(version.ruta_archivo)
        mensaje = f'No fue posible cargar la planeación: {exc}'
        flash(mensaje, 'error')
        return _respuesta_carga(ficha_id, False, mensaje, status=422)
    except Exception:
        db.session.rollback()
        if version:
            ArchivoService.eliminar(version.ruta_archivo)
        current_app.logger.exception('Error inesperado al cargar la planeación')
        mensaje = (
            'No fue posible cargar la planeación porque el servidor encontró un error. '
            'El archivo no se agregó al historial; revisa el log y vuelve a intentarlo.'
        )
        flash(mensaje, 'error')
        return _respuesta_carga(ficha_id, False, mensaje, status=500)


@planeacion_bp.route('/fichas/<int:ficha_id>/planeacion/programa', methods=['POST'])
@login_required
def cargar_programa(ficha_id):
    """Guarda el PDF del diseño curricular oficial que valida la planeación."""
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    archivo = request.files.get('archivo_programa')
    if not archivo or not archivo.filename.lower().endswith('.pdf'):
        mensaje = 'Selecciona el Programa de Formación en formato .pdf.'
        flash(mensaje, 'error')
        return _respuesta_carga(ficha_id, False, mensaje, status=422)

    version = None
    try:
        version = crear_version(archivo, ficha_id, current_user.id, TIPO_PROGRAMA)
        ruta = Path(current_app.config['UPLOAD_FOLDER']) / version.ruta_archivo
        programa = parsear_programa(ruta)
        alineacion = comparar_fuentes(programa['metadata'], _metadata_ficha(ficha))
        if not alineacion['alineado']:
            raise ErrorImportacion(
                'Carga bloqueada para proteger los datos. El programa cargado no '
                'corresponde al de la ficha: ' + ' '.join(alineacion['motivos'])
            )
        actualizar_estado(version, 'procesado', metadata=programa['metadata'])
        db.session.commit()
        mensaje = (
            f'Programa de formación cargado como versión {version.version}. '
            f'Se leyeron {programa["resumen"]["competencias"]} competencias, '
            f'{programa["resumen"]["resultados"]} resultados y '
            f'{programa["resumen"]["horas_lectivas_declaradas"]:g} horas lectivas.'
        )
        flash(mensaje, 'success')
        return _respuesta_carga(ficha_id, True, mensaje)
    except (ErrorArchivo, ErrorImportacion, ValueError, OSError) as exc:
        db.session.rollback()
        if version:
            ArchivoService.eliminar(version.ruta_archivo)
        mensaje = f'No fue posible cargar el programa de formación: {exc}'
        flash(mensaje, 'error')
        return _respuesta_carga(ficha_id, False, mensaje, status=422)
    except Exception:
        db.session.rollback()
        if version:
            ArchivoService.eliminar(version.ruta_archivo)
        current_app.logger.exception('Error inesperado al cargar el programa de formación')
        mensaje = (
            'No fue posible cargar el programa porque el servidor encontró un error. '
            'El archivo no se agregó al historial; revisa el log y vuelve a intentarlo.'
        )
        flash(mensaje, 'error')
        return _respuesta_carga(ficha_id, False, mensaje, status=500)


@planeacion_bp.route('/fichas/<int:ficha_id>/planeacion/cargar-todo', methods=['POST'])
@login_required
def cargar_todo(ficha_id):
    """Carga y procesa uno, dos o los tres documentos en una sola acción."""
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    ok, mensaje, status = procesar_carga_unificada(ficha, current_user.id, request.files)
    flash(mensaje, 'success' if ok else 'error')
    return _respuesta_carga(ficha_id, ok, mensaje, status=status)


@planeacion_bp.route('/fichas/<int:ficha_id>/planeacion/descargar-todos')
@login_required
def descargar_todos(ficha_id):
    """Descarga en un archivo .zip todas las fuentes vigentes cargadas para la ficha."""
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    version_plan = ultima_version(ficha_id, TIPO_PLANEACION)
    version_rep = ultima_version(ficha_id, TIPO_REPORTE_JUICIOS)
    version_prog = ultima_version(ficha_id, TIPO_PROGRAMA)

    docs = [v for v in (version_plan, version_rep, version_prog) if v]
    if not docs:
        flash('No hay archivos cargados para descargar en esta ficha.', 'warning')
        return redirect(url_for('planeacion.analisis', ficha_id=ficha_id))

    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for ver in docs:
            try:
                raiz, relativa, _ = resolver_archivo_subido(ver.ruta_archivo)
                ruta_fisica = raiz / relativa
                nombre_en_zip = f'v{ver.version}_{secure_filename(ver.nombre_archivo)}'
                zf.write(ruta_fisica, arcname=nombre_en_zip)
            except Exception:
                current_app.logger.warning('No se pudo incluir en ZIP la versión %s de la ficha %s', ver.id, ficha_id)

    buffer.seek(0)
    nombre_zip = f'fuentes_ficha_{secure_filename(ficha.codigo or str(ficha.id))}.zip'
    from flask import send_file
    return send_file(
        buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=nombre_zip,
    )


@planeacion_bp.route('/fichas/<int:ficha_id>/planeacion/archivos/<int:version_id>/descargar')
@login_required
def descargar_version(ficha_id, version_id):
    ficha = _ficha_autorizada(ficha_id)
    version = db.session.get(ArchivoFichaVersion, version_id)
    if not ficha or not version or version.ficha_id != ficha_id:
        flash('Archivo no encontrado.', 'error')
        return redirect(url_for('planeacion.analisis', ficha_id=ficha_id))
    try:
        raiz, relativa, _candidatos = resolver_archivo_subido(version.ruta_archivo)
        nombre = f'v{version.version}_{secure_filename(version.nombre_archivo)}'
        return ArchivoService.enviar(raiz, relativa, nombre_descarga=nombre)
    except FileNotFoundError:
        flash('La versión ya no está disponible en el almacenamiento.', 'error')
        return redirect(url_for('planeacion.analisis', ficha_id=ficha_id))

