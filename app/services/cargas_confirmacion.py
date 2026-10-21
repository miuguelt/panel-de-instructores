"""Confirmación idempotente en la transacción del registro de negocio."""

import hashlib
import json
import re
from contextlib import ExitStack

from flask import current_app, g, has_request_context, jsonify, request, session, url_for
from sqlalchemy import event
from sqlalchemy.orm import Session
from werkzeug.datastructures import ImmutableMultiDict

from app import db
from app.models.carga import CargaArchivo, EnvioCarga
from app.services.cargas_acceso import DOCUMENTOS, autorizar
from app.services.cargas_archivo import ArchivoReanudable
from app.services.cargas_bloqueos import bloquear
from app.services.cargas_errores import ErrorCarga, respuesta_error
from app.services.cargas_transferencia import consultar_carga


def resultado_guardado(envio):
    return envio.resultado or dict(ok=True, guardado=True, message='El archivo quedó registrado correctamente.',
                                   redirect=envio.destino)


def confirmar_efectos(sesion):
    if not has_request_context():
        return
    envio = getattr(g, 'carga_envio', None)
    with sesion.no_autoflush:
        if envio is None or envio.estado != 'confirmando':
            return
        envio.estado = 'guardado'
        envio.datos_confirmados = True
        envio.resultado = resultado_guardado(envio)
        for identificador in envio.referencias.values():
            carga = sesion.get(CargaArchivo, identificador)
            carga.envio_id = envio.id
            carga.estado = 'guardado'


event.listen(Session, 'before_commit', confirmar_efectos)


def preparar_confirmacion():
    g.pop('carga_envio', None)
    g.pop('cargas_recursos', None)
    if request.method != 'POST' or '_cargas' not in request.form:
        return None
    if not current_app.config.get('CARGAS_REANUDABLES_ENABLED'):
        return respuesta_error(ErrorCarga('cargas_no_disponibles', 'La carga reanudable no está habilitada.', 503))
    try:
        return _preparar()
    except ErrorCarga as exc:
        db.session.rollback()
        return respuesta_error(exc)


