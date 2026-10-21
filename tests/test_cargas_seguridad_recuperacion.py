"""Permisos, integridad y recuperación observable de cargas reanudables."""

import hashlib
import json
import re
import time
import tracemalloc
from contextlib import closing
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import g
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import db
from app.helpers import utc_now
from app.models import Grupo, PlanMejoramiento, RegistroAsistencia
from app.models.carga import CargaArchivo, EnvioCarga
from app.models.material import MaterialFicha
from app.services.archivos import resolver_archivo_subido
from app.services.cargas_archivo import ArchivoReanudable
from app.services.cargas_bloqueos import bloquear
from app.services.cargas_errores import ErrorCarga
from app.services.cargas_transferencia import recibir_bloque
from tests import test_archivos as archivos
from tests import test_flujos_web as flujos


@pytest.fixture
def caso():
    soporte = flujos.FlujosWebTestCase()
    soporte.setUp()
    soporte.app.config.update(CARGAS_REANUDABLES_ENABLED=True, CARGAS_RESERVA_BYTES=0,
                              CARGAS_RESERVA_PORCENTAJE=0, CARGAS_BLOQUE_BYTES=256)
    try:
        yield soporte
    finally:
        soporte.tearDown()


def iniciar(caso, **cambios):
    datos = dict(destino=f'/instructor/fichas/{caso.ficha.id}/materiales', campo='archivo',
                 nombre='guia.pdf', tamano=len(archivos.PDF), tipo='application/pdf')
    datos.update(cambios)
    return caso.cliente.post('/cargas', json=datos)


def enviar(caso, identificador, contenido, offset=0, **cabeceras):
    headers = {'Upload-Offset': str(offset), 'X-Chunk-SHA256': hashlib.sha256(contenido).hexdigest()}
    headers.update(cabeceras)
    return caso.cliente.patch('/cargas/' + identificador, data=contenido,
                              content_type='application/octet-stream', headers=headers)


def completar(caso, **cambios):
    inicio = iniciar(caso, **cambios)
    assert inicio.status_code == 201, inicio.get_data(as_text=True)
    identificador = inicio.json['id']
    for offset in range(0, len(archivos.PDF), caso.app.config['CARGAS_BLOQUE_BYTES']):
        contenido = archivos.PDF[offset:offset + caso.app.config['CARGAS_BLOQUE_BYTES']]
        respuesta = enviar(caso, identificador, contenido, offset)
        assert respuesta.status_code == 200, respuesta.get_data(as_text=True)
    return identificador


def confirmar(caso, identificador, clave='confirmacion', **campos):
    return caso.cliente.post(f'/instructor/fichas/{caso.ficha.id}/materiales',
        data={'_cargas': json.dumps({'archivo': identificador}), '_carga_envio': clave, **campos},
        headers={'X-Requested-With': 'XMLHttpRequest'}, content_type='multipart/form-data')


def aprendiz(caso, persona=None):
    g.pop('_login_user', None)
    with caso.cliente.session_transaction() as sesion:
        sesion.clear()
        sesion['aprendiz_documento'] = (persona or caso.aprendiz).documento
        sesion['aprendiz_ficha_id'] = caso.ficha.id


def test_reanuda_sin_aceptar_desfase_y_descarga_los_mismos_bytes(caso):
    inicio = iniciar(caso)
    identificador = inicio.json['id']
    assert enviar(caso, identificador, archivos.PDF[:256]).json['offset'] == 256
    assert enviar(caso, identificador, archivos.PDF[:256]).status_code == 409
    assert caso.cliente.get('/cargas/' + identificador).json['offset'] == 256
    for offset in range(256, len(archivos.PDF), 256):
        respuesta = enviar(caso, identificador, archivos.PDF[offset:offset + 256], offset)
        assert respuesta.status_code == 200
    assert confirmar(caso, identificador).json['ok'] is True
    material = MaterialFicha.query.one()
    respuesta = caso.cliente.get(f'/aprendiz/descargar/{material.url_archivo}')
    assert respuesta.status_code == 200
    assert respuesta.data == archivos.PDF
    respuesta.close()


