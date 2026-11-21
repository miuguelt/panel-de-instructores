"""Carga de Excel de la ficha, estado de importación y plantilla."""
import json
from pathlib import Path

import openpyxl
from flask import current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

import app.routes.instructor as _pkg
from app import db
from app.helpers import utc_now
from app.models.archivo_ficha import TIPO_REPORTE_JUICIOS, ArchivoFichaVersion
from app.models.ficha import Ficha
from app.models.importacion import ImportacionJob
from app.services.alertas import notificar_juicios_importados
from app.services.archivos import ArchivoService, ErrorArchivo
from app.services.importacion_ficha import (
    ErrorImportacion,
    es_reporte_oficial,
    leer_metadata_archivo,
    validar_reporte_ficha,
)
from app.services.importacion_jobs import (
    ColaImportacionesNoDisponible,
    encolar_importacion,
)
from app.services.permisos import configurar_rol_aprendiz, puede_gestionar_ficha
from app.services.versiones_archivos import (
    actualizar_estado,
)

from . import _actualizar_indicadores_carga, instructor_bp
from .fichas import _resumen_importacion


@instructor_bp.route('/fichas/<int:ficha_id>/cargar-excel', methods=['POST'])
@login_required
def cargar_excel(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    archivo = request.files.get('archivo')
    if not archivo or not archivo.filename.lower().endswith(('.xlsx', '.xls')):
        flash('Debes subir un archivo Excel (.xlsx o .xls).', 'error')
        return redirect(url_for('instructor.aprendices', ficha_id=ficha_id))

    importacion_job_id = None
    version = None
    archivos_creados = []
    ruta_temporal = None
    volver_planeacion = request.form.get('retorno') == 'planeacion'
    volver_juicios = request.form.get('retorno') == 'juicios'
    aprendiz_admin_id = request.form.get('aprendiz_administrativo_id', type=int)
    try:
        metadata_reporte = leer_metadata_archivo(archivo)
        if es_reporte_oficial(metadata_reporte):
            validar_reporte_ficha(ficha, metadata_reporte)
        version = _pkg.crear_version(
            archivo,
            ficha.id,
            current_user.id,
            TIPO_REPORTE_JUICIOS,
            metadata=metadata_reporte,
            permitir_existente=True,
            archivos_creados=archivos_creados,
        )
        if current_app.config.get('IMPORTACIONES_ASINCRONAS'):
            archivo.stream.seek(0)
            nombre_archivo = secure_filename(archivo.filename) or 'reporte.xls'
            # Dentro de UPLOAD_FOLDER porque el worker corre en otro contenedor
            # y solo comparte con el web el volumen `uploads`.
            ruta = str(Path(current_app.config['UPLOAD_FOLDER']) / version.ruta_archivo)

            job = ImportacionJob(
                ficha_id=ficha.id,
                instructor_id=current_user.id,
                archivo_version_id=version.id,
                archivo_path=ruta,
                nombre_archivo=nombre_archivo,
                estado='encolado',
                aprendiz_administrativo_id=aprendiz_admin_id,
            )
            db.session.add(job)
            db.session.commit()
            archivos_creados.clear()
            ruta_temporal = None
            importacion_job_id = job.id
            try:
                encolar_importacion(job.id, current_app.config['IMPORT_QUEUE_NAME'])
            except ColaImportacionesNoDisponible as exc:
                db.session.rollback()
                # El trabajo apunta al original versionado; no es un temporal.
                job = db.session.get(ImportacionJob, job.id)
                if job:
                    job.estado = 'error'
                    job.error = 'No fue posible conectar con la cola de procesamiento.'
                    job.terminado_en = utc_now()
                    version = db.session.get(ArchivoFichaVersion, version.id)
                    if version:
                        actualizar_estado(version, 'error', detalle=job.error)
                    db.session.commit()
                importacion_job_id = None
                # Conserva la versión permanente para descarga y diagnóstico.
                raise RuntimeError(
                    'No fue posible poner la importación en cola. '
                    'Revisa REDIS_URL y que el worker esté activo.'
                ) from exc

            flash(
                f'Solicitud recibida correctamente (trabajo #{job.id}). '
                'El archivo quedó en cola y se está procesando en segundo plano; '
                'puedes seguir usando el panel.',
                'success',
            )
        else:
            resultado = _pkg.importar_archivo(archivo, ficha, current_user.id)
            ficha = resultado['ficha']
            if aprendiz_admin_id:
                try:
                    configurar_rol_aprendiz(ficha.id, aprendiz_admin_id, True)
                except ValueError as err:
                    flash(f'No se pudo asignar el rol administrativo: {err}', 'warning')
            actualizar_estado(version, 'procesado', detalle=_resumen_importacion(resultado))
            notificar_juicios_importados(resultado, commit=False)
            db.session.commit()
            archivos_creados.clear()
            _actualizar_indicadores_carga(ficha.id)

            msg = _resumen_importacion(resultado)
            if resultado['errores']:
                flash(msg + f" {len(resultado['errores'])} errores.", 'warning')
                for err in resultado['errores'][:10]:
                    flash(err, 'error')
            else:
                flash(msg, 'success')

    except (ErrorArchivo, ErrorImportacion, RuntimeError) as exc:
        db.session.rollback()
        for ruta_nueva in archivos_creados:
            ArchivoService.eliminar(ruta_nueva)
        if ruta_temporal:
            ArchivoService.eliminar(ruta_temporal)
        flash(str(exc), 'error')
    except Exception:
        db.session.rollback()
        for ruta_nueva in archivos_creados:
            ArchivoService.eliminar(ruta_nueva)
        if ruta_temporal:
            ArchivoService.eliminar(ruta_temporal)
        current_app.logger.exception('Error inesperado al importar aprendices')
        flash('No fue posible procesar el archivo. Verifica el Excel e inténtalo de nuevo.', 'error')

    parametros = {'ficha_id': ficha.id}
    if importacion_job_id:
        parametros['importacion_id'] = importacion_job_id
    if volver_planeacion:
        return redirect(url_for('planeacion.analisis', **parametros))
    if volver_juicios:
        return redirect(url_for('instructor.juicios', **parametros))
    return redirect(url_for('instructor.aprendices', **parametros))


@instructor_bp.route('/fichas/<int:ficha_id>/importaciones/<int:job_id>', methods=['GET'])
@login_required
def estado_importacion(ficha_id, job_id):
    """Estado consultable para una barra de progreso del frontend."""
    ficha = db.session.get(Ficha, ficha_id)
    job = db.session.get(ImportacionJob, job_id)
    if not job or job.ficha_id != ficha_id or not puede_gestionar_ficha(ficha):
        return jsonify({'error': 'Importación no encontrada.'}), 404
    resultado = None
    if job.resultado:
        try:
            resultado = json.loads(job.resultado)
        except (TypeError, ValueError):
            resultado = job.resultado
    return jsonify({
        'id': job.id,
        'estado': job.estado,
        'resultado': resultado,
        'error': job.error,
        'creado_en': job.creado_en.isoformat() if job.creado_en else None,
        'iniciado_en': job.iniciado_en.isoformat() if job.iniciado_en else None,
        'terminado_en': job.terminado_en.isoformat() if job.terminado_en else None,
    })


@instructor_bp.route('/fichas/<int:ficha_id>/plantilla-excel')
@login_required
def descargar_plantilla(ficha_id):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Aprendices'
    ws.append(['Documento', 'Nombre', 'Apellidos', 'Tipo (CC/TI)', 'Estado', 'Correo (opcional)'])
    ws.append(['1234567890', 'Juan', 'Perez Garcia', 'CC', 'EN_FORMACION', 'juan@ejemplo.com'])
    ws.append(['9876543210', 'Maria', 'Lopez Ruiz', 'TI', 'EN_FORMACION', ''])

    import io

    from flask import send_file
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='plantilla_aprendices.xlsx')
