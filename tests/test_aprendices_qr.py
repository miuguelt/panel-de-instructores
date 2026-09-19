import unittest
from datetime import date
from unittest.mock import patch

from app import create_app, db
from app.models import Ficha, Instructor
from app.routes.instructor import _obtener_ip_local


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

    def test_obtener_ip_local_devuelve_cadena_valida(self):
        ip = _obtener_ip_local()
        self.assertIsInstance(ip, str)
        self.assertTrue(len(ip) >= 7)

    @patch('app.routes.instructor.socket.socket')
    def test_obtener_ip_local_fallback_en_error(self, mock_socket):
        mock_socket.side_effect = Exception('Network unreachable')
        ip = _obtener_ip_local()
        self.assertEqual(ip, '127.0.0.1')

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

    def test_vista_aprendices_con_ip_local_muestra_selector_red(self):
        with patch('app.routes.instructor._obtener_ip_local', return_value='192.168.1.101'):
            resp = self.client.get(f'/instructor/fichas/{self.ficha.id}/aprendices', headers={'Host': 'localhost:8009'})
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)

            # Selector en tarjeta
            self.assertIn('192.168.1.101', html)
            self.assertIn('id="btn-switch-url-wifi"', html)
            self.assertIn('id="btn-switch-url-local"', html)

            # Selector en modal
            self.assertIn('id="modal-pill-wifi"', html)
            self.assertIn('id="modal-pill-local"', html)
