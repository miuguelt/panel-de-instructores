"""Recepción acotada por bloques, con avance confirmado después de fsync."""

import hashlib
import os
import re
import shutil
from datetime import timedelta
from uuid import uuid4

from flask import current_app
from sqlalchemy import func
from werkzeug.utils import secure_filename

from app import db
from app.helpers import utc_now
from app.models.carga import CargaArchivo, EnvioCarga
from app.services.cargas_acceso import autorizar, extensiones
from app.services.cargas_bloqueos import bloquear, directorio_privado
from app.services.cargas_errores import ErrorCarga


def estado_carga(carga):
    envio = db.session.get(EnvioCarga, carga.envio_id) if carga.envio_id else None
    estado = envio.estado if envio else carga.estado
    resultado = envio.resultado if envio else None
    return dict(ok=True, id=carga.id, estado=estado, offset=carga.offset, tamano=carga.tamano,
                vence_en=carga.vence_en.isoformat() + 'Z', huellas=carga.huellas,
                chunk_bytes=carga.bloque_bytes,
                message=(resultado or {}).get('message', 'Avance confirmado por el servidor.'),
                resultado=resultado, guardado=bool(envio), datos_confirmados=bool(envio and envio.datos_confirmados),
                acciones=['consultar'] if envio else ['continuar', 'cancelar'])


def consultar_carga(identificador):
    carga = db.session.get(CargaArchivo, identificador, populate_existing=True)
    if not carga:
        raise ErrorCarga('carga_no_encontrada', 'No encontramos esta carga.', 404)
    propietario, _, _, _ = autorizar(carga.destino, carga.campo)
    if propietario != carga.propietario:
        raise ErrorCarga('carga_no_encontrada', 'No encontramos esta carga.', 404)
    if carga.estado in {'cancelado', 'vencido'} or (not carga.envio_id and carga.vence_en <= utc_now()):
        raise ErrorCarga('carga_vencida', 'El plazo para continuar esta carga terminó. Seleccione el archivo para iniciar una nueva.', 410, 'seleccionar_archivo')
    return carga


