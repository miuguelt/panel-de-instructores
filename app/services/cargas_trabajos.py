"""Procesamiento durable de documentos recibidos, independiente de Redis."""

from contextlib import ExitStack
from datetime import timedelta

from flask import current_app, g, session, url_for
from flask_login import login_user

from app import db
from app.helpers import utc_now
from app.models import ArchivoFichaVersion, Ficha, Instructor, TIPO_REPORTE_JUICIOS
from app.models.carga import CargaArchivo, EnvioCarga
from app.services.cargas_acceso import autorizar
from app.services.cargas_archivo import ArchivoReanudable
from app.services.cargas_bloqueos import bloquear
from app.services.cargas_confirmacion import resultado_guardado
from app.services.cargas_errores import ErrorCarga


def publicar_envio(identificador):
    from app.services.importacion_jobs import ColaImportacionesNoDisponible, encolar_importacion
    try:
        encolar_importacion('carga:' + identificador, current_app.config['IMPORT_QUEUE_NAME'])
    except ColaImportacionesNoDisponible:
        current_app.logger.warning('La carga %s permanece pendiente en la base de datos; el worker la recuperará.', identificador)


def _documentos(envio, archivos):
    from app.services.carga_documentos import procesar_carga_unificada
    from app.services.importacion_ficha import importar_archivo
    from app.services.versiones_archivos import crear_version, actualizar_estado
    instructor_id = int(envio.propietario.split(':')[1])
    ficha_id = envio.argumentos.get('ficha_id')
    if envio.endpoint == 'instructor.importar_reporte_ficha':
        resultado = importar_archivo(archivos['archivo'], None, instructor_id, crear_ficha=True)
        ficha = resultado['ficha']
        version = crear_version(archivos['archivo'], ficha.id, instructor_id, TIPO_REPORTE_JUICIOS,
                                metadata=resultado.get('metadata'), permitir_existente=True)
        actualizar_estado(version, 'procesado')
        envio.resultado = dict(ok=True, guardado=True, message='La ficha y sus juicios quedaron guardados correctamente.',
                              redirect=url_for('instructor.aprendices', ficha_id=ficha.id))
        db.session.commit()
        return dict(ok=True, message='La ficha y sus juicios quedaron guardados correctamente.',
                    redirect=url_for('instructor.aprendices', ficha_id=ficha.id))
    ficha = db.session.get(Ficha, ficha_id)
    # El servicio valida conjuntamente los documentos antes del primer commit.
    ok, mensaje, _ = procesar_carga_unificada(ficha, instructor_id, archivos)
    if not ok:
        raise ErrorCarga('procesamiento_fallido', mensaje, 422, 'reintentar_procesamiento', True)
    aprendiz_admin = (envio.campos.get('aprendiz_administrativo_id') or [None])[0]
    if aprendiz_admin:
        from app.services.permisos import configurar_rol_aprendiz
        configurar_rol_aprendiz(ficha.id, int(aprendiz_admin), True)
        db.session.commit()
    return dict(ok=True, message=mensaje, redirect=url_for('planeacion.analisis', ficha_id=ficha_id))


def procesar_envio(identificador):
    try:
        with bloquear('trabajo-' + identificador):
            envio = db.session.get(EnvioCarga, identificador, populate_existing=True)
            if not envio:
                return False
            if envio.datos_confirmados:
                if envio.estado != 'guardado' or not envio.lease_hasta:
                    return False
                envio.estado = 'completado'
                envio.lease_hasta = None
                envio.resultado = dict(resultado_guardado(envio), ok=True, guardado=True, estado='completado',
                    message='Los datos quedaron guardados. Se recuperó la confirmación después de una interrupción del procesamiento.')
                db.session.commit()
                return True
            if envio.estado not in {'encolado', 'procesando'}:
                return False
            if envio.estado == 'procesando' and envio.lease_hasta and envio.lease_hasta > utc_now():
                return False
            envio.estado = 'procesando'
            envio.iniciado_en = utc_now()
            envio.lease_hasta = utc_now() + timedelta(minutes=5)
            envio.intentos += 1
            db.session.commit()
            _ejecutar_envio(envio)
            return True
    except ErrorCarga as exc:
        if exc.codigo == 'carga_ocupada':
            return False
        raise


