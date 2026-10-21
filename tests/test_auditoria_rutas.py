"""Regresiones HTTP de aislamiento, validación y conservación de datos."""

from datetime import date, timedelta
import json
import secrets
from io import BytesIO
import zipfile

from flask import g
import pytest
from sqlalchemy import text

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor, Tarea
from app.models import ArchivoFichaVersion, TIPO_PLANEACION, TIPO_PROGRAMA
from app.models.alertas import Notificacion
from app.models.alertas import ConfiguracionAlertas, ConfiguracionAlertasComite
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.models.atencion import TurnoAtencion
from app.models.aseo import TurnoAseo, IntercambioAseo
from app.models.grupo import Grupo, GrupoMensaje
from app.models.juicio import FichaCompetenciaProgramacion
from app.models.observador import NotaObservador
from app.models.ranking import ConfiguracionRanking
from app.models.material import MaterialFicha
from app.routes.auth import _destino_interno
from app.services.importacion_jobs import ColaImportacionesNoDisponible
from tests.apoyo_planeacion import crear_planeacion_xlsx


@pytest.fixture
def entorno(tmp_path):
    app = create_app({
        'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False, 'UPLOAD_FOLDER': str(tmp_path),
        'SECRET_KEY': secrets.token_urlsafe(32),
    })
    with app.app_context():
        db.create_all()
        propietario = Instructor(nombre='Responsable', correo='responsable@example.com')
        ajeno = Instructor(nombre='Otra persona', correo='otra@example.com')
        propietario.set_password(secrets.token_urlsafe(18))
        ajeno.set_password(secrets.token_urlsafe(18))
        db.session.add_all([propietario, ajeno])
        db.session.flush()
        ficha = Ficha(codigo='901', nombre_programa='Programa de prueba', instructor_id=propietario.id)
        otra = Ficha(codigo='902', nombre_programa='Otro programa', instructor_id=ajeno.id)
        db.session.add_all([ficha, otra])
        db.session.flush()
        ana = Aprendiz(ficha_id=ficha.id, documento='101', nombre='Ana', apellidos='Prueba')
        bea = Aprendiz(ficha_id=ficha.id, documento='102', nombre='Beatriz', apellidos='Prueba')
        externa = Aprendiz(ficha_id=otra.id, documento='103', nombre='Carolina', apellidos='Prueba')
        db.session.add_all([ana, bea, externa])
        db.session.commit()
        cliente = app.test_client()
        yield app, cliente, propietario, ficha, otra, ana, bea, externa
        db.session.remove()
        db.drop_all()


def ingresar(cliente, instructor):
    g.pop('_login_user', None)
    with cliente.session_transaction() as sesion:
        sesion['_user_id'] = str(instructor.id)
        sesion['_fresh'] = True


def ingresar_aprendiz(cliente, aprendiz):
    with cliente.session_transaction() as sesion:
        sesion['aprendiz_documento'] = aprendiz.documento
        sesion['aprendiz_ficha_id'] = aprendiz.ficha_id


@pytest.mark.parametrize('estado', ['en_atencion', 'atendido', 'cancelado', 'ausente'])
def test_turno_de_otra_ficha_no_se_modifica(entorno, estado):
    _, cliente, responsable, ficha, otra, _, _, externa = entorno
    turno = TurnoAtencion(ficha_id=otra.id, aprendiz_id=externa.id)
    db.session.add(turno)
    db.session.commit()
    ingresar(cliente, responsable)
    respuesta = cliente.post(f'/instructor/fichas/{ficha.id}/fila-atencion/{turno.id}/estado',
                             data={'estado': estado})
    assert respuesta.status_code == 302
    db.session.refresh(turno)
    assert turno.estado == 'esperando'
    assert turno.atendido_en is None and turno.completado_en is None
    assert NotaObservador.query.count() == 0
    with cliente.session_transaction() as sesion:
        assert any(categoria == 'error' for categoria, _ in sesion['_flashes'])


