"""Carga unificada de los tres documentos que alimentan una ficha.

La validación de los documentos precede la confirmación de sus registros.
La cola y los indicadores se actualizan después del guardado; sus fallas
se informan sin eliminar versiones confirmadas ni archivos históricos.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from flask import current_app
from werkzeug.utils import secure_filename

from app import db
from app.models import (
    ImportacionJob,
    TIPO_PLANEACION,
    TIPO_PROGRAMA,
    TIPO_REPORTE_JUICIOS,
)
from app.services.alertas import actualizar_alertas_ficha
from app.services.archivos import ArchivoService, ErrorArchivo
from app.services.importacion_ficha import (
    ErrorImportacion,
    es_reporte_oficial,
    importar_archivo,
    leer_metadata_archivo,
    validar_reporte_ficha,
)
from app.services.importacion_jobs import (
    ColaImportacionesNoDisponible,
    encolar_importacion,
    encolar_recalculo_resumen,
)
from app.services.planeacion import comparar_fuentes, parsear_planeacion
from app.services.programa_formacion import parsear_programa
from app.services.ranking import actualizar_participacion_ficha
from app.services.resultados_persistidos import guardar_contenido_documento
from app.services.versiones_archivos import actualizar_estado, crear_version


def metadata_ficha(ficha):
    return {
        'codigo_programa': ficha.codigo_programa,
        'nombre_programa': ficha.nombre_programa,
    }


def procesar_carga_unificada(ficha, instructor_id, archivos):
    """Carga y procesa uno, dos o los tres documentos de una ficha.

    Devuelve ``(ok, mensaje, status)``. Antes de confirmar se revierte la
    transacción y se limpian únicamente los archivos de esta solicitud.
    """
    archivo_planeacion = archivos.get('archivo_planeacion')
    archivo_juicios = (archivos.get('archivo_juicios') or archivos.get('archivo_reporte')
                       or archivos.get('archivo'))
    archivo_programa = archivos.get('archivo_programa')

    tiene_planeacion = bool(archivo_planeacion and archivo_planeacion.filename)
    tiene_juicios = bool(archivo_juicios and archivo_juicios.filename)
    tiene_programa = bool(archivo_programa and archivo_programa.filename)

    if not (tiene_planeacion or tiene_juicios or tiene_programa):
        return False, 'Selecciona al menos uno de los tres documentos para procesar.', 422

    mensajes_exito = []
    archivos_creados = []
    ruta_cruda = None
    guardado_confirmado = False
    procesamiento_pendiente = False
    reporte_en_worker = False

    try:
        # 1. Planeación Pedagógica
        if tiene_planeacion:
            if not archivo_planeacion.filename.lower().endswith('.xlsx'):
                raise ValueError('La planeación pedagógica debe estar en formato .xlsx.')
            ver_plan = crear_version(archivo_planeacion, ficha.id, instructor_id, TIPO_PLANEACION, permitir_existente=True, archivos_creados=archivos_creados)
            ruta_plan = Path(current_app.config['UPLOAD_FOLDER']) / ver_plan.ruta_archivo
            contenido_plan = parsear_planeacion(ruta_plan)
            alineacion_plan = comparar_fuentes(contenido_plan['metadata'], metadata_ficha(ficha))
            motivos = list(alineacion_plan['motivos'])
            if not alineacion_plan['codigo_planeacion']:
                motivos.append('La planeación no contiene el código del programa en sus encabezados.')
            if not alineacion_plan['codigo_ficha']:
                motivos.append(f'La ficha {ficha.codigo} no tiene registrado el código del programa.')
            if motivos:
                raise ErrorImportacion(f'La planeación pedagógica GFPI-F-134 no corresponde a la ficha {ficha.codigo}: ' + ' '.join(motivos))
            guardar_contenido_documento(ver_plan, contenido_plan, 'planeacion-v1')
            actualizar_estado(ver_plan, 'procesado', metadata=contenido_plan['metadata'])
            mensajes_exito.append(f'Planeación v{ver_plan.version} ({contenido_plan["resumen"]["resultados"]} resultados)')

        # 2. Programa de Formación
        if tiene_programa:
            if not archivo_programa.filename.lower().endswith('.pdf'):
                raise ValueError('El Programa de Formación debe estar en formato .pdf.')
            ver_prog = crear_version(archivo_programa, ficha.id, instructor_id, TIPO_PROGRAMA, permitir_existente=True, archivos_creados=archivos_creados)
            ruta_prog = Path(current_app.config['UPLOAD_FOLDER']) / ver_prog.ruta_archivo
            programa_data = parsear_programa(ruta_prog)
            alineacion_prog = comparar_fuentes(programa_data['metadata'], metadata_ficha(ficha))
            if not alineacion_prog['alineado']:
                raise ErrorImportacion(f'El Programa de Formación no corresponde a la ficha {ficha.codigo}: ' + ' '.join(alineacion_prog['motivos']))
            guardar_contenido_documento(ver_prog, programa_data, 'programa-v1')
            actualizar_estado(ver_prog, 'procesado', metadata=programa_data['metadata'])
            mensajes_exito.append(f'Programa v{ver_prog.version} ({programa_data["resumen"]["competencias"]} competencias)')

        # 3. Reporte de Juicios Evaluativos
        if tiene_juicios:
            if not archivo_juicios.filename.lower().endswith(('.xls', '.xlsx')):
                raise ValueError('El Reporte de Juicios debe estar en formato .xls o .xlsx.')
            meta_rep = leer_metadata_archivo(archivo_juicios)
            if es_reporte_oficial(meta_rep):
                validar_reporte_ficha(ficha, meta_rep)
            ver_rep = crear_version(archivo_juicios, ficha.id, instructor_id, TIPO_REPORTE_JUICIOS, metadata=meta_rep, permitir_existente=True, archivos_creados=archivos_creados)

            if current_app.config.get('IMPORTACIONES_ASINCRONAS'):
                archivo_juicios.stream.seek(0)
                nom_arch = secure_filename(archivo_juicios.filename) or 'reporte.xls'
                ruta_cruda = ArchivoService.guardar_crudo(
                    archivo_juicios,
                    carpeta='importaciones',
                    nombre_archivo=f'{uuid4().hex}_{nom_arch}',
                )
                job = ImportacionJob(
                    ficha_id=ficha.id,
                    instructor_id=instructor_id,
                    archivo_version_id=ver_rep.id,
                    archivo_path=ruta_cruda,
                    nombre_archivo=nom_arch,
                    estado='encolado',
                )
                db.session.add(job)
                db.session.commit()
                archivos_creados.clear()
                guardado_confirmado = True
                procesamiento_pendiente = True
                try:
                    encolar_importacion(job.id, current_app.config['IMPORT_QUEUE_NAME'])
                    procesamiento_pendiente = False
                    reporte_en_worker = True
                    mensajes_exito.append(f'Reporte de juicios v{ver_rep.version} encolado (trabajo #{job.id})')
                except ColaImportacionesNoDisponible:
                    job.estado = 'error'
                    job.error = 'No fue posible conectar con la cola de procesamiento.'
                    actualizar_estado(ver_rep, 'error', detalle=job.error)
                    db.session.commit()
                    if ruta_cruda:
                        ArchivoService.eliminar(Path(ruta_cruda).relative_to(Path(current_app.config['UPLOAD_FOLDER'])).as_posix())
                        ruta_cruda = None
                    return False, ('Los documentos quedaron guardados, pero el procesamiento del reporte no pudo iniciarse. '
                                   'Vuelva a cargar el reporte más tarde o informe al administrador.'), 503
            else:
                res_imp = importar_archivo(archivo_juicios, ficha, instructor_id)
                actualizar_estado(ver_rep, 'procesado', detalle=f"{res_imp.get('nuevos', 0)} aprendices, {res_imp.get('juicios_nuevos', 0)} juicios")
                mensajes_exito.append(f'Reporte de juicios v{ver_rep.version} procesado ({res_imp.get("nuevos", 0)} aprendices)')

        db.session.commit()
        archivos_creados.clear()
        guardado_confirmado = True
        if tiene_juicios and not reporte_en_worker:
            actualizar_alertas_ficha(ficha.id)
            actualizar_participacion_ficha(ficha.id)
        if not reporte_en_worker:
            trabajo_resumen = encolar_recalculo_resumen(ficha.id, instructor_id)
            if trabajo_resumen is not None and trabajo_resumen.estado == 'error':
                return True, ('Los documentos quedaron guardados, pero los indicadores están pendientes porque no se pudo iniciar su actualización. '
                              'Recargue la página más tarde o informe al administrador. ' + ' · '.join(mensajes_exito)), 200
        return True, 'Análisis actualizado con éxito. ' + ' · '.join(mensajes_exito), 200

    except (ErrorArchivo, ErrorImportacion, ValueError, OSError) as exc:
        db.session.rollback()
        for ruta_nueva in archivos_creados:
            try:
                ArchivoService.eliminar(ruta_nueva)
            except Exception:
                pass
        if ruta_cruda and not guardado_confirmado:
            ArchivoService.eliminar(Path(ruta_cruda).relative_to(Path(current_app.config['UPLOAD_FOLDER'])).as_posix())
        if guardado_confirmado:
            if procesamiento_pendiente:
                return False, 'El reporte quedó guardado, pero no se confirmó el inicio de su procesamiento. Consulte el estado de la importación antes de reintentarlo.', 503
            return True, 'Los documentos quedaron guardados, pero no fue posible actualizar todos los indicadores. Recargue la página más tarde.', 200
        return False, f'No fue posible completar la carga: {exc}', 422
    except Exception:
        db.session.rollback()
        for ruta_nueva in archivos_creados:
            try:
                ArchivoService.eliminar(ruta_nueva)
            except Exception:
                pass
        if ruta_cruda and not guardado_confirmado:
            ArchivoService.eliminar(Path(ruta_cruda).relative_to(Path(current_app.config['UPLOAD_FOLDER'])).as_posix())
        current_app.logger.exception('Error inesperado al cargar documentos')
        if guardado_confirmado:
            if procesamiento_pendiente:
                return False, 'El reporte quedó guardado, pero no se confirmó el inicio de su procesamiento. Consulte el estado de la importación antes de reintentarlo.', 503
            return True, 'Los documentos quedaron guardados, pero no fue posible actualizar todos los indicadores. Recargue la página más tarde.', 200
        return False, 'Ocurrió un error inesperado al procesar los documentos.', 500