def iniciar_carga(datos, clave=None):
    if not isinstance(datos, dict):
        raise ErrorCarga('formulario_invalido', 'No se pudo leer la solicitud de carga.')
    propietario, destino, endpoint, _ = autorizar(datos.get('destino'), datos.get('campo'))
    tamano = datos.get('tamano')
    if isinstance(tamano, bool) or not isinstance(tamano, int) or tamano <= 0:
        raise ErrorCarga('archivo_vacio', 'Seleccione un archivo que tenga contenido.')
    if tamano > current_app.config['MAX_RESUMABLE_UPLOAD_BYTES']:
        limite_mib = current_app.config['MAX_RESUMABLE_UPLOAD_BYTES'] / 1024**2
        raise ErrorCarga('archivo_demasiado_grande', f'El máximo permitido por archivo es {limite_mib:.1f} MiB.', 413, 'seleccionar_archivo')
    nombre = datos.get('nombre')
    if not isinstance(nombre, str) or not nombre or len(nombre) > 255:
        raise ErrorCarga('nombre_invalido', 'El nombre del archivo no es válido.')
    nombre = secure_filename(nombre)
    if not nombre or '.' not in nombre or nombre.rsplit('.', 1)[-1].lower() not in extensiones(endpoint, datos['campo']):
        raise ErrorCarga('formato_invalido', 'El formato del archivo no está permitido en este formulario.', 422, 'seleccionar_archivo')
    tipo = datos.get('tipo') or 'application/octet-stream'
    if not isinstance(tipo, str) or len(tipo) > 150:
        raise ErrorCarga('formato_invalido', 'El tipo de archivo no es válido.')
    if clave is not None and (not isinstance(clave, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,150}', clave)):
        raise ErrorCarga('clave_invalida', 'La identificación del intento de carga no es válida.')
    identificador = hashlib.sha256((propietario + ':' + clave).encode()).hexdigest()[:32] if clave else uuid4().hex
    with bloquear('reservas'):
        ahora = utc_now()
        existente = db.session.get(CargaArchivo, identificador, populate_existing=True)
        if existente:
            if (existente.destino, existente.campo, existente.nombre, existente.tamano, existente.tipo) != (destino, datos['campo'], nombre, tamano, tipo):
                raise ErrorCarga('confirmacion_distinta', 'El intento de carga corresponde a otro archivo.', 409)
            return consultar_carga(identificador)
        pendientes = CargaArchivo.query.filter(CargaArchivo.envio_id.is_(None),
            CargaArchivo.estado.in_(['subiendo', 'recibido']), CargaArchivo.vence_en > ahora)
        if pendientes.filter_by(propietario=propietario).count() >= 3:
            raise ErrorCarga('cupo_cargas', 'Ya tiene tres cargas pendientes. Termine o cancele alguna antes de iniciar otra.', 429, 'continuar')
        reserva = pendientes.with_entities(func.coalesce(func.sum(CargaArchivo.tamano - CargaArchivo.offset), 0)).scalar()
        total, _, libre = shutil.disk_usage(directorio_privado())
        margen = max(current_app.config['CARGAS_RESERVA_BYTES'], int(total * current_app.config['CARGAS_RESERVA_PORCENTAJE']))
        if libre - reserva - tamano < margen:
            raise ErrorCarga('sin_espacio', 'El servidor no tiene espacio disponible para recibir este archivo. Informe al administrador.', 507, 'contactar_administrador')
        carga = CargaArchivo(id=identificador, propietario=propietario, destino=destino,
            campo=datos['campo'], nombre=nombre, tipo=tipo, tamano=tamano, offset=0,
            bloque_bytes=current_app.config['CARGAS_BLOQUE_BYTES'],
            huellas=[], estado='subiendo', vence_en=ahora + timedelta(hours=24))
        db.session.add(carga)
        db.session.commit()
        return carga


def recibir_bloque(carga, stream, offset, huella, longitud):
    if carga.envio_id or carga.estado != 'subiendo':
        raise ErrorCarga('desfase', 'El archivo ya terminó de transferirse. Consulte su estado antes de continuar.', 409, 'consultar')
    if offset != carga.offset:
        raise ErrorCarga('desfase', 'El avance cambió. Consultaremos el servidor para continuar desde el bloque confirmado.', 409, 'consultar')
    esperado = min(carga.bloque_bytes, carga.tamano - carga.offset)
    if longitud != esperado:
        raise ErrorCarga('bloque_incompleto', 'El bloque llegó incompleto o tiene un tamaño incorrecto. Vuelva a enviarlo.')
    if not isinstance(huella, str) or not re.fullmatch('[a-f0-9]{64}', huella):
        raise ErrorCarga('huella_invalida', 'No se pudo verificar la integridad del bloque.')
    ruta = directorio_privado() / (carga.id + '.part')
    digest = hashlib.sha256()
    try:
        with open(ruta, 'r+b' if ruta.exists() else 'w+b') as archivo:
            archivo.seek(0, os.SEEK_END)
            if archivo.tell() < carga.offset:
                raise ErrorCarga('archivo_incompleto', 'El archivo recibido no coincide con el avance registrado. Informe al administrador.', 500, 'contactar_administrador')
            archivo.truncate(carga.offset)
            archivo.seek(carga.offset)
            faltan = esperado
            while faltan:
                parte = stream.read(min(1024 * 1024, faltan))
                if not parte:
                    raise ErrorCarga('bloque_incompleto', 'Se interrumpió la recepción del bloque. Puede continuar la carga.')
                digest.update(parte)
                archivo.write(parte)
                faltan -= len(parte)
            if digest.hexdigest() != huella:
                raise ErrorCarga('bloque_corrupto', 'El bloque recibido no coincide con el archivo. Volveremos a enviarlo.')
            archivo.flush()
            os.fsync(archivo.fileno())
        carga.offset += esperado
        carga.huellas = carga.huellas + [huella]
        carga.vence_en = utc_now() + timedelta(hours=24)
        if carga.offset == carga.tamano:
            digest = hashlib.sha256()
            with open(ruta, 'rb') as archivo:
                for parte in iter(lambda: archivo.read(1024 * 1024), b''):
                    digest.update(parte)
            carga.hash_sha256 = digest.hexdigest()
            carga.estado = 'recibido'
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return carga


def cancelar_carga(carga):
    if carga.envio_id:
        raise ErrorCarga('archivo_guardado', 'El archivo ya fue registrado y no se puede cancelar desde la carga.', 409, 'consultar', True)
    carga.estado = 'cancelado'
    db.session.commit()
    (directorio_privado() / (carga.id + '.part')).unlink(missing_ok=True)
    return dict(ok=True, estado='cancelado', message='La carga se canceló y su archivo temporal se eliminó.')