@pytest.mark.parametrize('datos', [None, [], ['enlace_github'], 3, 'texto'])
@pytest.mark.parametrize('rol', ['aprendiz', 'instructor'])
def test_portafolio_rechaza_json_sin_objeto_sin_borrar_enlaces(entorno, datos, rol):
    _, cliente, responsable, ficha, _, ana, _, _ = entorno
    ana.enlace_github = 'https://github.com/example'
    db.session.commit()
    if rol == 'instructor':
        ingresar(cliente, responsable)
        ruta = f'/instructor/fichas/{ficha.id}/aprendices/{ana.id}/portafolio'
    else:
        ingresar_aprendiz(cliente, ana)
        ruta = f'/aprendiz/{ficha.id}/guardar-portafolio'
    respuesta = cliente.post(ruta, data=json.dumps(datos), content_type='application/json')
    assert respuesta.status_code == 400
    assert respuesta.get_json()['ok'] is False
    db.session.refresh(ana)
    assert ana.enlace_github == 'https://github.com/example'


@pytest.mark.parametrize('destino', ['https://example.com', '//example.com', '///example.com',
                                      '/\\example.com', '/ruta\r\nLocation: //example.com',
                                      'http://[', ' /instructor'])
def test_destino_interno_rechaza_urls_ambiguas(destino):
    assert _destino_interno(destino) is None


def test_destino_interno_conserva_ruta_consulta_y_fragmento():
    destino = '/instructor/fichas?estado=activo#seleccion'
    assert _destino_interno(destino) == destino
    assert _destino_interno(None) is None


@pytest.mark.parametrize('destino', ['https://example.com', '//example.com', '/\\example.com', 'http://['])
def test_notificacion_no_redirige_a_destino_externo(entorno, destino):
    _, cliente, responsable, _, _, _, _, _ = entorno
    aviso = Notificacion(destinatario_tipo='instructor', destinatario_id=responsable.id,
                         mensaje='Aviso de prueba', clave='aviso-auditoria')
    db.session.add(aviso)
    db.session.commit()
    ingresar(cliente, responsable)
    respuesta = cliente.post(f'/instructor/notificaciones/{aviso.id}/leer',
                             data={'redirect_url': destino})
    assert respuesta.status_code == 302
    assert respuesta.headers['Location'] == '/instructor/notificaciones'
    db.session.refresh(aviso)
    assert aviso.leida is True


@pytest.mark.parametrize('campo,valor', [
    ('peso_asistencia', 'NaN'), ('peso_evidencias', 'Infinity'),
    ('bonus_entrega_anticipada', 'NaN'), ('bonus_racha_asistencia', 'Infinity'),
    ('bonus_calificacion_alta', '-Infinity'), ('umbral_calificacion_alta', 'NaN'),
    ('penalizacion_falla_injustificada', 'Infinity'), ('horas_entrega_anticipada', str(2**65)),
    ('semanas_racha', str(2**65)),
])
def test_configuracion_ranking_rechaza_no_finitos_y_desbordamientos(entorno, campo, valor):
    _, cliente, responsable, ficha, _, _, _, _ = entorno
    config = ConfiguracionRanking(ficha_id=ficha.id, peso_asistencia=30, peso_evidencias=40,
                                  peso_juicios=30)
    db.session.add(config)
    db.session.commit()
    ingresar(cliente, responsable)
    datos = {'peso_asistencia': '30', 'peso_evidencias': '40', 'peso_juicios': '30', campo: valor}
    respuesta = cliente.post(f'/instructor/fichas/{ficha.id}/ranking/configuracion', data=datos)
    assert respuesta.status_code == 302
    with cliente.session_transaction() as sesion:
        assert any(categoria == 'error' for categoria, _ in sesion['_flashes'])
    db.session.refresh(config)
    assert (config.peso_asistencia, config.peso_evidencias, config.peso_juicios) == (30, 40, 30)
    assert config.bonus_entrega_anticipada == 1
    assert config.bonus_racha_asistencia == 3
    assert config.semanas_racha == 4


def test_plan_no_revela_tarea_preseleccionada_de_otra_ficha(entorno):
    _, cliente, responsable, ficha, otra, _, _, _ = entorno
    tarea = Tarea(ficha_id=otra.id, instructor_id=otra.instructor_id,
                  titulo='Contenido reservado de otra ficha')
    db.session.add(tarea)
    db.session.commit()
    ingresar(cliente, responsable)
    respuesta = cliente.get(f'/instructor/fichas/{ficha.id}/planes-mejoramiento?tarea_id={tarea.id}')
    assert respuesta.status_code == 200
    assert tarea.titulo not in respuesta.get_data(as_text=True)


