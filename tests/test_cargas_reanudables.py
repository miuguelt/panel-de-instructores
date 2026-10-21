"""La recepción confirma bloques durables y nunca duplica sus efectos."""

import hashlib
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from app import db
from tests import test_archivos as soporte_archivos

PDF = soporte_archivos.PDF


@pytest.fixture
def caso():
    soporte = soporte_archivos.ArchivosTestCase()
    soporte.setUp()
    soporte.app.config.update(CARGAS_REANUDABLES_ENABLED=True, CARGAS_RESERVA_BYTES=0,
                              CARGAS_RESERVA_PORCENTAJE=0)
    try:
        yield soporte
    finally:
        soporte.tearDown()


def iniciar(caso, contenido=PDF, **cambios):
    datos = dict(destino=f'/instructor/fichas/{caso.ficha.id}/materiales',
                 campo='archivo', nombre='guia.pdf', tamano=len(contenido), tipo='application/pdf')
    datos.update(cambios)
    return caso.cliente.post('/cargas', json=datos)


def bloque(caso, identificador, contenido=PDF, offset=0, huella=None):
    return caso.cliente.patch('/cargas/' + identificador, data=contenido,
        content_type='application/octet-stream', headers={'Upload-Offset': str(offset),
        'X-Chunk-SHA256': huella or hashlib.sha256(contenido).hexdigest()})


def test_recibe_confirma_y_repite_formulario_sin_duplicar(caso):
    from app.models.material import MaterialFicha
    inicio = iniciar(caso)
    assert inicio.status_code == 201
    identificador = inicio.json['id']
    respuesta = bloque(caso, identificador)
    assert respuesta.status_code == 200
    assert respuesta.json['offset'] == len(PDF)
    assert respuesta.json['estado'] == 'recibido'
    import json
    datos = {'_cargas': json.dumps({'archivo': identificador}), '_carga_envio': 'envio-uno',
             'descripcion': 'Guía para el grupo'}
    url = f'/instructor/fichas/{caso.ficha.id}/materiales'
    primera = caso.cliente.post(url, data=datos, headers={'X-Requested-With': 'XMLHttpRequest'},
                               content_type='multipart/form-data')
    assert primera.status_code == 200 and primera.json['ok']
    segunda = caso.cliente.post(url, data=datos, headers={'X-Requested-With': 'XMLHttpRequest'},
                               content_type='multipart/form-data')
    assert segunda.status_code == 200 and segunda.json['ok']
    material = MaterialFicha.query.one()
    assert material.descripcion == 'Guía para el grupo'
    assert (Path(caso.uploads.name) / material.url_archivo).read_bytes() == PDF


def test_bloque_corrupto_desfase_y_respuesta_perdida(caso):
    identificador = iniciar(caso).json['id']
    assert bloque(caso, identificador, huella='0' * 64).status_code == 422
    assert caso.cliente.get('/cargas/' + identificador).json['offset'] == 0
    assert bloque(caso, identificador).status_code == 200
    assert bloque(caso, identificador).status_code == 409
    estado = caso.cliente.get('/cargas/' + identificador).json
    assert estado['offset'] == len(PDF)
    assert estado['huellas'] == [hashlib.sha256(PDF).hexdigest()]


def test_inicio_idempotente_recupera_respuesta_perdida_y_conserva_tamano_bloque(caso):
    from app.models.carga import CargaArchivo
    datos = dict(destino=f'/instructor/fichas/{caso.ficha.id}/materiales', campo='archivo',
                 nombre='guia.pdf', tamano=len(PDF), tipo='application/pdf')
    primera = caso.cliente.post('/cargas', json=datos, headers={'Idempotency-Key': 'inicio-uno'})
    assert primera.status_code == 201
    caso.app.config['CARGAS_BLOQUE_BYTES'] = 128
    segunda = caso.cliente.post('/cargas', json=datos, headers={'Idempotency-Key': 'inicio-uno'})
    assert segunda.json['id'] == primera.json['id']
    assert segunda.json['chunk_bytes'] == 4 * 1024**2
    assert CargaArchivo.query.count() == 1
    assert bloque(caso, segunda.json['id']).json['offset'] == len(PDF)
    datos['nombre'] = 'otra.pdf'
    assert caso.cliente.post('/cargas', json=datos, headers={'Idempotency-Key': 'inicio-uno'}).status_code == 409


def test_limite_dos_gib_y_cuota(caso):
    assert iniciar(caso, tamano=2**31).status_code == 201
    assert iniciar(caso, tamano=2**31 + 1).status_code == 413
    assert iniciar(caso).status_code == 201
    assert iniciar(caso).status_code == 201
    assert iniciar(caso).status_code == 429


