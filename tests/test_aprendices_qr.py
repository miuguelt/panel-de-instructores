import unittest
import re
from datetime import date

from app import create_app, db
from app.models import Ficha, Instructor


class AprendicesQrTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Instructor QR',
            correo='instructor-qr@sena.edu.co',
            rol='admin',
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='2824567',
            codigo_ficha='2824567',
            nombre_programa='ADSO - Programación de Software',
            instructor_id=self.instructor.id,
            fecha_inicio=date.today(),
        )
        db.session.add(self.ficha)
        db.session.commit()

        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.instructor.id)
            sess['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def test_vista_aprendices_incluye_elementos_proyeccion_tv(self):
        resp = self.client.get(f'/instructor/fichas/{self.ficha.id}/aprendices')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Botones y disparadores en la tarjeta de herramientas
        self.assertIn('id="btn-open-tv-modal"', html)
        self.assertIn('id="btn-open-tv-modal-action"', html)
        self.assertIn('Ampliar', html)

        # Modal de proyección en máxima resolución
        self.assertIn('id="qr-tv-modal"', html)
        self.assertIn('MODO PROYECCIÓN TV', html)
        self.assertIn('id="qr-code-tv"', html)
        self.assertIn('id="btn-qr-tv-fullscreen"', html)
        self.assertIn('Pantalla Completa', html)
        self.assertIn('id="btn-download-qr-hd"', html)
        self.assertIn('Descargar QR HD (PNG)', html)

        # Instrucciones de acceso para aprendices
        self.assertIn('¿Cómo ingresar?', html)
        self.assertIn('Abre la cámara de tu celular', html)
        self.assertIn('Ingresa tu número de documento', html)

    def test_vista_aprendices_comparte_unico_enlace_del_sitio_en_qr_y_campo(self):
        with self.client.session_transaction(base_url='https://control.enlinea.sbs') as sess:
            sess['_user_id'] = str(self.instructor.id)
            sess['_fresh'] = True
        resp = self.client.get(
            f'/instructor/fichas/{self.ficha.id}/aprendices',
            base_url='https://control.enlinea.sbs',
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        enlace_esperado = f'https://control.enlinea.sbs/aprendiz/{self.ficha.id}'
        campo_enlace = re.search(r'<input id="learner-access-url"[^>]*value="([^"]+)"', html)
        enlace_qr_ampliado = re.search(
            r'<code class="qr-tv-url-text" id="qr-tv-current-url">([^<]+)</code>',
            html,
        )

        self.assertIsNotNone(campo_enlace)
        self.assertIsNotNone(enlace_qr_ampliado)
        self.assertEqual(campo_enlace.group(1), enlace_esperado)
        self.assertEqual(enlace_qr_ampliado.group(1), enlace_esperado)
        self.assertNotIn('Localhost', html)
        self.assertNotIn('btn-switch-url-', html)
        self.assertNotIn('modal-pill-', html)
        self.assertNotIn('data-url-local=', html)
        self.assertNotIn('data-url-wifi=', html)