def test_soporte_no_permite_cambiar_identidad_desde_formulario(entorno):
    _, cliente, responsable, ficha, _, ana, bea, _ = entorno
    sesion = SesionAsistencia(ficha_id=ficha.id, fecha=date(2026, 1, 2))
    registro = RegistroAsistencia(sesion=sesion, aprendiz=bea, estado='FALTA')
    db.session.add_all([sesion, registro])
    db.session.commit()
    ingresar_aprendiz(cliente, ana)
    respuesta = cliente.post(f'/aprendiz/{ficha.id}/justificar/{registro.id}',
                             data={'documento': bea.documento, 'nota': 'Cambio sin autorización'})
    assert respuesta.status_code == 302
    db.session.refresh(registro)
    assert registro.nota is None


@pytest.mark.parametrize('datos', [[], ['competencia'], {'competencia': 123}])
@pytest.mark.parametrize('accion', ['toggle', 'programar'])
def test_competencias_validan_objeto_y_nombre(entorno, datos, accion):
    _, cliente, responsable, ficha, _, _, _, _ = entorno
    ingresar(cliente, responsable)
    respuesta = cliente.post(f'/instructor/fichas/{ficha.id}/competencias/{accion}', json=datos)
    assert respuesta.status_code == 400
    assert respuesta.get_json()['success'] is False
    assert FichaCompetenciaProgramacion.query.count() == 0


@pytest.mark.parametrize('datos', [
    {'fecha_inicio': 'sin fecha', 'fecha_fin': '2026-10-01'},
    {'fecha_inicio': '2026-09-01', 'fecha_fin': '2026-02-30'},
    {'limpiar': 'false'},
])
def test_programacion_invalida_no_elimina_fechas_previas(entorno, datos):
    _, cliente, responsable, ficha, _, _, _, _ = entorno
    programa = FichaCompetenciaProgramacion(ficha_id=ficha.id, competencia='Competencia de prueba',
                 instructor_id=responsable.id, fecha_inicio=date(2026, 8, 1), fecha_fin=date(2026, 8, 31))
    db.session.add(programa)
    db.session.commit()
    ingresar(cliente, responsable)
    respuesta = cliente.post(f'/instructor/fichas/{ficha.id}/competencias/programar',
        json={'competencia': programa.competencia, **datos})
    assert respuesta.status_code == 400
    db.session.expire_all()
    actual = db.session.get(FichaCompetenciaProgramacion, programa.id)
    assert actual is not None
    assert (actual.fecha_inicio, actual.fecha_fin) == (date(2026, 8, 1), date(2026, 8, 31))


@pytest.mark.parametrize('fallo', [True, False])
def test_eliminar_material_conserva_archivo_hasta_confirmar_base_de_datos(entorno, tmp_path, fallo):
    _, cliente, responsable, ficha, _, _, _, _ = entorno
    ruta = tmp_path / 'material.pdf'
    contenido = b'%PDF-1.4\ncontenido preservado\n%%EOF'
    ruta.write_bytes(contenido)
    material = MaterialFicha(ficha_id=ficha.id, instructor_id=responsable.id,
                             nombre_archivo='material.pdf', url_archivo=ruta.name)
    db.session.add(material)
    db.session.commit()
    material_id = material.id
    if fallo:
        db.session.execute(text("CREATE TRIGGER bloquear_material BEFORE DELETE ON materiales_ficha "
            "BEGIN SELECT RAISE(ABORT, 'Interrupción de prueba'); END"))
        db.session.commit()
    ingresar(cliente, responsable)
    respuesta = cliente.post(f'/instructor/fichas/{ficha.id}/materiales/{material_id}/eliminar')
    assert ruta.exists() is fallo
    assert (db.session.get(MaterialFicha, material_id) is not None) is fallo
    assert respuesta.status_code == 302
    if fallo:
        assert ruta.read_bytes() == contenido


@pytest.mark.parametrize('accion', ['GET', 'POST'])
def test_chat_no_permite_sesion_de_aprendiz_deshabilitado(entorno, accion):
    _, cliente, _, ficha, _, ana, _, _ = entorno
    grupo = Grupo(ficha_id=ficha.id, nombre='Equipo', aprendices=[ana])
    ana.activo = False
    db.session.add(grupo)
    db.session.commit()
    ingresar_aprendiz(cliente, ana)
    respuesta = cliente.open(f'/aprendiz/{ficha.id}/grupo/mensajes', method=accion,
                             json={'contenido': 'Mensaje no autorizado'} if accion == 'POST' else None)
    assert respuesta.status_code == 404
    assert GrupoMensaje.query.count() == 0