def test_identidad_ajena_no_puede_consultar_modificar_ni_cancelar(caso):
    identificador = iniciar(caso).json['id']
    caso._autenticar(caso.ajeno)
    for metodo in ('get', 'delete'):
        respuesta = getattr(caso.cliente, metodo)('/cargas/' + identificador)
        assert respuesta.status_code in {403, 404}
    assert enviar(caso, identificador, archivos.PDF[:256]).status_code in {403, 404}
    carga = db.session.get(CargaArchivo, identificador)
    assert carga.offset == 0 and carga.estado == 'subiendo'


def test_aprendiz_requiere_sesion_validada_y_no_documento_del_formulario(caso):
    destino = f'/aprendiz/{caso.ficha.id}/subir-evidencia/{caso.tarea.id}'
    g.pop('_login_user', None)
    with caso.cliente.session_transaction() as sesion:
        sesion.clear()
    respuesta = iniciar(caso, destino=destino, campo='archivo_evidencia',
                         documento=caso.aprendiz.documento)
    assert respuesta.status_code == 401
    aprendiz(caso)
    respuesta = iniciar(caso, destino=destino, campo='archivo_evidencia')
    assert respuesta.status_code == 201
    identificador = respuesta.json['id']
    aprendiz(caso, caso.otro_aprendiz)
    assert caso.cliente.get('/cargas/' + identificador).status_code == 404


def test_aprendiz_inactivo_y_cambio_a_actividad_de_clase_revocan_acceso(caso):
    aprendiz(caso)
    destino = f'/aprendiz/{caso.ficha.id}/subir-evidencia/{caso.tarea.id}'
    identificador = iniciar(caso, destino=destino, campo='archivo_evidencia').json['id']
    caso.aprendiz.activo = False
    db.session.commit()
    assert caso.cliente.get('/cargas/' + identificador).status_code == 403
    caso.aprendiz.activo = True
    caso.tarea.modalidad = 'clase'
    db.session.commit()
    assert caso.cliente.get('/cargas/' + identificador).status_code == 403


def test_tarea_grupal_exige_pertenencia_activa(caso):
    grupo = Grupo(ficha_id=caso.ficha.id, nombre='Grupo de prueba')
    caso.tarea.es_grupal = True
    caso.tarea.grupos.append(grupo)
    db.session.add(grupo)
    db.session.commit()
    aprendiz(caso)
    destino = f'/aprendiz/{caso.ficha.id}/subir-evidencia/{caso.tarea.id}'
    assert iniciar(caso, destino=destino, campo='archivo_evidencia').status_code == 403
    grupo.aprendices.append(caso.aprendiz)
    db.session.commit()
    respuesta = iniciar(caso, destino=destino, campo='archivo_evidencia')
    assert respuesta.status_code == 201
    grupo.activo = False
    db.session.commit()
    assert caso.cliente.get('/cargas/' + respuesta.json['id']).status_code == 403


def test_plan_cerrado_y_soporte_de_otro_aprendiz_se_rechazan(caso):
    plan = PlanMejoramiento(ficha_id=caso.ficha.id, aprendiz_id=caso.aprendiz.id,
        creado_por=caso.instructor.id, actividades='Adjuntar informe.')
    db.session.add(plan)
    db.session.commit()
    aprendiz(caso)
    destino = f'/aprendiz/{caso.ficha.id}/subir-evidencia-plan/{plan.id}'
    respuesta = iniciar(caso, destino=destino, campo='archivo_evidencia_plan')
    assert respuesta.status_code == 201
    plan.estado = 'cumplido'
    db.session.commit()
    assert caso.cliente.get('/cargas/' + respuesta.json['id']).status_code == 403
    propio = RegistroAsistencia.query.filter_by(aprendiz_id=caso.aprendiz.id).one()
    ajeno = RegistroAsistencia.query.filter_by(aprendiz_id=caso.otro_aprendiz.id).one()
    assert iniciar(caso, destino=f'/aprendiz/{caso.ficha.id}/justificar/{ajeno.id}', campo='soporte').status_code == 403
    assert iniciar(caso, destino=f'/aprendiz/{caso.ficha.id}/justificar/{propio.id}', campo='soporte').status_code == 201


