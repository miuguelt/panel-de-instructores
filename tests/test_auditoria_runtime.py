"""Comprueba configuración y procesamiento con base de datos y XLSX reales."""

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import create_app, db
from app.models import Aprendiz, ArchivoFichaVersion, ImportacionJob, JuicioEvaluativo, Notificacion
from tests import test_importacion_ficha as apoyo


def test_configuracion_no_inventa_conexion_si_falta_variable():
    entorno = dict(os.environ, DATABASE_URL=' ', SECRET_KEY=secrets.token_hex(32))
    resultado = subprocess.run([sys.executable, '-c',
        'from app import create_app; create_app()'], env=entorno, capture_output=True, text=True)
    assert resultado.returncode != 0
    assert 'DATABASE_URL' in resultado.stderr
    assert 'debe configurarse' in resultado.stderr


def test_sesion_sin_clave_configurada_no_usa_una_clave_compartida():
    entorno = dict(os.environ, FLASK_ENV='development', SECRET_KEY='', DATABASE_URL='sqlite:///:memory:')
    codigo = 'import json, config; print(json.dumps({"efimera":config.SECRET_KEY_IS_EPHEMERAL,"longitud":len(config.Config.SECRET_KEY)}))'
    resultado = subprocess.run([sys.executable, '-c', codigo], env=entorno, capture_output=True, text=True)
    assert resultado.returncode == 0
    datos = json.loads(resultado.stdout.strip().splitlines()[-1])
    assert datos == {'efimera': True, 'longitud': 128}


def test_health_no_publica_detalles_de_conexion():
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'WTF_CSRF_ENABLED': False})
    dato_privado = secrets.token_urlsafe(24)
    with app.app_context(), patch.object(db.engine, 'connect', side_effect=SQLAlchemyError(dato_privado)):
        respuesta = app.test_client().get('/health')
    assert respuesta.status_code == 200
    assert respuesta.json['status'] == 'degraded'
    assert respuesta.json['database'] == 'unavailable'
    assert dato_privado not in respuesta.text


@pytest.fixture
def contexto_runtime():
    caso = apoyo.ImportacionFichaTestCase()
    caso.setUp()
    try:
        yield caso
    finally:
        caso.tearDown()


def test_worker_conserva_importacion_confirmada_si_falla_ranking(contexto_runtime):
    import worker
    caso = contexto_runtime
    inicial = apoyo.importar_archivo(
        caso._archivo_con_estado('POR EVALUAR'), caso.ficha, caso.a.id,
    )
    assert inicial['carga_inicial_juicios']
    db.session.commit()
    contenido = caso._archivo().read()
    ruta = Path(caso.uploads.name, 'reporte.xlsx')
    ruta.write_bytes(contenido)
    version = ArchivoFichaVersion(ficha_id=caso.ficha.id, instructor_id=caso.a.id,
        tipo='reporte_juicios', version=1, nombre_archivo='reporte.xlsx',
        ruta_archivo='respaldo.xlsx', tamano_bytes=len(contenido), estado='pendiente')
    db.session.add(version)
    db.session.flush()
    trabajo = ImportacionJob(ficha_id=caso.ficha.id, instructor_id=caso.a.id,
        archivo_version_id=version.id, archivo_path=str(ruta), nombre_archivo=ruta.name, estado='encolado')
    db.session.add(trabajo)
    db.session.commit()
    trabajo_id, version_id = trabajo.id, version.id
    with patch('worker.app', caso.app), patch('worker.actualizar_participacion_ficha', side_effect=RuntimeError('indicador no disponible')):
        worker._procesar(trabajo_id)
    db.session.expire_all()
    confirmado = db.session.get(ImportacionJob, trabajo_id)
    assert confirmado.estado == 'completado'
    assert db.session.get(ArchivoFichaVersion, version_id).estado == 'procesado'
    assert Aprendiz.query.filter_by(ficha_id=caso.ficha.id, documento='1001').count() == 1
    assert JuicioEvaluativo.query.filter_by(ficha_id=caso.ficha.id).count() == 1
    assert Notificacion.query.filter_by(
        destinatario_tipo='aprendiz', ficha_id=caso.ficha.id, tipo='juicio_evaluativo'
    ).count() == 1
    assert json.loads(confirmado.resultado)['advertencias']
    assert not ruta.exists()


def test_worker_descarta_identificador_invalido_sin_detener_consumidor(contexto_runtime):
    import worker
    with patch('worker.app', contexto_runtime.app):
        assert worker._procesar(b'no-es-un-identificador') is None
    assert ImportacionJob.query.count() == 0


def test_creacion_administrador_exige_correo_configurado(contexto_runtime):
    from seed_admin import seed_admin
    from app.models import Instructor
    with patch.dict(os.environ, {'ADSO_ADMIN_EMAIL': '', 'ADSO_ADMIN_PASSWORD': secrets.token_urlsafe(24)}):
        assert seed_admin() == 1
    assert Instructor.query.filter_by(rol='admin').count() == 0


def test_consumidor_continua_despues_de_un_mensaje_invalido(contexto_runtime):
    import worker
    cliente = Mock()
    cliente.blpop.side_effect = [('cola', b'identificador-invalido'), KeyboardInterrupt]
    with patch('worker.app', contexto_runtime.app), patch('worker._conectar_redis', return_value=cliente):
        with pytest.raises(KeyboardInterrupt):
            worker.main()
    assert cliente.blpop.call_count == 2
    assert ImportacionJob.query.count() == 0


def test_fila_atencion_envia_token_csrf_real_y_actualiza_turno(contexto_runtime):
    from flask import g, url_for
    from app.models.atencion import TurnoAtencion
    from app.services.atencion_service import AtencionService
    import re

    caso = contexto_runtime
    aprendiz = Aprendiz(ficha_id=caso.ficha.id, documento='CSRF-001', nombre='Aprendiz', apellidos='Verificación')
    db.session.add(aprendiz)
    db.session.commit()
    turno = AtencionService.solicitar_turno(caso.ficha.id, aprendiz.id, motivo='Revisar evidencia')
    caso.app.config['WTF_CSRF_ENABLED'] = True
    cliente = caso.app.test_client()
    g.pop('_login_user', None)
    with cliente.session_transaction() as sesion:
        sesion['_user_id'] = str(caso.a.id)
        sesion['_fresh'] = True
    with caso.app.test_request_context():
        destino = url_for('atencion.cambiar_estado', ficha_id=caso.ficha.id, turno_id=turno.id)
        fila = url_for('atencion.fila_atencion', ficha_id=caso.ficha.id)
    rechazo = cliente.post(destino, data={'estado': 'en_atencion'})
    assert rechazo.status_code in {302, 400}
    db.session.refresh(turno)
    assert turno.estado == 'esperando'
    pagina = cliente.get(fila)
    assert pagina.status_code == 200
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', pagina.text)
    assert token is not None
    respuesta = cliente.post(destino, data={'estado': 'en_atencion', 'csrf_token': token.group(1)})
    assert respuesta.status_code == 302
    db.session.refresh(turno)
    assert db.session.get(TurnoAtencion, turno.id).estado == 'en_atencion'