def test_chat_rechaza_cursor_que_desborda_identificador_sql(entorno):
    _, cliente, _, ficha, _, ana, _, _ = entorno
    db.session.add(Grupo(ficha_id=ficha.id, nombre='Equipo', aprendices=[ana]))
    db.session.commit()
    ingresar_aprendiz(cliente, ana)
    respuesta = cliente.get(f'/aprendiz/{ficha.id}/grupo/mensajes?despues_id={2**100}')
    assert respuesta.status_code == 400
    assert 'error' in respuesta.get_json()


@pytest.mark.parametrize('accion', ['proponer', 'responder'])
def test_intercambio_aseo_no_suplanta_documento_de_otro_aprendiz(entorno, accion):
    _, cliente, _, ficha, _, ana, bea, _ = entorno
    tercera = Aprendiz(ficha_id=ficha.id, documento='104', nombre='Diana', apellidos='Prueba')
    db.session.add(tercera)
    db.session.flush()
    turno = TurnoAseo(ficha_id=ficha.id, fecha=date.today() + timedelta(days=5),
                      aprendiz_1_id=bea.id, aprendiz_2_id=tercera.id)
    db.session.add(turno)
    db.session.flush()
    intercambio = IntercambioAseo(turno_id=turno.id, aprendiz_solicita_id=tercera.id,
                                 aprendiz_recibe_id=bea.id)
    db.session.add(intercambio)
    db.session.commit()
    ingresar_aprendiz(cliente, ana)
    if accion == 'proponer':
        ruta = f'/aprendiz/{ficha.id}/turnos-aseo/{turno.id}/intercambiar'
        datos = {'documento': bea.documento, 'aprendiz_recibe_id': ana.id}
    else:
        ruta = f'/aprendiz/{ficha.id}/intercambios/{intercambio.id}/responder'
        datos = {'documento': bea.documento, 'accion': 'rechazar'}
    respuesta = cliente.post(ruta, data=datos)
    assert respuesta.status_code == 302
    db.session.refresh(intercambio)
    assert intercambio.estado == 'pendiente'
    assert IntercambioAseo.query.count() == 1


def test_fallo_observador_revierte_finalizacion_del_turno(entorno):
    _, cliente, responsable, ficha, _, ana, _, _ = entorno
    turno = TurnoAtencion(ficha_id=ficha.id, aprendiz_id=ana.id, estado='en_atencion')
    db.session.add(turno)
    db.session.commit()
    db.session.execute(text("CREATE TRIGGER bloquear_observador BEFORE INSERT ON notas_observador "
        "BEGIN SELECT RAISE(ABORT, 'Interrupción de prueba'); END"))
    db.session.commit()
    ingresar(cliente, responsable)
    respuesta = cliente.post(f'/instructor/fichas/{ficha.id}/fila-atencion/{turno.id}/estado',
                             data={'estado': 'atendido'})
    db.session.refresh(turno)
    assert turno.estado == 'en_atencion'
    assert turno.completado_en is None
    assert NotaObservador.query.count() == 0
    assert respuesta.status_code == 302


def test_fallo_al_regenerar_grupos_conserva_equipos_actuales(entorno):
    _, cliente, responsable, ficha, _, ana, bea, _ = entorno
    grupo = Grupo(ficha_id=ficha.id, nombre='Equipo previo', aprendices=[ana, bea])
    db.session.add(grupo)
    db.session.commit()
    db.session.execute(text("CREATE TRIGGER bloquear_grupo BEFORE INSERT ON grupos "
        "BEGIN SELECT RAISE(ABORT, 'Interrupción de prueba'); END"))
    db.session.commit()
    ingresar(cliente, responsable)
    respuesta = cliente.post(f'/instructor/fichas/{ficha.id}/grupos/generar',
         data={'tamano_grupo': '2', 'aprendices_ids[]': [str(ana.id), str(bea.id)]})
    db.session.refresh(grupo)
    assert grupo.activo is True
    assert {aprendiz.id for aprendiz in grupo.aprendices} == {ana.id, bea.id}
    assert Grupo.query.count() == 1
    assert respuesta.status_code == 302