def test_carga_para_editar_tarea_verifica_propietario(caso):
    destino = f'/instructor/fichas/{caso.ficha.id}/tareas/{caso.tarea.id}/editar'
    respuesta = iniciar(caso, destino=destino, campo='material_apoyo')
    assert respuesta.status_code == 201
    caso._autenticar(caso.ajeno)
    assert iniciar(caso, destino=destino, campo='material_apoyo').status_code == 403


@pytest.mark.parametrize('cambios', [
    {'tamano': 0}, {'tamano': -1}, {'tamano': True}, {'tamano': '256'},
    {'nombre': ''}, {'nombre': 'a' * 256}, {'nombre': '.exe'}, {'tipo': {'valor': 'mime'}},
    {'campo': 'no_existe'}, {'destino': '/no-existe'}, {'destino': '//example.com/cargar'},
    {'destino': 42}, {'destino': '/instructor/fichas'},
])
def test_rechaza_datos_invalidos_sin_reservar_espacio(caso, cambios):
    respuesta = iniciar(caso, **cambios)
    assert respuesta.status_code in {404, 422}
    assert respuesta.json['ok'] is False
    assert CargaArchivo.query.count() == 0


def test_id_invalido_mime_offset_y_huella_no_modifican_avance(caso):
    assert caso.cliente.get('/cargas/no-es-id').status_code == 404
    assert caso.cliente.get('/cargas/' + '0' * 32).status_code == 404
    identificador = iniciar(caso).json['id']
    assert caso.cliente.patch('/cargas/' + identificador, data=b'contenido', content_type='text/plain').status_code == 422
    assert enviar(caso, identificador, archivos.PDF[:256], **{'Upload-Offset': 'incorrecto'}).status_code == 409
    assert enviar(caso, identificador, archivos.PDF[:256], **{'X-Chunk-SHA256': 'incorrecta'}).status_code == 422
    assert enviar(caso, identificador, archivos.PDF[:255]).status_code == 422
    assert caso.cliente.get('/cargas/' + identificador).json['offset'] == 0


def test_bloqueo_concurrente_rechaza_solicitud_y_permite_continuar(caso):
    identificador = iniciar(caso).json['id']
    with bloquear(identificador):
        respuesta = enviar(caso, identificador, archivos.PDF[:256])
    assert respuesta.status_code == 409
    assert respuesta.json['code'] == 'carga_ocupada'
    assert enviar(caso, identificador, archivos.PDF[:256]).json['offset'] == 256


def test_fsync_fallido_no_confirma_bloque_y_reintento_recupera(caso):
    identificador = iniciar(caso).json['id']
    with patch('app.services.cargas_transferencia.os.fsync', side_effect=OSError('Disco no disponible')):
        respuesta = enviar(caso, identificador, archivos.PDF[:256])
    assert respuesta.status_code == 507
    assert respuesta.json['code'] == 'fallo_almacenamiento'
    assert caso.cliente.get('/cargas/' + identificador).json['offset'] == 0
    assert enviar(caso, identificador, archivos.PDF[:256]).json['offset'] == 256


def test_stream_interrumpido_y_archivo_confirmado_truncado(caso):
    identificador = iniciar(caso).json['id']
    carga = db.session.get(CargaArchivo, identificador)
    with pytest.raises(ErrorCarga, match='interrumpió'):
        recibir_bloque(carga, BytesIO(b'fragmento'), 0, hashlib.sha256(archivos.PDF[:256]).hexdigest(), 256)
    assert carga.offset == 0
    assert enviar(caso, identificador, archivos.PDF[:256]).json['offset'] == 256
    ruta = Path(caso.uploads.name) / '.cargas' / (identificador + '.part')
    ruta.write_bytes(b'archivo truncado')
    respuesta = enviar(caso, identificador, archivos.PDF[256:512], 256)
    assert respuesta.status_code == 500
    assert respuesta.json['code'] == 'archivo_incompleto'


def test_temporales_no_son_descargables_por_resolucion_publica(caso):
    identificador = completar(caso)
    with pytest.raises(FileNotFoundError):
        resolver_archivo_subido('.cargas/' + identificador + '.part')
    with pytest.raises(FileNotFoundError):
        resolver_archivo_subido('../archivo.pdf')