def test_autorizacion_formato_espacio_y_cancelacion(caso):
    assert iniciar(caso, destino='https://example.com/cargar').status_code == 422
    assert iniciar(caso, nombre='ejecutable.exe').status_code == 422
    with patch('app.services.cargas_transferencia.shutil.disk_usage', return_value=(100, 99, 1)):
        assert iniciar(caso).status_code == 507
    identificador = iniciar(caso).json['id']
    assert caso.cliente.delete('/cargas/' + identificador).status_code == 200
    assert caso.cliente.get('/cargas/' + identificador).status_code == 410
    with caso.cliente.session_transaction() as sesion:
        sesion.clear()
    from flask import g
    g.pop('_login_user', None)
    assert iniciar(caso).status_code == 401


def test_reconciliacion_y_vencimiento(caso):
    from app.models.carga import CargaArchivo
    from app.helpers import utc_now
    identificador = iniciar(caso).json['id']
    carga = db.session.get(CargaArchivo, identificador)
    ruta = Path(caso.uploads.name) / '.cargas' / (identificador + '.part')
    ruta.write_bytes(b'escritura sin confirmar')
    respuesta = bloque(caso, identificador)
    assert respuesta.status_code == 200
    assert ruta.read_bytes() == PDF
    carga.vence_en = utc_now() - timedelta(seconds=1)
    db.session.commit()
    assert caso.cliente.get('/cargas/' + identificador).status_code == 410


def test_no_confirma_archivo_incompleto_o_ajeno(caso):
    import json
    identificador = iniciar(caso).json['id']
    datos = {'_cargas': json.dumps({'archivo': identificador}), '_carga_envio': 'incompleto'}
    respuesta = caso.cliente.post(f'/instructor/fichas/{caso.ficha.id}/materiales', data=datos)
    assert respuesta.status_code == 409
    assert bloque(caso, identificador).status_code == 200
    from app.models.carga import CargaArchivo
    carga = db.session.get(CargaArchivo, identificador)
    carga.propietario = 'instructor:otro'
    db.session.commit()
    assert caso.cliente.get('/cargas/' + identificador).status_code == 404


def test_documento_guardado_se_procesa_sin_repetir_transferencia(caso):
    import json
    from tests.apoyo_planeacion import crear_planeacion_xlsx
    from app.models import ArchivoFichaVersion
    caso.ficha.codigo_programa = '228118'
    caso.ficha.nombre_programa = 'Tecnólogo en Analisis y Desarrollo de Software'
    db.session.commit()
    contenido = crear_planeacion_xlsx(caso.uploads.name).read_bytes()
    destino = f'/instructor/fichas/{caso.ficha.id}/planeacion/cargar'
    inicio = iniciar(caso, contenido, destino=destino, nombre='plan.xlsx', campo='archivo_planeacion',
                     tipo='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    assert inicio.status_code == 201
    identificador = inicio.json['id']
    assert bloque(caso, identificador, contenido).status_code == 200
    respuesta = caso.cliente.post(destino, data={'_cargas': json.dumps({'archivo_planeacion': identificador}),
        '_carga_envio': 'plan-uno'}, content_type='multipart/form-data')
    assert respuesta.status_code == 202
    assert respuesta.json['guardado'] is True
    from app.services.cargas_trabajos import procesar_envio
    from app.models.carga import CargaArchivo
    carga = db.session.get(CargaArchivo, identificador)
    assert procesar_envio(carga.envio_id) is True
    assert ArchivoFichaVersion.query.one().estado == 'procesado'
    estado = caso.cliente.get('/cargas/' + identificador).json
    assert estado['estado'] == 'completado'
    assert estado['resultado']['ok'] is True
    assert procesar_envio(carga.envio_id) is False


def test_limpieza_no_borra_documentos_confirmados(caso):
    from app.models.carga import CargaArchivo
    from app.helpers import utc_now
    from app.services.cargas_limpieza import limpiar_cargas
    identificador = iniciar(caso).json['id']
    assert bloque(caso, identificador).status_code == 200
    carga = db.session.get(CargaArchivo, identificador)
    carga.vence_en = utc_now() - timedelta(seconds=1)
    db.session.commit()
    assert limpiar_cargas() == 1
    assert not (Path(caso.uploads.name) / '.cargas' / (identificador + '.part')).exists()
    assert caso.cliente.get('/cargas/' + identificador).status_code == 410