def _ejecutar_envio(envio):
    app = current_app._get_current_object()
    try:
        with app.test_request_context(envio.destino, method='POST'), ExitStack() as recursos:
            instructor = db.session.get(Instructor, int(envio.propietario.split(':')[1]))
            if not instructor:
                raise ErrorCarga('sin_permiso', 'La cuenta que solicitó la importación ya no está disponible.', 403)
            login_user(instructor)
            archivos = {}
            for campo, identificador in envio.referencias.items():
                autorizar(envio.destino, campo)
                carga = db.session.get(CargaArchivo, identificador)
                archivo = ArchivoReanudable(carga)
                recursos.callback(archivo.close)
                archivos[campo] = archivo
            g.carga_trabajo = True
            # El mismo commit de los datos académicos confirma la idempotencia.
            g.carga_envio = envio
            envio.estado = 'confirmando'
            envio.resultado = dict(ok=True, guardado=True, message='Los datos quedaron guardados correctamente.',
                redirect=(url_for('planeacion.analisis', ficha_id=envio.argumentos['ficha_id'])
                          if envio.argumentos.get('ficha_id') else url_for('instructor.fichas')))
            resultado = _documentos(envio, archivos)
            envio.estado = 'completado'
            envio.datos_confirmados = True
            envio.lease_hasta = None
            envio.resultado = dict(resultado, guardado=True, estado='completado')
            db.session.commit()
    except Exception as exc:
        db.session.rollback()
        envio = db.session.get(EnvioCarga, envio.id, populate_existing=True)
        if envio.datos_confirmados:
            envio.estado = 'completado'
            envio.resultado = dict(resultado_guardado(envio), ok=True, guardado=True, estado='completado',
                message='Los datos quedaron guardados, pero no fue posible actualizar todos los indicadores. Puede actualizar la vista.')
        else:
            envio.estado = 'error'
            detalle = str(exc) if isinstance(exc, ErrorCarga) else 'El procesamiento encontró un error. Informe al administrador si vuelve a ocurrir.'
            envio.resultado = dict(ok=False, guardado=True, estado='error', code='procesamiento_fallido',
                message='El archivo quedó guardado, pero su procesamiento falló. ' + detalle,
                accion='reintentar_procesamiento', retry_url='/cargas/' + next(iter(envio.referencias.values())) + '/reintentar')
        envio.lease_hasta = None
        db.session.commit()
        current_app.logger.exception('No se pudo completar el procesamiento de la carga %s.', envio.id)


def procesar_pendientes():
    ahora = utc_now()
    trabajos = EnvioCarga.query.filter(
        (EnvioCarga.estado == 'encolado') |
        ((EnvioCarga.estado == 'procesando') & (EnvioCarga.lease_hasta <= ahora)) |
        ((EnvioCarga.estado == 'guardado') & (EnvioCarga.lease_hasta.is_not(None)))
    ).order_by(EnvioCarga.creado_en).limit(10).all()
    procesados = 0
    for trabajo in trabajos:
        procesados += bool(procesar_envio(trabajo.id))
    return procesados


def reintentar_envio(carga):
    envio = db.session.get(EnvioCarga, carga.envio_id) if carga.envio_id else None
    if not envio or envio.estado != 'error' or envio.datos_confirmados:
        raise ErrorCarga('reintento_no_disponible', 'Consulte el estado del envío antes de reintentar su procesamiento.', 409, 'consultar')
    if any(db.session.get(CargaArchivo, identificador).vence_en <= utc_now() for identificador in envio.referencias.values()):
        raise ErrorCarga('carga_vencida', 'El plazo para reintentar terminó. Inicie una nueva carga.', 410, 'seleccionar_archivo')
    envio.estado = 'encolado'
    envio.resultado = dict(ok=True, guardado=True, estado='encolado',
        message='Archivo guardado; pendiente de procesamiento.', status_url='/cargas/' + carga.id)
    db.session.commit()
    publicar_envio(envio.id)
    return envio.resultado