def test_misma_clave_con_datos_distintos_o_archivo_consumido_no_duplica(caso):
    identificador = completar(caso)
    assert confirmar(caso, identificador, descripcion='Original').json['ok']
    respuesta = confirmar(caso, identificador, descripcion='Diferente')
    assert respuesta.status_code == 409
    assert confirmar(caso, identificador, clave='otra-clave').status_code == 409
    assert caso.cliente.delete('/cargas/' + identificador).status_code == 409
    assert MaterialFicha.query.one().descripcion == 'Original'


def test_rollback_del_registro_conserva_temporal_para_reintentar(caso):
    identificador = completar(caso)

    def impedir_material(sesion):
        if any(isinstance(objeto, MaterialFicha) for objeto in sesion.new):
            raise SQLAlchemyError('Persistencia no disponible')

    event.listen(Session, 'before_commit', impedir_material)
    try:
        respuesta = confirmar(caso, identificador)
    finally:
        event.remove(Session, 'before_commit', impedir_material)
    assert respuesta.status_code == 422
    assert MaterialFicha.query.count() == 0
    carga = db.session.get(CargaArchivo, identificador, populate_existing=True)
    assert carga.envio_id is None
    assert (Path(caso.uploads.name) / '.cargas' / (identificador + '.part')).read_bytes() == archivos.PDF
    assert confirmar(caso, identificador).json['ok'] is True
    assert MaterialFicha.query.count() == 1


def test_perder_respuesta_despues_del_commit_no_duplica_material(caso):
    interrumpir = [True]

    @caso.app.after_request
    def perder_respuesta(respuesta):
        envio = getattr(g, 'carga_envio', None)
        if interrumpir[0] and envio is not None and envio.datos_confirmados:
            interrumpir[0] = False
            raise RuntimeError('Respuesta interrumpida después de guardar')
        return respuesta

    identificador = completar(caso)
    with pytest.raises(RuntimeError, match='Respuesta interrumpida'):
        confirmar(caso, identificador)
    assert MaterialFicha.query.count() == 1
    respuesta = confirmar(caso, identificador)
    assert respuesta.status_code == 200 and respuesta.json['ok'] is True
    assert MaterialFicha.query.count() == 1


def test_copia_acotada_si_no_hay_enlaces_y_diario_conserva_rutas(caso):
    identificador = completar(caso)
    carga = db.session.get(CargaArchivo, identificador)
    destino = Path(caso.uploads.name) / 'copia.pdf'
    with closing(ArchivoReanudable(carga)) as archivo:
        with patch('app.services.cargas_archivo.os.link', side_effect=OSError('Enlaces no disponibles')):
            archivo.save(destino)
    assert destino.read_bytes() == archivos.PDF
    diario = Path(caso.uploads.name) / '.cargas' / (identificador + '.json')
    assert json.loads(diario.read_text(encoding='utf-8')) == ['copia.pdf']
    destino.unlink()
    with closing(ArchivoReanudable(carga)) as archivo:
        archivo.save(destino)
    assert destino.read_bytes() == archivos.PDF
    assert json.loads(diario.read_text(encoding='utf-8')) == ['copia.pdf']


def test_capacidad_reservada_se_resta_a_nuevas_solicitudes(caso):
    with patch('app.services.cargas_transferencia.shutil.disk_usage', return_value=(4096, 0, 1024)):
        assert iniciar(caso, tamano=768).status_code == 201
        respuesta = iniciar(caso, tamano=768)
    assert respuesta.status_code == 507
    assert CargaArchivo.query.count() == 1


def test_csrf_rechazado_es_json_y_no_reserva_archivo(caso):
    caso.app.config['WTF_CSRF_ENABLED'] = True
    respuesta = iniciar(caso)
    assert respuesta.status_code == 400
    assert respuesta.json['ok'] is False
    assert respuesta.json['reload'] is True
    assert CargaArchivo.query.count() == 0


