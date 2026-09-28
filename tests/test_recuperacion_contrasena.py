import hashlib
import secrets
import unittest
from datetime import timedelta
from urllib.parse import urlsplit
from unittest.mock import patch

from app import create_app, db
from app.helpers import utc_now
from app.models.instructor import Instructor
from app.routes.auth import _clave_limite_por_correo, _enviar_correo_recuperacion, _url_publica_configurada


class RecuperacionContrasenaTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'PUBLIC_BASE_URL': 'https://panel.example.com',
            'SMTP_HOST': 'smtp.example.com',
            'SMTP_PORT': 587,
            'SMTP_USER': 'avisos@example.com',
            'SMTP_PASSWORD': 'solo-en-memoria',
            'SMTP_FROM': 'SENA Control <avisos@example.com>',
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        self.instructor = Instructor(
            nombre='Instructora de Prueba',
            correo='instructora@example.com',
            rol='admin',
        )
        self.instructor.set_password('ClaveAnteriorSegura123!')
        db.session.add(self.instructor)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def test_solicitud_y_cambio_de_contrasena_invalidan_sesiones_anteriores(self):
        correo = self.app.test_client()
        enlace_enviado = {}

        def capturar_enlace(instructor, enlace):
            enlace_enviado['url'] = enlace
            return True

        with patch(
            'app.routes.auth._enviar_correo_recuperacion',
            side_effect=capturar_enlace,
        ):
            respuesta_solicitud = correo.post(
                '/recuperar-contrasena',
                data={'correo': self.instructor.correo.upper()},
            )

        self.assertEqual(respuesta_solicitud.status_code, 200)
        self.assertEqual(respuesta_solicitud.headers['Cache-Control'], 'no-store, max-age=0')
        self.assertEqual(respuesta_solicitud.headers['Referrer-Policy'], 'no-referrer')
        self.assertIn('Si existe una cuenta activa'.encode(), respuesta_solicitud.data)
        self.assertIn('url', enlace_enviado)
        self.assertTrue(enlace_enviado['url'].startswith(
            'https://panel.example.com/restablecer-contrasena#'
        ))

        token = urlsplit(enlace_enviado['url']).fragment
        db.session.refresh(self.instructor)
        self.assertEqual(
            self.instructor.password_reset_token_hash,
            hashlib.sha256(token.encode('ascii')).hexdigest(),
        )
        self.assertNotEqual(self.instructor.password_reset_token_hash, token)
        self.assertGreater(self.instructor.password_reset_expires_at, utc_now())

        sesion_anterior = self.app.test_client()
        with sesion_anterior.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.instructor.id}:1'
            sesion['_fresh'] = True

        respuesta_cambio = correo.post(
            '/restablecer-contrasena',
            data={
                'token': token,
                'password': 'ClaveNuevaSegura456!',
                'confirmacion': 'ClaveNuevaSegura456!',
            },
        )

        self.assertEqual(respuesta_cambio.status_code, 302)
        self.assertTrue(respuesta_cambio.headers['Location'].endswith('/login'))
        db.session.refresh(self.instructor)
        self.assertTrue(self.instructor.check_password('ClaveNuevaSegura456!'))
        self.assertEqual(self.instructor.auth_version, 2)
        self.assertIsNone(self.instructor.password_reset_token_hash)
        self.assertIsNone(self.instructor.password_reset_expires_at)
        self.assertEqual(sesion_anterior.get('/instructor/').status_code, 302)

    def test_enlace_vencido_no_cambia_la_contrasena(self):
        token = secrets.token_urlsafe(32)
        self.instructor.password_reset_token_hash = hashlib.sha256(
            token.encode('ascii')
        ).hexdigest()
        self.instructor.password_reset_expires_at = utc_now() - timedelta(seconds=1)
        db.session.commit()

        respuesta = self.app.test_client().post(
            '/restablecer-contrasena',
            data={
                'token': token,
                'password': 'ClaveNuevaSegura456!',
                'confirmacion': 'ClaveNuevaSegura456!',
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('El enlace no es válido o venció.'.encode(), respuesta.data)
        self.assertTrue(self.instructor.check_password('ClaveAnteriorSegura123!'))
        self.assertEqual(self.instructor.auth_version, 1)

    def test_envio_smtp_usa_tls_y_no_expone_el_token_en_logs(self):
        class ServidorSMTPFalso:
            def __init__(self):
                self.mensaje = None
                self.inicio_tls = False
                self.credenciales = None

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def starttls(self, context=None):
                self.inicio_tls = context is not None

            def login(self, usuario, clave):
                self.credenciales = (usuario, clave)

            def send_message(self, mensaje):
                self.mensaje = mensaje

        servidor = ServidorSMTPFalso()
        with self.app.app_context(), patch(
            'app.routes.auth.smtplib.SMTP', return_value=servidor
        ):
            enviado = _enviar_correo_recuperacion(
                self.instructor,
                'https://panel.example.com/restablecer-contrasena#token-de-prueba',
            )

        self.assertTrue(enviado)
        self.assertTrue(servidor.inicio_tls)
        self.assertEqual(servidor.credenciales, ('avisos@example.com', 'solo-en-memoria'))
        self.assertEqual(servidor.mensaje['To'], self.instructor.correo)
        self.assertIn('token-de-prueba', servidor.mensaje.get_content())

    def test_url_publica_y_clave_de_limite_validan_y_ocultan_el_correo(self):
        with self.app.app_context():
            self.assertEqual(
                _url_publica_configurada(),
                'https://panel.example.com',
            )
            self.app.config['PUBLIC_BASE_URL'] = 'https://panel.example.com/ruta'
            self.assertIsNone(_url_publica_configurada())

        with self.app.test_request_context(
            '/recuperar-contrasena',
            method='POST',
            data={'correo': 'Instructora@Example.com'},
        ):
            clave = _clave_limite_por_correo()

        self.assertTrue(clave.startswith('recuperacion:'))
        self.assertNotIn('instructora@example.com', clave)


if __name__ == '__main__':
    unittest.main()