def _preparar():
    try:
        referencias = json.loads(request.form['_cargas'])
    except (TypeError, ValueError) as exc:
        raise ErrorCarga('referencias_invalidas', 'No se pudieron leer los archivos recibidos.') from exc
    clave = request.form.get('_carga_envio', '')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', clave) or not isinstance(referencias, dict) or not 1 <= len(referencias) <= 3:
        raise ErrorCarga('referencias_invalidas', 'La confirmación de los archivos no es válida.')
    if not all(isinstance(campo, str) and isinstance(valor, str) for campo, valor in referencias.items()):
        raise ErrorCarga('referencias_invalidas', 'La confirmación de los archivos no es válida.')
    propietario, destino, endpoint, argumentos = autorizar(request.path, next(iter(referencias)))
    id_envio = hashlib.sha256((propietario + ':' + clave).encode()).hexdigest()
    g.cargas_recursos = ExitStack()
    g.cargas_recursos.enter_context(bloquear('envio-' + id_envio))
    envio = db.session.get(EnvioCarga, id_envio, populate_existing=True)
    campos = {nombre: request.form.getlist(nombre) for nombre in request.form
              if nombre not in {'csrf_token', '_cargas', '_carga_envio'}}
    if envio:
        if envio.destino != destino or envio.referencias != referencias or envio.campos != campos:
            raise ErrorCarga('confirmacion_distinta', 'Este envío ya corresponde a otros datos. Inicie una nueva confirmación.', 409)
        if envio.estado == 'error' and not envio.datos_confirmados:
            from app.services.cargas_trabajos import reintentar_envio
            carga = consultar_carga(next(iter(referencias.values())))
            return jsonify(reintentar_envio(carga)), 202
        if envio.datos_confirmados or envio.estado in {'encolado', 'procesando', 'completado'}:
            return jsonify(resultado_guardado(envio)), 202 if envio.estado in {'encolado', 'procesando'} else 200
    for campo, identificador in sorted(referencias.items()):
        if not re.fullmatch('[a-f0-9]{32}', identificador):
            raise ErrorCarga('referencias_invalidas', 'El identificador del archivo no es válido.')
        g.cargas_recursos.enter_context(bloquear(identificador))
        carga = consultar_carga(identificador)
        if carga.destino != destino or carga.campo != campo or carga.propietario != propietario:
            raise ErrorCarga('archivo_ajeno', 'El archivo pertenece a otro formulario.', 403)
        if carga.envio_id:
            raise ErrorCarga('archivo_registrado', 'Este archivo ya quedó registrado. Consulte el resultado del envío.', 409, 'consultar', True)
        if carga.estado != 'recibido':
            raise ErrorCarga('archivo_incompleto', 'El archivo todavía no ha terminado de subir.', 409, 'continuar')
    if envio is None:
        destino_exito = (url_for('aprendiz.panel', ficha_id=argumentos['ficha_id'])
                         if endpoint.startswith('aprendiz.') else
                         url_for('instructor.tareas', ficha_id=argumentos['ficha_id'])
                         if endpoint == 'instructor.editar_tarea' else destino)
        envio = EnvioCarga(id=id_envio, propietario=propietario, destino=destino, endpoint=endpoint,
                          argumentos=argumentos, referencias=referencias, campos=campos,
                          resultado=dict(ok=True, guardado=True, message='El archivo quedó registrado correctamente.',
                                         redirect=destino_exito))
        db.session.add(envio)
        db.session.commit()
    if endpoint in DOCUMENTOS:
        envio.estado = 'encolado'
        envio.resultado = dict(ok=True, guardado=True, estado='encolado',
            message='Archivo guardado; pendiente de procesamiento. Puede seguir usando el panel.',
            status_url='/cargas/' + next(iter(referencias.values())))
        for identificador in referencias.values():
            carga = db.session.get(CargaArchivo, identificador)
            carga.envio_id = envio.id
        db.session.commit()
        from app.services.cargas_trabajos import publicar_envio
        publicar_envio(envio.id)
        return jsonify(envio.resultado), 202
    archivos = list(request.files.items(multi=True))
    if any(campo in request.files for campo in referencias):
        raise ErrorCarga('archivo_repetido', 'El formulario contiene dos archivos para el mismo campo.')
    for campo, identificador in referencias.items():
        archivo = ArchivoReanudable(db.session.get(CargaArchivo, identificador))
        g.cargas_recursos.callback(archivo.close)
        archivos.append((campo, archivo))
    request.files = ImmutableMultiDict(archivos)
    g.carga_envio = envio
    return None


def finalizar_confirmacion(respuesta):
    envio = getattr(g, 'carga_envio', None)
    if envio is None:
        return respuesta
    db.session.refresh(envio)
    # La primera confirmación de negocio también persistió la idempotencia.
    # Un error posterior no puede convertir ese resultado en un rechazo.
    if envio.datos_confirmados:
        anteriores = getattr(g, 'carga_mensajes_previos', 0)
        mensajes = session.get('_flashes', [])[anteriores:]
        resultado = dict(ok=True, guardado=True,
            message=' '.join(texto for _, texto in mensajes) or resultado_guardado(envio)['message'],
            redirect=respuesta.headers.get('Location') or envio.destino)
        if respuesta.is_json and respuesta.status_code < 400:
            resultado.update(respuesta.get_json() or {})
        envio.resultado = resultado
        db.session.commit()
        return jsonify(resultado)
    db.session.rollback()
    return respuesta


def cerrar_confirmacion(error=None):
    recursos = g.pop('cargas_recursos', None)
    if recursos:
        recursos.close()
    g.pop('carga_envio', None)
    g.pop('carga_trabajo', None)


def registrar_confirmaciones(app):
    app.register_error_handler(ErrorCarga, respuesta_error)
    app.before_request(preparar_confirmacion)
    app.after_request(finalizar_confirmacion)
    app.teardown_request(cerrar_confirmacion)