def test_csrf_valido_permite_post_y_patch_y_sin_token_no_avanza(caso):
    caso.app.config['WTF_CSRF_ENABLED'] = True
    pagina = caso.cliente.get(f'/instructor/fichas/{caso.ficha.id}/materiales')
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', pagina.get_data(as_text=True)).group(1)
    respuesta = caso.cliente.post('/cargas', json=dict(
        destino=f'/instructor/fichas/{caso.ficha.id}/materiales', campo='archivo',
        nombre='guia.pdf', tamano=len(archivos.PDF), tipo='application/pdf'),
        headers={'X-CSRFToken': token})
    assert respuesta.status_code == 201
    identificador = respuesta.json['id']
    respuesta = enviar(caso, identificador, archivos.PDF[:256])
    assert respuesta.status_code == 400 and respuesta.json['reload'] is True
    assert caso.cliente.get('/cargas/' + identificador).json['offset'] == 0
    assert enviar(caso, identificador, archivos.PDF[:256], **{'X-CSRFToken': token}).json['offset'] == 256


def test_servicio_deshabilitado_informa_sin_crear_archivos(caso):
    caso.app.config['CARGAS_REANUDABLES_ENABLED'] = False
    respuesta = iniciar(caso)
    assert respuesta.status_code == 503
    assert respuesta.json['code'] == 'cargas_no_disponibles'
    assert CargaArchivo.query.count() == 0


def encolar_planeacion(caso):
    from tests.apoyo_planeacion import crear_planeacion_xlsx
    contenido = crear_planeacion_xlsx(caso.uploads.name).read_bytes()
    destino = f'/instructor/fichas/{caso.ficha.id}/planeacion/cargar'
    respuesta = iniciar(caso, destino=destino, campo='archivo_planeacion', nombre='plan.xlsx',
        tipo='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', tamano=len(contenido))
    assert respuesta.status_code == 201
    identificador = respuesta.json['id']
    for offset in range(0, len(contenido), caso.app.config['CARGAS_BLOQUE_BYTES']):
        bloque = contenido[offset:offset + caso.app.config['CARGAS_BLOQUE_BYTES']]
        assert enviar(caso, identificador, bloque, offset).status_code == 200
    respuesta = caso.cliente.post(destino, data={'_cargas': json.dumps({'archivo_planeacion': identificador}),
        '_carga_envio': 'documento-en-cola'}, content_type='multipart/form-data')
    assert respuesta.status_code == 202
    return db.session.get(CargaArchivo, identificador)


def test_procesamiento_fallido_conserva_original_y_reintento_no_retransfiere(caso):
    from app.services.cargas_trabajos import procesar_envio
    caso.ficha.codigo_programa = '999999'
    db.session.commit()
    carga = encolar_planeacion(caso)
    assert procesar_envio(carga.envio_id) is True
    estado = caso.cliente.get('/cargas/' + carga.id).json
    assert estado['estado'] == 'error'
    assert estado['resultado']['guardado'] is True
    temporal = Path(caso.uploads.name) / '.cargas' / (carga.id + '.part')
    contenido_antes = temporal.read_bytes()
    assert hashlib.sha256(contenido_antes).hexdigest() == carga.hash_sha256
    assert procesar_envio(carga.envio_id) is False
    caso.ficha.codigo_programa = '228118'
    caso.ficha.nombre_programa = 'Tecnólogo en Analisis y Desarrollo de Software'
    db.session.commit()
    respuesta = caso.cliente.post('/cargas/' + carga.id + '/reintentar')
    assert respuesta.status_code in {200, 202}
    assert respuesta.json['estado'] == 'encolado'
    assert procesar_envio(carga.envio_id) is True
    assert temporal.read_bytes() == contenido_antes
    estado = caso.cliente.get('/cargas/' + carga.id).json
    assert estado['estado'] == 'completado'
    assert estado['resultado']['ok'] is True
    assert caso.cliente.post('/cargas/' + carga.id + '/reintentar').status_code == 409


