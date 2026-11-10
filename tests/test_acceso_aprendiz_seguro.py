"""El documento del aprendiz solo autentica en el formulario de acceso.

Nunca por la URL ni por un formulario de escritura: así nadie suplanta a un
aprendiz ni descarga sus datos conociendo solo la ficha y la cédula (Ley 1581).
"""

import secrets
from datetime import date

import pytest

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor
from app.services.alertas import _url_panel_aprendiz


@pytest.fixture
def entorno():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
        'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False,
    })
    with app.app_context():
        db.create_all()
        instructor = Instructor(nombre='Instructor', correo='acceso-seguro@example.com')
        instructor.set_password(secrets.token_urlsafe(24))
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='ACC-1', nombre_programa='Programa', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.flush()
        ana = Aprendiz(ficha_id=ficha.id, documento='1001', nombre='Ana',
                       apellidos='Prueba', estado='EN_FORMACION')
        luis = Aprendiz(ficha_id=ficha.id, documento='1002', nombre='Luis',
                        apellidos='Prueba', estado='EN_FORMACION')
        db.session.add_all([ana, luis])
        db.session.commit()
        yield app, ficha.id, ana, luis
        db.session.remove()
        db.drop_all()


def _entrar(cliente, ficha_id, documento):
    return cliente.post(f'/aprendiz/{ficha_id}', data={'documento': documento})


def test_documento_en_url_del_panel_no_abre_sesion(entorno):
    app, ficha_id, ana, _ = entorno
    cliente = app.test_client()
    respuesta = cliente.get(f'/aprendiz/{ficha_id}/panel?documento={ana.documento}')
    assert respuesta.status_code == 302
    assert 'documento' not in respuesta.headers['Location']
    with cliente.session_transaction() as sesion:
        assert 'aprendiz_documento' not in sesion
    seguimiento = cliente.get(respuesta.headers['Location'])
    assert seguimiento.status_code == 302
    assert seguimiento.headers['Location'].endswith(f'/aprendiz/{ficha_id}')


def test_documento_en_url_no_reemplaza_la_sesion_activa(entorno):
    app, ficha_id, ana, luis = entorno
    cliente = app.test_client()
    _entrar(cliente, ficha_id, ana.documento)
    cliente.get(f'/aprendiz/{ficha_id}/panel?documento={luis.documento}')
    with cliente.session_transaction() as sesion:
        assert sesion['aprendiz_documento'] == ana.documento


def test_panel_con_sesion_valida_responde(entorno):
    app, ficha_id, ana, _ = entorno
    cliente = app.test_client()
    assert _entrar(cliente, ficha_id, ana.documento).status_code == 302
    respuesta = cliente.get(f'/aprendiz/{ficha_id}/panel')
    assert respuesta.status_code == 200
    assert 'Ana'.encode() in respuesta.data


def test_panel_rechaza_sesion_de_otra_ficha(entorno):
    app, ficha_id, ana, _ = entorno
    cliente = app.test_client()
    with cliente.session_transaction() as sesion:
        sesion['aprendiz_documento'] = ana.documento
        sesion['aprendiz_ficha_id'] = ficha_id + 999
    assert cliente.get(f'/aprendiz/{ficha_id}/panel').status_code == 302


def test_reporte_no_se_descarga_con_documento_en_url(entorno):
    app, ficha_id, ana, _ = entorno
    cliente = app.test_client()
    respuesta = cliente.get(f'/aprendiz/{ficha_id}/descargar-reporte?documento={ana.documento}')
    assert respuesta.mimetype != 'application/pdf'


def test_reporte_se_descarga_con_sesion(entorno):
    app, ficha_id, ana, _ = entorno
    cliente = app.test_client()
    _entrar(cliente, ficha_id, ana.documento)
    respuesta = cliente.get(f'/aprendiz/{ficha_id}/descargar-reporte')
    assert respuesta.mimetype == 'application/pdf'


def _falta_con_soporte(ficha_id, aprendiz, soporte=None):
    from app.models import RegistroAsistencia, SesionAsistencia
    sesion = SesionAsistencia(ficha_id=ficha_id, fecha=date.today())
    db.session.add(sesion)
    db.session.flush()
    registro = RegistroAsistencia(sesion_id=sesion.id, aprendiz_id=aprendiz.id,
                                  estado='FALTA', soporte_url=soporte)
    db.session.add(registro)
    db.session.commit()
    return registro


