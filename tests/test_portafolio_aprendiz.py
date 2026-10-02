import unittest
from unittest.mock import patch
from sqlalchemy.exc import SQLAlchemyError

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor
from app.models.aprendiz import normalizar_url_portafolio


class PortafolioAprendizTestCase(unittest.TestCase):
    """Pruebas unitarias y de integración para enlaces de GitHub y Notion del aprendiz."""

    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'SECRET_KEY': 'clave-pruebas',
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.client = self.app.test_client()

        # Datos base
        self.instructor = Instructor(
            nombre='Instructor Carlos',
            correo='carlos@sena.edu.co',
            rol='instructor',
            auth_version=1,
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)

        self.otro_instructor = Instructor(
            nombre='Instructor Externo',
            correo='externo@sena.edu.co',
            rol='instructor',
            auth_version=1,
        )
        self.otro_instructor.set_password('clave-segura')
        db.session.add(self.otro_instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='2692929',
            nombre_programa='Análisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
        )
        db.session.add(self.ficha)
        db.session.flush()

        self.aprendiz = Aprendiz(
            documento='1098765432',
            nombre='Valentina',
            apellidos='Gómez Rojas',
            ficha_id=self.ficha.id,
            correo='valentina@sena.edu.co',
            estado='EN_FORMACION',
            activo=True,
        )
        db.session.add(self.aprendiz)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def test_modelo_campos_y_propiedad_portafolio(self):
        """El modelo Aprendiz debe persistir enlaces y reportar tiene_enlaces_portafolio."""
        self.assertIsNone(self.aprendiz.enlace_github)
        self.assertIsNone(self.aprendiz.enlace_notion)
        self.assertFalse(self.aprendiz.tiene_enlaces_portafolio)

        self.aprendiz.enlace_github = 'https://github.com/valentina-sena'
        self.assertTrue(self.aprendiz.tiene_enlaces_portafolio)

        self.aprendiz.enlace_github = None
        self.aprendiz.enlace_notion = 'https://notion.so/bitacora-valentina'
        self.assertTrue(self.aprendiz.tiene_enlaces_portafolio)

        self.aprendiz.enlace_github = 'https://github.com/valentina-sena'
        db.session.commit()

        aprendiz_recuperado = db.session.get(Aprendiz, self.aprendiz.id)
        self.assertEqual(aprendiz_recuperado.enlace_github, 'https://github.com/valentina-sena')
        self.assertEqual(aprendiz_recuperado.enlace_notion, 'https://notion.so/bitacora-valentina')
        self.assertTrue(aprendiz_recuperado.tiene_enlaces_portafolio)

    def test_normalizar_url_portafolio_casos_validos_y_limpieza(self):
        """Valida que normalizar_url_portafolio limpie y autoanteponga https si es necesario."""
        self.assertIsNone(normalizar_url_portafolio(None))
        self.assertIsNone(normalizar_url_portafolio(''))
        self.assertIsNone(normalizar_url_portafolio('   '))

        url_github = normalizar_url_portafolio('github.com/aprendiz/proyecto', tipo='github')
        self.assertEqual(url_github, 'https://github.com/aprendiz/proyecto')

        url_notion = normalizar_url_portafolio('https://aprendiz.notion.site/Bitacora-1234', tipo='notion')
        self.assertEqual(url_notion, 'https://aprendiz.notion.site/Bitacora-1234')

    def test_normalizar_url_portafolio_errores_validacion(self):
        """Debe lanzar ValueError ante enlaces inválidos, dominios equivocados o exceso de longitud."""
        with self.assertRaises(ValueError) as ctx:
            normalizar_url_portafolio('texto-invalido-sin-punto')
        self.assertIn('estructura válida', str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            normalizar_url_portafolio('https://gitlab.com/repo', tipo='github')
        self.assertIn('github.com', str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            normalizar_url_portafolio('https://google.com/doc', tipo='notion')
        self.assertIn('notion.so', str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            normalizar_url_portafolio('https://github.com/' + ('a' * 500), tipo='github')
        self.assertIn('500 caracteres', str(ctx.exception))

    def test_aprendiz_guardar_portafolio_exito_formulario(self):
        """El aprendiz puede guardar sus enlaces mediante formulario tradicional."""
        with self.client.session_transaction() as sess:
            sess['aprendiz_documento'] = self.aprendiz.documento
            sess['aprendiz_ficha_id'] = self.ficha.id

        respuesta = self.client.post(
            f'/aprendiz/{self.ficha.id}/guardar-portafolio',
            data={
                'enlace_github': 'https://github.com/valentina/adso',
                'enlace_notion': 'https://valentina.notion.site/bitacora',
            },
            follow_redirects=True,
        )
        self.assertEqual(respuesta.status_code, 200)

        db.session.refresh(self.aprendiz)
        self.assertEqual(self.aprendiz.enlace_github, 'https://github.com/valentina/adso')
        self.assertEqual(self.aprendiz.enlace_notion, 'https://valentina.notion.site/bitacora')

    def test_aprendiz_guardar_portafolio_exito_ajax(self):
        """El aprendiz puede guardar enlaces por AJAX recibiendo respuesta JSON."""
        with self.client.session_transaction() as sess:
            sess['aprendiz_documento'] = self.aprendiz.documento
            sess['aprendiz_ficha_id'] = self.ficha.id

        respuesta = self.client.post(
            f'/aprendiz/{self.ficha.id}/guardar-portafolio',
            json={
                'enlace_github': 'github.com/valentina/portafolio',
                'enlace_notion': 'notion.so/valentina/bitacora',
            },
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.get_json()
        self.assertTrue(datos.get('ok'))
        self.assertEqual(datos.get('enlace_github'), 'https://github.com/valentina/portafolio')
        self.assertEqual(datos.get('enlace_notion'), 'https://notion.so/valentina/bitacora')

        db.session.refresh(self.aprendiz)
        self.assertEqual(self.aprendiz.enlace_github, 'https://github.com/valentina/portafolio')

    def test_aprendiz_guardar_portafolio_limpiar_enlaces(self):
        """Enviar cadenas vacías debe remover los enlaces previamente registrados."""
        self.aprendiz.enlace_github = 'https://github.com/existente'
        self.aprendiz.enlace_notion = 'https://notion.so/existente'
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['aprendiz_documento'] = self.aprendiz.documento
            sess['aprendiz_ficha_id'] = self.ficha.id

        respuesta = self.client.post(
            f'/aprendiz/{self.ficha.id}/guardar-portafolio',
            json={'enlace_github': '', 'enlace_notion': ''},
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.get_json()
        self.assertTrue(datos.get('ok'))
        self.assertIsNone(datos.get('enlace_github'))
        self.assertIsNone(datos.get('enlace_notion'))

        db.session.refresh(self.aprendiz)
        self.assertIsNone(self.aprendiz.enlace_github)
        self.assertIsNone(self.aprendiz.enlace_notion)

    def test_aprendiz_guardar_portafolio_validacion_invalida(self):
        """URL no válida debe retornar error 400 en AJAX o redirección con mensaje en formulario."""
        with self.client.session_transaction() as sess:
            sess['aprendiz_documento'] = self.aprendiz.documento
            sess['aprendiz_ficha_id'] = self.ficha.id

        # AJAX
        resp_ajax = self.client.post(
            f'/aprendiz/{self.ficha.id}/guardar-portafolio',
            json={'enlace_github': 'https://invalido.com/repo', 'enlace_notion': ''},
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(resp_ajax.status_code, 400)
        self.assertIn('github.com', resp_ajax.get_json().get('error', ''))

        # Formulario normal
        resp_form = self.client.post(
            f'/aprendiz/{self.ficha.id}/guardar-portafolio',
            data={'enlace_github': 'https://invalido.com/repo', 'enlace_notion': ''},
            follow_redirects=True,
        )
        self.assertEqual(resp_form.status_code, 200)
        self.assertIn(b'github.com', resp_form.data)

    def test_aprendiz_guardar_portafolio_sin_sesion(self):
        """Petición sin sesión válida debe ser rechazada."""
        resp_ajax = self.client.post(
            f'/aprendiz/{self.ficha.id}/guardar-portafolio',
            json={'enlace_github': 'https://github.com/repo'},
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(resp_ajax.status_code, 401)

        resp_form = self.client.post(
            f'/aprendiz/{self.ficha.id}/guardar-portafolio',
            data={'enlace_github': 'https://github.com/repo'},
            follow_redirects=False,
        )
        self.assertEqual(resp_form.status_code, 302)

    def test_aprendiz_guardar_portafolio_aprendiz_inexistente(self):
        """Petición con documento que ya no existe en la ficha debe responder 404 o 302."""
        with self.client.session_transaction() as sess:
            sess['aprendiz_documento'] = '9999999999'
            sess['aprendiz_ficha_id'] = self.ficha.id

        resp_ajax = self.client.post(
            f'/aprendiz/{self.ficha.id}/guardar-portafolio',
            json={'enlace_github': 'https://github.com/repo'},
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(resp_ajax.status_code, 404)

        resp_form = self.client.post(
            f'/aprendiz/{self.ficha.id}/guardar-portafolio',
            data={'enlace_github': 'https://github.com/repo'},
            follow_redirects=False,
        )
        self.assertEqual(resp_form.status_code, 302)

    def test_aprendiz_guardar_portafolio_error_base_datos(self):
        """Maneja excepciones de base de datos con rollback adecuado."""
        with self.client.session_transaction() as sess:
            sess['aprendiz_documento'] = self.aprendiz.documento
            sess['aprendiz_ficha_id'] = self.ficha.id

        with patch('app.routes.aprendiz.db.session.commit', side_effect=SQLAlchemyError('Error simulado')):
            resp_ajax = self.client.post(
                f'/aprendiz/{self.ficha.id}/guardar-portafolio',
                json={'enlace_github': 'https://github.com/valentina/repo'},
                headers={'Accept': 'application/json'},
            )
            self.assertEqual(resp_ajax.status_code, 500)

            resp_form = self.client.post(
                f'/aprendiz/{self.ficha.id}/guardar-portafolio',
                data={'enlace_github': 'https://github.com/valentina/repo'},
                follow_redirects=False,
            )
            self.assertEqual(resp_form.status_code, 302)

    def test_instructor_guardar_portafolio_exito_y_permisos(self):
        """Instructor autorizado puede actualizar enlaces de aprendiz; no autorizado es rechazado."""
        # Login instructor titular
        self.client.post('/login', data={'correo': 'carlos@sena.edu.co', 'password': 'clave-segura'})

        # Actualización exitosa formulario
        resp = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/aprendices/{self.aprendiz.id}/portafolio',
            data={
                'enlace_github': 'https://github.com/valentina/proyectos',
                'enlace_notion': 'https://notion.so/valentina/evidencias',
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        db.session.refresh(self.aprendiz)
        self.assertEqual(self.aprendiz.enlace_github, 'https://github.com/valentina/proyectos')

        # Actualización exitosa AJAX
        resp_ajax = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/aprendices/{self.aprendiz.id}/portafolio',
            json={
                'enlace_github': 'https://github.com/valentina/nuevo',
                'enlace_notion': '',
            },
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(resp_ajax.status_code, 200)
        self.assertTrue(resp_ajax.get_json().get('ok'))
        db.session.refresh(self.aprendiz)
        self.assertEqual(self.aprendiz.enlace_github, 'https://github.com/valentina/nuevo')
        self.assertIsNone(self.aprendiz.enlace_notion)

        # Validación inválida desde instructor
        resp_invalido = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/aprendices/{self.aprendiz.id}/portafolio',
            json={'enlace_github': 'https://invalido.com/repo'},
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(resp_invalido.status_code, 400)

        # Error en base de datos desde instructor
        with patch('app.routes.instructor.db.session.commit', side_effect=SQLAlchemyError('Error simulado')):
            resp_db = self.client.post(
                f'/instructor/fichas/{self.ficha.id}/aprendices/{self.aprendiz.id}/portafolio',
                json={'enlace_github': 'https://github.com/valentina/otro'},
                headers={'Accept': 'application/json'},
            )
            self.assertEqual(resp_db.status_code, 500)

            resp_db_form = self.client.post(
                f'/instructor/fichas/{self.ficha.id}/aprendices/{self.aprendiz.id}/portafolio',
                data={'enlace_github': 'https://github.com/valentina/otro'},
                follow_redirects=False,
            )
            self.assertEqual(resp_db_form.status_code, 302)

        # Logout e intento con instructor sin acceso a la ficha
        self.client.post('/logout')
        self.client.post('/login', data={'correo': 'externo@sena.edu.co', 'password': 'clave-segura'})
        resp_denegado = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/aprendices/{self.aprendiz.id}/portafolio',
            json={'enlace_github': 'https://github.com/intento'},
            headers={'Accept': 'application/json'},
        )
        self.assertEqual(resp_denegado.status_code, 403)

    def test_vistas_renderizan_enlaces_portafolio(self):
        """Las vistas del aprendiz y del instructor deben mostrar los enlaces registrados."""
        self.aprendiz.enlace_github = 'https://github.com/valentina/panel-repo'
        self.aprendiz.enlace_notion = 'https://valentina.notion.site/bitacora-adso'
        db.session.commit()

        # Vista Panel Aprendiz
        with self.client.session_transaction() as sess:
            sess['aprendiz_documento'] = self.aprendiz.documento
            sess['aprendiz_ficha_id'] = self.ficha.id

        resp_panel = self.client.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(resp_panel.status_code, 200)
        self.assertIn(b'https://github.com/valentina/panel-repo', resp_panel.data)
        self.assertIn(b'https://valentina.notion.site/bitacora-adso', resp_panel.data)

        # Vista Directorio de Aprendices (Instructor)
        self.client.post('/login', data={'correo': 'carlos@sena.edu.co', 'password': 'clave-segura'})
        resp_dir = self.client.get(f'/instructor/fichas/{self.ficha.id}/aprendices')
        self.assertEqual(resp_dir.status_code, 200)
        self.assertIn(b'https://github.com/valentina/panel-repo', resp_dir.data)
        self.assertIn(b'https://valentina.notion.site/bitacora-adso', resp_dir.data)

        # Vista Historial Aprendiz (Instructor)
        resp_historial = self.client.get(f'/instructor/fichas/{self.ficha.id}/aprendices/{self.aprendiz.id}/historial')
        self.assertEqual(resp_historial.status_code, 200)
        self.assertIn(b'https://github.com/valentina/panel-repo', resp_historial.data)
        self.assertIn(b'https://valentina.notion.site/bitacora-adso', resp_historial.data)