def test_pendientes_recupera_lease_vencido_y_respeta_ejecucion_activa(caso):
    from app.services.cargas_trabajos import procesar_envio, procesar_pendientes
    caso.ficha.codigo_programa = '228118'
    caso.ficha.nombre_programa = 'Tecnólogo en Analisis y Desarrollo de Software'
    db.session.commit()
    carga = encolar_planeacion(caso)
    envio = db.session.get(EnvioCarga, carga.envio_id)
    envio.estado = 'procesando'
    envio.lease_hasta = utc_now() + timedelta(minutes=5)
    db.session.commit()
    assert procesar_envio(envio.id) is False
    envio.lease_hasta = utc_now() - timedelta(seconds=1)
    db.session.commit()
    with bloquear('trabajo-' + envio.id):
        assert procesar_envio(envio.id) is False
    assert procesar_pendientes() == 1
    db.session.refresh(envio)
    assert envio.estado == 'completado'
    assert envio.datos_confirmados is True
    assert procesar_pendientes() == 0


def test_recupera_worker_detenido_despues_del_commit_sin_reimportar(caso):
    from app.models import ArchivoFichaVersion
    from app.services import cargas_trabajos
    caso.ficha.codigo_programa = '228118'
    caso.ficha.nombre_programa = 'Tecnólogo en Analisis y Desarrollo de Software'
    db.session.commit()
    carga = encolar_planeacion(caso)
    procesar_documentos = cargas_trabajos._documentos
    llamadas = []

    def detener_despues_de_guardar(envio, archivos_recibidos):
        llamadas.append(envio.id)
        procesar_documentos(envio, archivos_recibidos)
        raise SystemExit('El proceso terminó después de confirmar los datos')

    with patch('app.services.cargas_trabajos._documentos', side_effect=detener_despues_de_guardar):
        with pytest.raises(SystemExit):
            cargas_trabajos.procesar_envio(carga.envio_id)
        envio = db.session.get(EnvioCarga, carga.envio_id, populate_existing=True)
        assert envio.datos_confirmados is True
        assert ArchivoFichaVersion.query.count() == 1
        assert cargas_trabajos.procesar_pendientes() == 1
    estado = caso.cliente.get('/cargas/' + carga.id).json
    assert estado['estado'] == 'completado'
    assert estado['resultado']['ok'] is True
    assert estado['resultado']['redirect'] == f'/instructor/fichas/{caso.ficha.id}/planeacion'
    assert len(llamadas) == 1
    assert ArchivoFichaVersion.query.count() == 1


def test_limpieza_reconcilia_diario_y_preserva_archivo_referenciado(caso):
    from app.services.cargas_limpieza import archivo_referenciado, limpiar_cargas
    identificador = completar(caso)
    assert confirmar(caso, identificador).json['ok'] is True
    material = MaterialFicha.query.one()
    carga = db.session.get(CargaArchivo, identificador)
    assert archivo_referenciado(material.url_archivo) is True
    assert archivo_referenciado('sin-referencia.pdf') is False
    raiz = Path(caso.uploads.name)
    huérfano = raiz / 'sin-referencia.pdf'
    huérfano.write_bytes(archivos.PDF)
    diario = raiz / '.cargas' / (identificador + '.json')
    diario.write_text(json.dumps([material.url_archivo + '.part', 'sin-referencia.pdf']), encoding='utf-8')
    carga.vence_en = utc_now() - timedelta(seconds=1)
    db.session.commit()
    assert limpiar_cargas() == 1
    assert not huérfano.exists()
    assert not diario.exists()
    assert not (raiz / '.cargas' / (identificador + '.part')).exists()
    assert (raiz / material.url_archivo).read_bytes() == archivos.PDF


def test_limpieza_omite_trabajo_pendiente_y_carga_bloqueada(caso):
    from app.services.cargas_limpieza import limpiar_cargas
    carga = encolar_planeacion(caso)
    carga.vence_en = utc_now() - timedelta(seconds=1)
    db.session.commit()
    assert limpiar_cargas() == 0
    assert (Path(caso.uploads.name) / '.cargas' / (carga.id + '.part')).is_file()
    identificador = completar(caso)
    otra = db.session.get(CargaArchivo, identificador)
    otra.vence_en = utc_now() - timedelta(seconds=1)
    db.session.commit()
    with bloquear(identificador):
        assert limpiar_cargas() == 0
    assert limpiar_cargas() == 1