def test_descarga_de_soporte_ignora_documento_en_url(entorno):
    app, ficha_id, ana, _ = entorno
    from flask import session
    from app.routes.aprendiz import _puede_descargar_archivo
    url = 'soportes/incapacidad-ana.pdf'
    _falta_con_soporte(ficha_id, ana, url)
    with app.test_request_context(f'/?ficha_id={ficha_id}&documento={ana.documento}'):
        assert _puede_descargar_archivo([url]) is False
    with app.test_request_context('/'):
        session['aprendiz_documento'] = ana.documento
        session['aprendiz_ficha_id'] = ficha_id
        assert _puede_descargar_archivo([url]) is True


def test_descarga_de_soporte_rechaza_a_otro_aprendiz(entorno):
    app, ficha_id, ana, luis = entorno
    from flask import session
    from app.routes.aprendiz import _puede_descargar_archivo
    url = 'soportes/incapacidad-ana.pdf'
    _falta_con_soporte(ficha_id, ana, url)
    with app.test_request_context('/'):
        session['aprendiz_documento'] = luis.documento
        session['aprendiz_ficha_id'] = ficha_id
        assert _puede_descargar_archivo([url]) is False


def test_post_sin_sesion_no_acepta_documento_del_formulario(entorno):
    app, ficha_id, ana, _ = entorno
    from app.routes.aprendiz import _documento_aprendiz_para_ficha
    with app.test_request_context('/', method='POST', data={'documento': ana.documento}):
        assert _documento_aprendiz_para_ficha(ficha_id) is None


def test_post_con_sesion_usa_la_identidad_de_sesion(entorno):
    app, ficha_id, ana, luis = entorno
    from flask import session
    from app.routes.aprendiz import _documento_aprendiz_para_ficha
    with app.test_request_context('/', method='POST', data={'documento': ana.documento}):
        session['aprendiz_documento'] = ana.documento
        session['aprendiz_ficha_id'] = ficha_id
        assert _documento_aprendiz_para_ficha(ficha_id) == ana.documento
    with app.test_request_context('/', method='POST', data={'documento': luis.documento}):
        session['aprendiz_documento'] = ana.documento
        session['aprendiz_ficha_id'] = ficha_id
        assert _documento_aprendiz_para_ficha(ficha_id) is None


def test_justificar_sin_sesion_no_guarda_nada(entorno):
    app, ficha_id, ana, _ = entorno
    registro = _falta_con_soporte(ficha_id, ana)
    cliente = app.test_client()
    cliente.post(
        f'/aprendiz/{ficha_id}/justificar/{registro.id}',
        data={'documento': ana.documento, 'nota': 'Estuve enfermo.'},
    )
    db.session.refresh(registro)
    assert registro.soporte_url is None
    assert not registro.nota
    assert registro.estado == 'FALTA'


def test_transparencia_exige_sesion_de_aprendiz(entorno):
    app, ficha_id, ana, _ = entorno
    cliente = app.test_client()
    anonimo = cliente.get(f'/aprendiz/{ficha_id}/turnos-aseo')
    assert anonimo.status_code == 302
    con_url = cliente.get(f'/aprendiz/{ficha_id}/turnos-aseo?documento={ana.documento}')
    assert con_url.status_code == 302


def test_transparencia_no_publica_estado_academico(entorno):
    app, ficha_id, ana, _ = entorno
    cliente = app.test_client()
    _entrar(cliente, ficha_id, ana.documento)
    respuesta = cliente.get(f'/aprendiz/{ficha_id}/turnos-aseo')
    assert respuesta.status_code == 200
    assert b'data-estado' not in respuesta.data
    assert b'EN_FORMACION' not in respuesta.data


def test_url_de_notificacion_no_lleva_cedula(entorno):
    _, ficha_id, ana, _ = entorno
    url = _url_panel_aprendiz(ficha_id)
    assert url == f'/aprendiz/{ficha_id}/panel'
    assert ana.documento not in url
