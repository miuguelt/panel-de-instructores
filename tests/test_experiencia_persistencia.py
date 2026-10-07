"""Preferencias de experiencia e hitos permanentes del aprendiz."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import tempfile
from threading import Barrier, local
import unittest
from unittest.mock import patch

from itsdangerous import URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor, Tarea


DEFAULTS = {
    'weeklyGoal': 2, 'notificationMode': 'all', 'rankingVisible': True,
    'reducedMotion': False, 'density': 'comfortable', 'resume': None,
}


class ExperienciaPersistenciaTestCase(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' +
            (Path(self.temporal.name) / 'experiencia.sqlite').as_posix(),
            'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False, 'SECRET_KEY': secrets.token_hex(32),
            'UPLOAD_FOLDER': self.temporal.name,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        instructor = Instructor(nombre='Instructor', correo='instructor@example.com')
        instructor.set_password(secrets.token_urlsafe(24))
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='200001', nombre_programa='ADSO', instructor_id=instructor.id)
        otra_ficha = Ficha(codigo='200002', nombre_programa='ADSO', instructor_id=instructor.id)
        db.session.add_all([ficha, otra_ficha])
        db.session.flush()
        ana = Aprendiz(documento='20001', nombre='Ana', apellidos='Pérez', ficha_id=ficha.id)
        luis = Aprendiz(documento='20002', nombre='Luis', apellidos='Rojas', ficha_id=ficha.id)
        tarea = Tarea(titulo='Individual', ficha_id=ficha.id, instructor_id=instructor.id)
        grupal = Tarea(titulo='Grupo', ficha_id=ficha.id, instructor_id=instructor.id, es_grupal=True)
        ajena = Tarea(titulo='Otra ficha', ficha_id=otra_ficha.id, instructor_id=instructor.id)
        db.session.add_all([ana, luis, tarea, grupal, ajena])
        db.session.commit()
        self.ficha_id, self.otra_ficha_id = ficha.id, otra_ficha.id
        self.ana_id, self.luis_id = ana.id, luis.id
        self.tarea_id, self.grupal_id, self.ajena_id = tarea.id, grupal.id, ajena.id
        self.client = self.app.test_client()
        self.autenticar(self.client, '20001')
        self.url = f'/aprendiz/{self.ficha_id}/experiencia'

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.contexto.pop()
        self.temporal.cleanup()

    def autenticar(self, cliente, documento):
        with cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = documento
            sesion['aprendiz_ficha_id'] = self.ficha_id

    def guardar(self, preferencias=None, revision=0, cliente=None, aprendiz_id=None, **extras):
        return (cliente or self.client).post(self.url, json={
            'preferences': DEFAULTS if preferencias is None else preferencias,
            'revision': revision, **extras,
        }, headers={'X-Learner-Id': str(aprendiz_id or self.ana_id)})

    def assert_error(self, respuesta, estado):
        self.assertEqual(respuesta.status_code, estado, respuesta.get_data(as_text=True))
        cuerpo = respuesta.get_json()
        self.assertFalse(cuerpo['ok'])
        self.assertEqual(cuerpo['status'], estado)
        self.assertEqual(cuerpo['instance'], self.url)
        self.assertEqual(cuerpo['detail'], cuerpo['error'])
        self.assertEqual(respuesta.mimetype, 'application/problem+json')
        self.assertIn('no-store', respuesta.headers['Cache-Control'])

    def test_defaults_lectura_no_crea_registro(self):
        from app.features.experiencia_aprendiz.models import ExperienciaAprendiz
        from app.features.experiencia_aprendiz.service import leer_experiencia
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.get_json(), {'ok': True, 'preferences': DEFAULTS, 'revision': 0})
        self.assertIn('private', respuesta.headers['Cache-Control'])
        self.assertIn('no-store', respuesta.headers['Cache-Control'])
        leido = leer_experiencia(self.ana_id)
        leido['preferences']['weeklyGoal'] = 19
        self.assertEqual(leer_experiencia(self.ana_id)['preferences'], DEFAULTS)
        self.assertEqual(ExperienciaAprendiz.query.count(), 0)

    def test_guardar_recuperar_nueva_sesion_y_actualizar(self):
        preferencias = {
            'weeklyGoal': 20, 'notificationMode': 'quiet', 'rankingVisible': False,
            'reducedMotion': True, 'density': 'compact',
            'resume': {'tab': 'evidencias', 'taskId': self.tarea_id},
        }
        respuesta = self.guardar(preferencias)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.get_json(), {'ok': True, 'preferences': preferencias, 'revision': 1})
        db.session.remove()
        cliente_nuevo = self.app.test_client()
        self.autenticar(cliente_nuevo, '20001')
        self.assertEqual(cliente_nuevo.get(self.url).get_json()['preferences'], preferencias)
        preferencias['weeklyGoal'] = 0
        preferencias['notificationMode'] = 'important'
        respuesta = self.guardar(preferencias, 1, cliente_nuevo)
        self.assertEqual(respuesta.get_json()['revision'], 2)
        self.assertEqual(self.client.get(self.url).get_json()['preferences'], preferencias)

    def test_permisos_ausente_otra_ficha_inactivo_y_contexto(self):
        cliente = self.app.test_client()
        self.assert_error(cliente.get(self.url), 401)
        self.assert_error(self.guardar(cliente=cliente), 401)
        respuesta = self.client.get(f'/aprendiz/{self.otra_ficha_id}/experiencia')
        self.assertEqual(respuesta.status_code, 401)
        self.assert_error(self.client.post(self.url, json={'preferences': DEFAULTS, 'revision': 0}), 400)
        for contexto in ('', '0', '-1', '1.5', 'texto', '١'):
            self.assert_error(self.client.get(self.url, headers={'X-Learner-Id': contexto}), 400)
        self.assert_error(self.client.get(self.url, headers={'X-Learner-Id': str(self.luis_id)}), 401)
        db.session.get(Aprendiz, self.ana_id).activo = False
        db.session.commit()
        self.assert_error(self.client.get(self.url), 403)
        self.assert_error(self.guardar(), 403)

    def test_cambio_sesion_misma_cookie_no_sobrescribe_otro(self):
        self.assertEqual(self.guardar({**DEFAULTS, 'weeklyGoal': 3}).status_code, 200)
        self.autenticar(self.client, '20002')
        preferencias_luis = {**DEFAULTS, 'weeklyGoal': 7}
        self.assertEqual(self.guardar(preferencias_luis, aprendiz_id=self.luis_id).status_code, 200)
        self.assert_error(self.guardar({**DEFAULTS, 'weeklyGoal': 9}, revision=1), 401)
        self.assertEqual(self.client.get(self.url).get_json()['preferences'], preferencias_luis)
        self.autenticar(self.client, '20001')
        self.assertEqual(self.client.get(self.url).get_json()['preferences']['weeklyGoal'], 3)

    def test_aislamiento_y_conflicto_revision(self):
        self.assertEqual(self.guardar({**DEFAULTS, 'weeklyGoal': 6}).status_code, 200)
        otro_cliente = self.app.test_client()
        self.autenticar(otro_cliente, '20002')
        self.assertEqual(otro_cliente.get(self.url).get_json()['revision'], 0)
        self.assertEqual(self.guardar(cliente=otro_cliente, aprendiz_id=self.luis_id).status_code, 200)
        self.assert_error(self.guardar(revision=0), 409)
        self.assert_error(self.guardar(revision=3), 409)
        self.assertEqual(self.guardar(revision=1).get_json()['revision'], 2)
        self.assert_error(self.guardar(revision=1), 409)

    def test_validacion_estricta_preferencias_y_revision(self):
        invalidas = [[], 'texto', {}, {**DEFAULTS, 'weeklyGoal': -1}, {**DEFAULTS, 'weeklyGoal': 21},
                     {**DEFAULTS, 'weeklyGoal': True}, {**DEFAULTS, 'weeklyGoal': 2.5},
                     {**DEFAULTS, 'notificationMode': 'otro'}, {**DEFAULTS, 'notificationMode': []},
                     {**DEFAULTS, 'rankingVisible': 1}, {**DEFAULTS, 'reducedMotion': 'false'},
                     {**DEFAULTS, 'density': 'otro'}, {**DEFAULTS, 'density': []},
                     {**DEFAULTS, 'logros': ['veinte_entregas']}, {**DEFAULTS, 'score': 100}]
        for preferencias in invalidas:
            with self.subTest(preferencias=preferencias):
                self.assert_error(self.guardar(preferencias), 400)
        for revision in ('0', True, None, -1, 1.5, 2147483647):
            self.assert_error(self.guardar(revision=revision), 400)
        self.assert_error(self.guardar(documento='20002'), 400)
        self.assert_error(self.client.post(self.url, data='{}', headers={'X-Learner-Id': str(self.ana_id)}), 400)
        self.assert_error(self.client.post(self.url, data='{', content_type='application/json',
                                          headers={'X-Learner-Id': str(self.ana_id)}), 400)
        self.assert_error(self.client.post(self.url, json=None, headers={'X-Learner-Id': str(self.ana_id)}), 400)

    def test_resume_valida_tabs_tarea_individual_y_pertenencia(self):
        invalidos = [[], {}, {'tab': 'otra', 'taskId': None}, {'tab': 'grupo', 'taskId': self.tarea_id},
                     {'tab': 'evidencias', 'taskId': self.grupal_id}, {'tab': 'evidencias', 'taskId': self.ajena_id},
                     {'tab': 'evidencias', 'taskId': 9999}, {'tab': 'evidencias', 'taskId': False},
                     {'tab': 'evidencias', 'taskId': -1}, {'tab': 'evidencias', 'taskId': '1'},
                     {'tab': [], 'taskId': None}, {'tab': 'resumen', 'taskId': None, 'aprendizId': self.luis_id}]
        for resume in invalidos:
            with self.subTest(resume=resume):
                self.assert_error(self.guardar({**DEFAULTS, 'resume': resume}), 400)
        for revision, tab in enumerate(('resumen', 'evidencias', 'grupo', 'juicios', 'rendimiento', 'convivencia')):
            respuesta = self.guardar({**DEFAULTS, 'resume': {'tab': tab, 'taskId': None}}, revision)
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(respuesta.get_json()['preferences']['resume'], {'tab': tab, 'taskId': None})

    def test_resume_con_tarea_solo_se_admite_en_evidencias(self):
        for tab in ('resumen', 'grupo', 'juicios', 'rendimiento', 'convivencia'):
            with self.subTest(tab=tab):
                self.assert_error(self.guardar({**DEFAULTS, 'resume': {'tab': tab, 'taskId': self.tarea_id}}), 400)
        respuesta = self.guardar({**DEFAULTS, 'resume': {'tab': 'evidencias', 'taskId': self.tarea_id}})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.get_json()['preferences']['resume'], {'tab': 'evidencias', 'taskId': self.tarea_id})

    def test_error_commit_revierte_y_no_filtra_parametros(self):
        self.assertEqual(self.guardar({**DEFAULTS, 'weeklyGoal': 4}).status_code, 200)
        with self.assertLogs(self.app.logger, level='ERROR') as registros:
            with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('Dato privado del aprendiz')):
                self.assert_error(self.guardar({**DEFAULTS, 'weeklyGoal': 9}, revision=1), 503)
        self.assertNotIn('Dato privado del aprendiz', '\n'.join(registros.output))
        self.assertEqual(self.client.get(self.url).get_json()['preferences']['weeklyGoal'], 4)
        self.assertEqual(self.client.get(self.url).get_json()['revision'], 1)

    def test_error_lectura_y_creacion(self):
        with patch('app.features.experiencia_aprendiz.routes.aprendiz_autorizado', side_effect=SQLAlchemyError()):
            self.assert_error(self.client.get(self.url), 503)
        with patch.object(db.session, 'commit', side_effect=IntegrityError('INSERT', {}, Exception('fallo'))):
            self.assert_error(self.guardar(), 503)
        self.assertEqual(self.client.get(self.url).get_json()['revision'], 0)

    def test_payload_demasiado_extenso_y_limite_global(self):
        self.assert_error(self.guardar(texto='a' * 9000), 400)
        self.app.config['MAX_CONTENT_LENGTH'] = 30
        self.assert_error(self.guardar(), 413)

    def test_csrf_header_obligatorio(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assert_error(self.guardar(), 400)
        token_sesion = secrets.token_urlsafe(32)
        with self.client.session_transaction() as sesion:
            sesion['csrf_token'] = token_sesion
        token = URLSafeTimedSerializer(self.app.secret_key, salt='wtf-csrf-token').dumps(token_sesion)
        respuesta = self.client.post(self.url, json={'preferences': DEFAULTS, 'revision': 0},
                                     headers={'X-Learner-Id': str(self.ana_id), 'X-CSRFToken': token})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.get_json()['revision'], 1)

    def test_carrera_creacion_y_actualizacion(self):
        from app.features.experiencia_aprendiz.service import guardar_experiencia
        clientes = [self.app.test_client(), self.app.test_client()]
        for cliente in clientes:
            self.autenticar(cliente, '20001')
        for revision in (0, 1):
            barrera = Barrier(2, timeout=10)

            def guardar_con_barrera(*argumentos, **opciones):
                barrera.wait()
                return guardar_experiencia(*argumentos, **opciones)

            def solicitar(indice):
                respuesta = self.guardar({**DEFAULTS, 'weeklyGoal': indice + 3}, revision, clientes[indice])
                return respuesta.status_code, respuesta.get_json()

            with patch('app.features.experiencia_aprendiz.routes.guardar_experiencia', guardar_con_barrera):
                with ThreadPoolExecutor(max_workers=2) as ejecutor:
                    resultados = list(ejecutor.map(solicitar, (0, 1)))
            self.assertEqual(sorted(estado for estado, _ in resultados), [200, 409])
            ganador = next(datos for estado, datos in resultados if estado == 200)
            self.assertEqual(self.client.get(self.url).get_json()['preferences'], ganador['preferences'])

    def test_hitos_permanentes_no_suben_revision_y_no_se_pueden_falsificar(self):
        from app.features.experiencia_aprendiz.service import leer_experiencia, registrar_hitos
        from app.features.experiencia_aprendiz.models import ExperienciaAprendiz
        self.assertEqual(registrar_hitos(self.ana_id, 0), [])
        self.assertEqual(ExperienciaAprendiz.query.count(), 0)
        self.assertEqual(registrar_hitos(self.ana_id, 1), ['primera_entrega'])
        self.assertEqual(leer_experiencia(self.ana_id), {'preferences': DEFAULTS, 'revision': 1})
        self.assertEqual(registrar_hitos(self.ana_id, 5), ['primera_entrega', 'cinco_entregas'])
        self.assertEqual(registrar_hitos(self.ana_id, 0), ['primera_entrega', 'cinco_entregas'])
        self.assertEqual(leer_experiencia(self.ana_id)['revision'], 1)
        self.assertEqual(self.guardar({**DEFAULTS, 'weeklyGoal': 8}, revision=1).status_code, 200)
        todos = ['primera_entrega', 'cinco_entregas', 'diez_entregas', 'veinte_entregas']
        self.assertEqual(registrar_hitos(self.ana_id, 20), todos)
        self.assertEqual(leer_experiencia(self.ana_id)['revision'], 2)
        self.assertEqual(leer_experiencia(self.ana_id)['preferences']['weeklyGoal'], 8)
        db.session.remove()
        self.assertEqual(registrar_hitos(self.ana_id, 1), todos)
        self.assertEqual(registrar_hitos(self.luis_id, 0), [])
        self.assert_error(self.guardar(revision=2, logros=todos), 400)

    def test_hitos_limites_y_fallo_commit(self):
        from app.features.experiencia_aprendiz.service import registrar_hitos
        from app.features.experiencia_aprendiz.models import ExperienciaAprendiz
        for total in (-1, True, '5', 5.5):
            with self.assertRaises(ValueError):
                registrar_hitos(self.ana_id, total)
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('fallo')):
            with self.assertRaises(SQLAlchemyError):
                registrar_hitos(self.ana_id, 5)
        self.assertEqual(ExperienciaAprendiz.query.count(), 0)
        self.assertEqual(registrar_hitos(self.ana_id, 1), ['primera_entrega'])
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('fallo')):
            with self.assertRaises(SQLAlchemyError):
                registrar_hitos(self.ana_id, 5)
        self.assertEqual(registrar_hitos(self.ana_id, 0), ['primera_entrega'])

    def test_hitos_carrera_creacion_y_union_no_pierde_logros(self):
        from app.features.experiencia_aprendiz.service import registrar_hitos
        from app.features.experiencia_aprendiz.models import ExperienciaAprendiz
        originales_get = db.session.get
        for aprendiz_id, fila_inicial in ((self.ana_id, False), (self.luis_id, True)):
            if fila_inicial:
                self.assertEqual(registrar_hitos(aprendiz_id, 1), ['primera_entrega'])
            barrera = Barrier(2, timeout=10)
            estado_hilo = local()

            def consultar_con_barrera(modelo, identidad, *argumentos, **opciones):
                resultado = originales_get(modelo, identidad, *argumentos, **opciones)
                if modelo is ExperienciaAprendiz and not getattr(estado_hilo, 'consultado', False):
                    estado_hilo.consultado = True
                    barrera.wait()
                return resultado

            def registrar(total):
                with self.app.app_context():
                    return registrar_hitos(aprendiz_id, total)

            with patch.object(db.session, 'get', consultar_con_barrera):
                with ThreadPoolExecutor(max_workers=2) as ejecutor:
                    resultados = list(ejecutor.map(registrar, (5, 20)))
            todos = ['primera_entrega', 'cinco_entregas', 'diez_entregas', 'veinte_entregas']
            self.assertIn(todos, resultados)
            self.assertEqual(registrar_hitos(aprendiz_id, 0), todos)
            self.assertEqual(self.client.get(self.url).get_json()['revision'], 1)

    def test_hitos_error_integridad_sin_fila_no_se_reintenta(self):
        from app.features.experiencia_aprendiz.service import registrar_hitos
        from app.features.experiencia_aprendiz.models import ExperienciaAprendiz
        with patch.object(db.session, 'commit', side_effect=IntegrityError('INSERT', {}, Exception('fallo'))):
            with self.assertRaises(IntegrityError):
                registrar_hitos(self.ana_id, 1)
        self.assertEqual(ExperienciaAprendiz.query.count(), 0)

    def test_eliminar_aprendiz_elimina_experiencia(self):
        from app.features.experiencia_aprendiz.models import ExperienciaAprendiz
        self.assertEqual(self.guardar().status_code, 200)
        db.session.delete(db.session.get(Aprendiz, self.ana_id))
        db.session.commit()
        self.assertEqual(ExperienciaAprendiz.query.count(), 0)
