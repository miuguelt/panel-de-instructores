"""Persistencia, aislamiento y validación de la personalización del aprendiz."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from PIL import Image
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.datastructures import MultiDict

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor


PREFERENCIAS = {
    'avatar': '💻', 'accent': '#39a900', 'themeName': 'sena', 'motto': '',
    'alias': '', 'background': 'plain', 'sectionOrder': [], 'viewMode': 'tabs',
}


def foto_prueba(formato='PNG', tamano=(900, 600)):
    salida = io.BytesIO()
    Image.new('RGBA' if formato == 'PNG' else 'RGB', tamano, 'red').save(salida, formato)
    salida.seek(0)
    return salida


class PersonalizacionAprendizTestCase(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (Path(self.temporal.name) / 'pruebas.sqlite').as_posix(),
            'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False, 'SECRET_KEY': secrets.token_hex(32),
            'UPLOAD_FOLDER': self.temporal.name,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        instructor = Instructor(nombre='Instructor de prueba', correo='instructor@example.com')
        instructor.set_password(secrets.token_urlsafe(24))
        db.session.add(instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='100001', nombre_programa='ADSO', instructor_id=instructor.id)
        self.otra_ficha = Ficha(codigo='100002', nombre_programa='ADSO', instructor_id=instructor.id)
        db.session.add_all([self.ficha, self.otra_ficha])
        db.session.flush()
        self.aprendiz = Aprendiz(documento='10001', nombre='Ana', apellidos='Pérez', ficha_id=self.ficha.id)
        self.otro = Aprendiz(documento='10002', nombre='Luis', apellidos='Rojas', ficha_id=self.ficha.id)
        db.session.add_all([self.aprendiz, self.otro])
        db.session.commit()
        self.ids = (self.ficha.id, self.otra_ficha.id, self.aprendiz.id, self.otro.id)
        self.client = self.app.test_client()
        self.autenticar(self.client, '10001')
        self.url = f'/aprendiz/{self.ids[0]}/personalizacion'

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.contexto.pop()
        self.temporal.cleanup()

    def autenticar(self, cliente, documento, ficha=None):
        with cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = documento
            sesion['aprendiz_ficha_id'] = ficha or self.ids[0]

    def guardar(self, preferencias=None, revision=0, cliente=None, **extras):
        datos = {
            'preferences': json.dumps(PREFERENCIAS if preferencias is None else preferencias),
            'revision': str(revision), **extras,
        }
        return (cliente or self.client).post(self.url, data=datos, content_type='multipart/form-data')

    def assert_error(self, respuesta, codigo):
        self.assertEqual(respuesta.status_code, codigo, respuesta.get_data(as_text=True))
        cuerpo = respuesta.get_json()
        self.assertFalse(cuerpo['ok'])
        self.assertEqual(cuerpo['status'], codigo)
        self.assertEqual(cuerpo['instance'], respuesta.request.path)
        self.assertEqual(cuerpo['error'], cuerpo['detail'])
        self.assertEqual(respuesta.mimetype, 'application/problem+json')
        self.assertIn('no-store', respuesta.headers['Cache-Control'])

    def test_lectura_default_no_crea_registro(self):
        from app.features.personalizacion_aprendiz.models import PersonalizacionAprendiz
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.get_json(), {
            'ok': True, 'preferences': PREFERENCIAS, 'revision': 0,
            'configured': False, 'photoUrl': None,
        })
        self.assertEqual(PersonalizacionAprendiz.query.count(), 0)
        self.assertIn('no-store', respuesta.headers['Cache-Control'])

    def test_guardar_recuperar_nueva_sesion_y_actualizar(self):
        preferencias = {**PREFERENCIAS, 'alias': 'Ana ADSO', 'motto': 'Aprendo cada día',
                        'background': 'grid', 'sectionOrder': ['seccion-tareas', 'seccion-progreso'],
                        'viewMode': 'cascade', 'avatar': '🚀', 'accent': '#2563eb', 'themeName': 'indigo'}
        respuesta = self.guardar(preferencias)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.get_json()['revision'], 1)
        self.assertTrue(respuesta.get_json()['configured'])
        db.session.remove()
        cliente_nuevo = self.app.test_client()
        self.autenticar(cliente_nuevo, '10001')
        recuperado = cliente_nuevo.get(self.url).get_json()
        self.assertEqual(recuperado['preferences'], preferencias)
        self.assertEqual(recuperado['revision'], 1)
        preferencias['alias'] = 'Ana'
        actualizado = self.guardar(preferencias, revision=1, cliente=cliente_nuevo)
        self.assertEqual(actualizado.get_json()['revision'], 2)
        self.assertEqual(self.client.get(self.url).get_json()['preferences']['alias'], 'Ana')

    def test_aislamiento_sesion_y_campos_falsificados(self):
        self.assertEqual(self.guardar({**PREFERENCIAS, 'alias': 'Privado'}).status_code, 200)
        cliente_otro = self.app.test_client()
        self.autenticar(cliente_otro, '10002')
        self.assertFalse(cliente_otro.get(self.url).get_json()['configured'])
        self.assertEqual(self.guardar({**PREFERENCIAS, 'alias': 'Luis'}, cliente=cliente_otro).status_code, 200)
        self.assertEqual(self.client.get(self.url).get_json()['preferences']['alias'], 'Privado')
        self.assert_error(self.guardar(revision=1, documento='10002'), 400)
        for campo in ('score', 'rank', 'badge', 'insignias', 'aprendiz_id'):
            with self.subTest(campo=campo):
                self.assert_error(self.guardar({**PREFERENCIAS, campo: 1}, revision=1), 400)

    def test_cambio_de_aprendiz_en_mismo_navegador_no_sobrescribe_otro_panel(self):
        preferencias_ana = {**PREFERENCIAS, 'alias': 'Ana privada'}
        respuesta_ana = self.guardar(preferencias_ana, photo=(foto_prueba(), 'ana.png'))
        foto_url_ana = respuesta_ana.get_json()['photoUrl']
        foto_ana = self.client.get(foto_url_ana).data
        self.autenticar(self.client, '10002')
        preferencias_luis = {**PREFERENCIAS, 'alias': 'Luis privado'}
        foto_luis_subida = io.BytesIO()
        Image.new('RGB', (400, 400), 'blue').save(foto_luis_subida, 'PNG')
        foto_luis_subida.seek(0)
        respuesta_luis = self.guardar(preferencias_luis, photo=(foto_luis_subida, 'luis.png'))
        self.assertEqual(respuesta_luis.get_json()['revision'], 1)
        foto_url_luis = respuesta_luis.get_json()['photoUrl']
        foto_luis = self.client.get(foto_url_luis).data
        self.assertNotEqual(foto_ana, foto_luis)
        header_ana = {'X-Learner-Id': str(self.ids[2])}
        respuesta_obsoleta = self.client.post(self.url, headers=header_ana, data={
            'preferences': json.dumps({**PREFERENCIAS, 'alias': 'No sobrescribir'}),
            'revision': '1', 'remove_photo': 'true',
        })
        self.assert_error(respuesta_obsoleta, 401)
        self.assert_error(self.client.get(self.url, headers=header_ana), 401)
        self.assert_error(self.client.get(foto_url_ana), 401)
        self.assertEqual(self.client.get(self.url).get_json()['preferences'], preferencias_luis)
        self.assertEqual(self.client.get(self.url).get_json()['revision'], 1)
        self.assertEqual(self.client.get(foto_url_luis).data, foto_luis)
        self.autenticar(self.client, '10001')
        self.assertEqual(self.client.get(self.url, headers=header_ana).get_json()['preferences'], preferencias_ana)
        self.assertEqual(self.client.get(foto_url_ana).data, foto_ana)
        self.assertIn(f'learner={self.ids[2]}', foto_url_ana)

    def test_contexto_esperado_acepta_identidad_actual_y_rechaza_formato_invalido(self):
        header = {'X-Learner-Id': str(self.ids[2])}
        self.assertEqual(self.client.get(self.url, headers=header).status_code, 200)
        respuesta = self.client.post(self.url, headers=header, data={
            'preferences': json.dumps(PREFERENCIAS), 'revision': '0',
        })
        self.assertEqual(respuesta.status_code, 200)
        for valor in ('', '0', '-1', '1.0', 'true', '١', '9' * 30):
            with self.subTest(valor=valor):
                self.assert_error(self.client.get(self.url, headers={'X-Learner-Id': valor}), 400)
                self.assert_error(self.client.get(f'{self.url}/foto?learner={valor}'), 400)

    def test_sesion_ausente_invalida_inactiva_y_otra_ficha(self):
        for metodo in ('get', 'post'):
            respuesta = getattr(self.app.test_client(), metodo)(self.url)
            self.assert_error(respuesta, 401)
        self.assert_error(self.client.get(f'/aprendiz/{self.ids[1]}/personalizacion'), 401)
        self.autenticar(self.client, 'no-existe')
        self.assert_error(self.client.get(self.url), 401)
        self.autenticar(self.client, '10001')
        db.session.get(Aprendiz, self.ids[2]).activo = False
        db.session.commit()
        self.assert_error(self.client.get(self.url), 403)
        self.assert_error(self.guardar(), 403)

    def test_conflicto_actualizacion_y_creacion_no_borra(self):
        self.assertEqual(self.guardar({**PREFERENCIAS, 'alias': 'Primero'}).status_code, 200)
        self.assert_error(self.guardar({**PREFERENCIAS, 'alias': 'Obsoleto'}), 409)
        self.assert_error(self.guardar(revision=9), 409)
        self.assertEqual(self.client.get(self.url).get_json()['preferences']['alias'], 'Primero')
        self.assertEqual(self.guardar(revision=1).status_code, 200)
        self.assert_error(self.guardar(revision=1), 409)

    def test_carrera_creacion_y_actualizacion_en_sesiones_independientes(self):
        from app.features.personalizacion_aprendiz.service import guardar_personalizacion
        clientes = [self.app.test_client(), self.app.test_client()]
        for cliente in clientes:
            self.autenticar(cliente, '10001')
        for revision in (0, 1):
            barrera = Barrier(2, timeout=10)

            def guardar_con_barrera(*argumentos, **opciones):
                barrera.wait()
                return guardar_personalizacion(*argumentos, **opciones)

            def solicitar(indice):
                preferencias = {**PREFERENCIAS, 'alias': f'Sesión {indice}'}
                respuesta = self.guardar(preferencias, revision, clientes[indice])
                return respuesta.status_code, respuesta.get_json()

            with patch('app.features.personalizacion_aprendiz.routes.guardar_personalizacion', guardar_con_barrera):
                with ThreadPoolExecutor(max_workers=2) as ejecutor:
                    resultados = list(ejecutor.map(solicitar, (0, 1)))
            self.assertEqual(sorted(estado for estado, _ in resultados), [200, 409])
            ganador = next(datos for estado, datos in resultados if estado == 200)
            recuperado = self.client.get(self.url).get_json()
            self.assertEqual(recuperado['preferences'], ganador['preferences'])
            self.assertEqual(recuperado['revision'], revision + 1)

    def test_preferencias_invalidas_y_limites(self):
        invalidas = [None, [], 'texto', {}, {**PREFERENCIAS, 'avatar': '<img>'},
                     {**PREFERENCIAS, 'accent': '#ffffff'}, {**PREFERENCIAS, 'themeName': 'otro'},
                     {**PREFERENCIAS, 'themeName': 'cyan'}, {**PREFERENCIAS, 'motto': 20},
                     {**PREFERENCIAS, 'motto': 'a' * 81}, {**PREFERENCIAS, 'alias': 'a' * 31},
                     {**PREFERENCIAS, 'alias': 'a\x00b'}, {**PREFERENCIAS, 'background': 'url(https://example.com)'},
                     {**PREFERENCIAS, 'viewMode': 'otro'}, {**PREFERENCIAS, 'sectionOrder': 'tareas'},
                     {**PREFERENCIAS, 'sectionOrder': [1]}, {**PREFERENCIAS, 'sectionOrder': ['desconocida']},
                     {**PREFERENCIAS, 'sectionOrder': ['seccion-tareas', 'seccion-tareas']}]
        for preferencias in invalidas:
            with self.subTest(preferencias=preferencias):
                respuesta = self.client.post(self.url, data={'preferences': json.dumps(preferencias), 'revision': '0'})
                self.assert_error(respuesta, 400)
        for revision in ('-1', '1.0', '', 'true', '2147483647', '9999999999999999999999999999'):
            self.assert_error(self.guardar(revision=revision), 400)
        self.assert_error(self.client.post(self.url, data={'preferences': '{', 'revision': '0'}), 400)
        self.assert_error(self.client.post(self.url, data={'revision': '0'}), 400)
        self.assert_error(self.client.post(self.url, json=PREFERENCIAS), 400)
        limites = {**PREFERENCIAS, 'motto': 'a' * 80, 'alias': 'a' * 30}
        self.assertEqual(self.guardar(limites).get_json()['preferences'], limites)

    def test_formulario_duplicado_y_carga_multiple_se_rechazan(self):
        formulario = MultiDict([('preferences', json.dumps(PREFERENCIAS)), ('revision', '0'), ('revision', '1')])
        self.assert_error(self.client.post(self.url, data=formulario), 400)
        formulario = MultiDict([('preferences', json.dumps(PREFERENCIAS)), ('revision', '0'),
                               ('photo', (foto_prueba(), 'uno.png')), ('photo', (foto_prueba(), 'dos.png'))])
        self.assert_error(self.client.post(self.url, data=formulario, content_type='multipart/form-data'), 400)
        self.assert_error(self.guardar(preferences='a' * 9000), 400)

    def test_foto_valida_se_normaliza_persiste_y_se_puede_quitar(self):
        respuesta = self.guardar(photo=(foto_prueba(), 'foto.png'))
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.get_json()
        self.assertIn('?v=1', datos['photoUrl'])
        db.session.remove()
        foto = self.client.get(datos['photoUrl'])
        self.assertEqual(foto.status_code, 200)
        self.assertEqual(foto.mimetype, 'image/jpeg')
        self.assertIn('private', foto.headers['Cache-Control'])
        self.assertIn('no-store', foto.headers['Cache-Control'])
        self.assertEqual(foto.headers['X-Content-Type-Options'], 'nosniff')
        with Image.open(io.BytesIO(foto.data)) as imagen:
            self.assertEqual(imagen.format, 'JPEG')
            self.assertLessEqual(max(imagen.size), 512)
            self.assertEqual(len(imagen.getexif()), 0)
        guardado = self.guardar({**PREFERENCIAS, 'alias': 'Ana'}, revision=1)
        self.assertIsNotNone(guardado.get_json()['photoUrl'])
        self.assertEqual(self.client.get(guardado.get_json()['photoUrl']).data, foto.data)
        eliminado = self.guardar(revision=2, remove_photo='true')
        self.assertIsNone(eliminado.get_json()['photoUrl'])
        self.assert_error(self.client.get(f'{self.url}/foto?v=3'), 404)

    def test_foto_aislada_sesion_y_no_existe(self):
        self.assert_error(self.client.get(f'{self.url}/foto'), 404)
        self.assertEqual(self.guardar(photo=(foto_prueba(), 'foto.png')).status_code, 200)
        cliente_otro = self.app.test_client()
        self.autenticar(cliente_otro, '10002')
        self.assert_error(cliente_otro.get(f'{self.url}/foto?v=1&aprendiz_id={self.ids[2]}'), 404)
        self.assert_error(self.app.test_client().get(f'{self.url}/foto'), 401)
        self.assert_error(self.client.get(f'/aprendiz/{self.ids[1]}/personalizacion/foto'), 401)

    def test_foto_formatos_admitidos(self):
        for indice, formato in enumerate(('JPEG', 'WebP', 'PNG')):
            with self.subTest(formato=formato):
                respuesta = self.guardar(revision=indice, photo=(foto_prueba(formato), f'foto.{formato.lower()}'))
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta.get_json()['revision'], indice + 1)

    def test_foto_quita_metadata_y_respeta_orientacion(self):
        contenido = io.BytesIO()
        imagen = Image.new('RGB', (900, 600), 'red')
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = 'Dato que no debe publicarse'
        imagen.save(contenido, 'JPEG', exif=exif)
        contenido.seek(0)
        respuesta = self.guardar(photo=(contenido, 'retrato.jpg'))
        self.assertEqual(respuesta.status_code, 200)
        foto = self.client.get(respuesta.get_json()['photoUrl'])
        self.assertNotIn(b'Dato que no debe publicarse', foto.data)
        with Image.open(io.BytesIO(foto.data)) as normalizada:
            self.assertEqual(normalizada.size, (341, 512))
            self.assertEqual(dict(normalizada.getexif()), {})

    def test_foto_invalida_no_reemplaza_datos(self):
        self.assertEqual(self.guardar(photo=(foto_prueba(), 'foto.png')).status_code, 200)
        original = self.client.get(f'{self.url}/foto').data
        casos = [(io.BytesIO(b'<svg></svg>'), 'foto.png', 400),
                 (io.BytesIO(b''), 'foto.png', 400),
                 (io.BytesIO(b'a' * (2 * 1024 * 1024 + 1)), 'foto.png', 413),
                 (foto_prueba('GIF'), 'foto.gif', 400),
                 (foto_prueba('PNG', (4001, 4000)), 'foto.png', 400),
                 (io.BytesIO(original[:80]), 'foto.jpg', 400)]
        for contenido, nombre, codigo in casos:
            with self.subTest(nombre=nombre, codigo=codigo):
                self.assert_error(self.guardar({**PREFERENCIAS, 'alias': 'No guardar'}, revision=1,
                                              photo=(contenido, nombre)), codigo)
        self.assert_error(self.guardar(revision=1, remove_photo='sí'), 400)
        self.assert_error(self.guardar(revision=1, remove_photo='true', photo=(foto_prueba(), 'foto.png')), 400)
        self.assertEqual(self.client.get(f'{self.url}/foto').data, original)
        self.assertEqual(self.client.get(self.url).get_json()['revision'], 1)
        self.assertEqual(self.client.get(self.url).get_json()['preferences'], PREFERENCIAS)

    def test_error_commit_revierte_preferencias_y_foto(self):
        self.assertEqual(self.guardar(photo=(foto_prueba(), 'foto.png')).status_code, 200)
        original = self.client.get(f'{self.url}/foto').data
        with self.assertLogs(self.app.logger, level='ERROR') as registros:
            with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('Dato privado del aprendiz')):
                self.assert_error(self.guardar({**PREFERENCIAS, 'alias': 'No guardado'}, revision=1,
                                              remove_photo='true'), 503)
        self.assertNotIn('Dato privado del aprendiz', '\n'.join(registros.output))
        self.assertEqual(self.client.get(self.url).get_json()['preferences'], PREFERENCIAS)
        self.assertEqual(self.client.get(f'{self.url}/foto').data, original)
        self.assertEqual(self.client.get(self.url).get_json()['revision'], 1)

    def test_error_lectura_base_de_datos(self):
        with patch('app.features.personalizacion_aprendiz.routes.aprendiz_de_sesion', side_effect=SQLAlchemyError()):
            self.assert_error(self.client.get(self.url), 503)
            self.assert_error(self.client.get(f'{self.url}/foto'), 503)

    def test_error_integridad_creacion_no_se_confunde_con_conflicto(self):
        with patch.object(db.session, 'commit', side_effect=IntegrityError('INSERT', {}, Exception('fallo'))):
            self.assert_error(self.guardar(), 503)
        self.assertFalse(self.client.get(self.url).get_json()['configured'])

    def test_csrf_se_exige_y_responde_json(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assert_error(self.guardar(), 400)
        self.assertFalse(self.client.get(self.url).get_json()['configured'])
        token_sesion = secrets.token_urlsafe(32)
        with self.client.session_transaction() as sesion:
            sesion['csrf_token'] = token_sesion
        token = URLSafeTimedSerializer(self.app.secret_key, salt='wtf-csrf-token').dumps(token_sesion)
        respuesta = self.guardar(csrf_token=token)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(self.client.get(self.url).get_json()['revision'], 1)

    def test_limite_global_carga_responde_json(self):
        self.app.config['MAX_CONTENT_LENGTH'] = 512
        self.assert_error(self.guardar(photo=(io.BytesIO(b'a' * 1024), 'foto.png')), 413)

    def test_eliminar_aprendiz_elimina_personalizacion(self):
        from app.features.personalizacion_aprendiz.models import PersonalizacionAprendiz
        self.assertEqual(self.guardar().status_code, 200)
        db.session.delete(db.session.get(Aprendiz, self.ids[2]))
        db.session.commit()
        self.assertEqual(PersonalizacionAprendiz.query.count(), 0)