def pdf_por_bloques(tamano, tamano_bloque):
    """Genera un PDF de una página con comentarios, sin crear un buffer completo."""
    partes = [b'%PDF-1.4\n']
    posiciones = []
    objetos = (
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>',
        b'<< /Length LLLLLLLLLL >>\nstream',
    )
    for numero, objeto in enumerate(objetos, 1):
        posiciones.append(sum(map(len, partes)))
        partes.append(f'{numero} 0 obj\n'.encode() + objeto + b'\n')
        if numero != 4:
            partes.append(b'endobj\n')
    cabecera = b''.join(partes)
    tabla = b'xref\n0 5\n0000000000 65535 f \n' + b''.join(
        f'{posicion:010d} 00000 n \n'.encode() for posicion in posiciones)
    fin = b'\nendstream\nendobj\n'
    cola = tabla + b'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\nXXXXXXXXXX\n%%EOF\n'
    longitud_stream = tamano - len(cabecera) - len(fin) - len(cola)
    cabecera = cabecera.replace(b'LLLLLLLLLL', f'{longitud_stream:010d}'.encode())
    posicion_xref = tamano - len(cola)
    cola = fin + cola.replace(b'XXXXXXXXXX', f'{posicion_xref:010d}'.encode())
    relleno = b'%\n' * (tamano_bloque // 2)
    for offset in range(0, tamano, tamano_bloque):
        bloque = relleno[:min(tamano_bloque, tamano - offset)]
        if offset == 0:
            bloque = cabecera + bloque[len(cabecera):]
        if offset + len(bloque) == tamano:
            bloque = bloque[:-len(cola)] + cola
        yield offset, bloque


def test_generador_del_archivo_grande_produce_pdf_estructural_valido():
    from pypdf import PdfReader
    contenido = b''.join(bloque for _, bloque in pdf_por_bloques(8192, 1024))
    assert len(contenido) == 8192
    lector = PdfReader(BytesIO(contenido), strict=True)
    assert len(lector.pages) == 1
    assert lector.pages[0].extract_text() == ''


def test_transfiere_dos_gib_reales_con_memoria_acotada_y_descarga_identica(caso, record_property):
    tamano = 2**31
    caso.app.config['CARGAS_BLOQUE_BYTES'] = 4 * 1024**2
    inicio = iniciar(caso, tamano=tamano, nombre='documento-grande.pdf')
    assert inicio.status_code == 201
    identificador = inicio.json['id']
    esperado = hashlib.sha256()
    inicio_tiempo = time.perf_counter()
    tracemalloc.start()
    cantidad = 0
    try:
        for offset, contenido in pdf_por_bloques(tamano, caso.app.config['CARGAS_BLOQUE_BYTES']):
            esperado.update(contenido)
            respuesta = enviar(caso, identificador, contenido, offset)
            assert respuesta.status_code == 200, respuesta.get_data(as_text=True)
            assert respuesta.json['offset'] == offset + len(contenido)
            cantidad += 1
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    tiempo = time.perf_counter() - inicio_tiempo
    assert cantidad == 512
    assert respuesta.json['estado'] == 'recibido'
    carga = db.session.get(CargaArchivo, identificador, populate_existing=True)
    assert carga.hash_sha256 == esperado.hexdigest()
    assert confirmar(caso, identificador, clave='dos-gib').json['ok'] is True
    material = MaterialFicha.query.one()
    descarga = caso.cliente.get('/aprendiz/descargar/' + material.url_archivo, buffered=False)
    obtenido = hashlib.sha256()
    recibidos = 0
    try:
        assert descarga.status_code == 200
        for fragmento in descarga.response:
            obtenido.update(fragmento)
            recibidos += len(fragmento)
    finally:
        descarga.close()
    assert recibidos == tamano
    assert obtenido.hexdigest() == esperado.hexdigest()
    # La métrica corresponde a asignaciones Python, no al RSS completo del proceso.
    assert pico < 128 * 1024**2
    record_property('bytes_transferidos', tamano)
    record_property('bloques_transferidos', cantidad)
    record_property('segundos_transferencia_local', round(tiempo, 3))
    record_property('pico_memoria_python_bytes', pico)