@pytest.mark.parametrize('campo,maximo', [
    ('umbral_fallas_consecutivas', 30), ('umbral_fallas_acumuladas', 100),
    ('umbral_fallas_esporadicas', 100), ('periodo_dias_esporadicas', 365),
    ('umbral_tareas_incumplidas', 100), ('dias_plazo_justificacion', 30),
    ('auto_escalar_dias', 365), ('umbral_notas_negativas', 50), ('periodo_dias_notas', 365),
])
def test_configuracion_comite_respeta_maximos_del_formulario(entorno, campo, maximo):
    _, cliente, responsable, ficha, _, _, _, _ = entorno
    config = ConfiguracionAlertasComite(ficha_id=ficha.id)
    db.session.add(config)
    db.session.commit()
    anterior = getattr(config, campo)
    ingresar(cliente, responsable)
    respuesta = cliente.post(f'/instructor/fichas/{ficha.id}/alertas/config-comite',
                             data={campo: str(maximo + 1)})
    assert respuesta.status_code == 302
    with cliente.session_transaction() as sesion:
        assert any(categoria == 'error' for categoria, _ in sesion['_flashes'])
    db.session.refresh(config)
    assert getattr(config, campo) == anterior


def test_configuracion_alertas_rechaza_desbordamiento_sql(entorno):
    _, cliente, responsable, ficha, _, _, _, _ = entorno
    config = ConfiguracionAlertas(ficha_id=ficha.id)
    db.session.add(config)
    db.session.commit()
    ingresar(cliente, responsable)
    respuesta = cliente.post(f'/instructor/fichas/{ficha.id}/alertas/config',
        data={'umbral_amarillo': '3', 'umbral_rojo': str(2**65), 'max_fallas_trimestre': '3'})
    assert respuesta.status_code == 302
    db.session.refresh(config)
    assert config.umbral_rojo == 6


def test_recuperacion_fuentes_informa_fallo_real_de_cola(entorno, tmp_path, monkeypatch):
    _, cliente, responsable, ficha, _, _, _, _ = entorno
    ficha.codigo_programa = '228118'
    ficha.nombre_programa = 'Tecnólogo en Análisis y Desarrollo de Software'
    db.session.commit()
    origen = crear_planeacion_xlsx(tmp_path)
    origen.rename(tmp_path / '1. GPFI-F-134PlaneacionPedagogicaProyectoFormativo.xlsx')

    def cola_no_disponible(*_args, **_kwargs):
        raise ColaImportacionesNoDisponible('Interrupción de prueba de la cola.')

    monkeypatch.setattr('app.services.importacion_jobs.encolar_importacion', cola_no_disponible)
    ingresar(cliente, responsable)
    respuesta = cliente.post(f'/instructor/fichas/{ficha.id}/planeacion/recuperar-fuentes')
    assert respuesta.status_code == 302
    with cliente.session_transaction() as sesion:
        assert any(categoria == 'warning' and 'indicadores' in mensaje
                   for categoria, mensaje in sesion['_flashes'])


@pytest.mark.parametrize('existe_programa', [False, True])
def test_descargar_fuentes_informa_archivos_ausentes(entorno, tmp_path, existe_programa):
    _, cliente, responsable, ficha, _, _, _, _ = entorno
    versiones = [ArchivoFichaVersion(
        ficha_id=ficha.id, instructor_id=responsable.id, tipo=TIPO_PLANEACION,
        version=1, nombre_archivo='Planeación.xlsx', ruta_archivo='no-existe.xlsx',
        hash_sha256='example', tamano_bytes=1, estado='procesado',
    )]
    if existe_programa:
        (tmp_path / 'programa.pdf').write_bytes(b'%PDF-1.4\nContenido disponible\n%%EOF')
        versiones.append(ArchivoFichaVersion(
            ficha_id=ficha.id, instructor_id=responsable.id, tipo=TIPO_PROGRAMA,
            version=1, nombre_archivo='Programa.pdf', ruta_archivo='programa.pdf',
            hash_sha256='example', tamano_bytes=1, estado='procesado',
        ))
    db.session.add_all(versiones)
    db.session.commit()
    ingresar(cliente, responsable)
    respuesta = cliente.get(f'/instructor/fichas/{ficha.id}/planeacion/descargar-todos')
    if existe_programa:
        assert respuesta.status_code == 200
        with zipfile.ZipFile(BytesIO(respuesta.data)) as paquete:
            assert 'Programa.pdf' in paquete.namelist()
            assert 'AVISO_ARCHIVOS_FALTANTES.txt' in paquete.namelist()
            assert 'Planeación.xlsx' in paquete.read('AVISO_ARCHIVOS_FALTANTES.txt').decode('utf-8')
    else:
        assert respuesta.status_code == 302
        with cliente.session_transaction() as sesion:
            assert any(categoria == 'error' for categoria, _ in sesion['_flashes'])
