"""Los formularios de contraseña deben poder enviarse sobre HTTPS con CSRF activo.

Flask-WTF exige la cabecera Referer en toda solicitud HTTPS protegida
(WTF_CSRF_SSL_STRICT). Una página que declara `no-referrer` hace que el
navegador la omita en su propio formulario, y el envío se rechaza siempre con
«La sesión del formulario expiró». Las pruebas con CSRF desactivado o sobre
HTTP no detectan ese fallo.
"""

import re
import unittest

from app import create_app, db
from app.models.instructor import Instructor

BASE_HTTPS = 'https://panel.example.com'
PAGINAS = (
    '/cambiar-password-obligatorio',
    '/recuperar-contrasena',
    '/restablecer-contrasena?token=' + 'a' * 43,
)


class CsrfRefererFormulariosPasswordTestCase(unittest.TestCase):

    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': True,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        self.instructor = Instructor(
            nombre='Instructor Temporal',
            correo='temporal@sena.edu.co',
            rol='colaborador',
            activo=True,
            auth_version=1,
            debe_cambiar_password=True,
        )
        self.instructor.set_password('ClaveTemporal1!')
        db.session.add(self.instructor)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _cliente_autenticado(self):
        cliente = self.app.test_client()
        with cliente.session_transaction(base_url=BASE_HTTPS) as sesion:
            sesion['_user_id'] = f'{self.instructor.id}:1'
            sesion['_fresh'] = True
        return cliente

    @staticmethod
    def _token_csrf(html):
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def test_paginas_de_password_permiten_referer_al_mismo_origen(self):
        """Ninguna página suprime el Referer que su propio formulario necesita."""
        for ruta in PAGINAS:
            with self.subTest(ruta=ruta):
                # Las páginas de recuperación son anónimas; con sesión de clave
                # temporal el interceptor las redirige al cambio obligatorio.
                cliente = (
                    self._cliente_autenticado()
                    if ruta == '/cambiar-password-obligatorio'
                    else self.app.test_client()
                )
                respuesta = cliente.get(ruta, base_url=BASE_HTTPS)
                self.assertEqual(respuesta.status_code, 200)
                html = respuesta.data.decode('utf-8')
                politicas = re.findall(r'<meta name="referrer" content="([^"]+)"', html)
                cabecera = respuesta.headers.get('Referrer-Policy')
                if cabecera:
                    politicas.append(cabecera)
                self.assertTrue(politicas, 'La página debe declarar su política de referente.')
                for politica in politicas:
                    # same-origin: el Referer llega al propio servidor (CSRF)
                    # y nunca a terceros (el token del enlace no se filtra).
                    self.assertEqual(politica, 'same-origin')

    def test_cambio_obligatorio_por_https_con_csrf_actualiza_la_password(self):
        cliente = self._cliente_autenticado()
        pagina = cliente.get('/cambiar-password-obligatorio', base_url=BASE_HTTPS)
        token = self._token_csrf(pagina.data.decode('utf-8'))

        respuesta = cliente.post(
            '/cambiar-password-obligatorio',
            base_url=BASE_HTTPS,
            headers={'Referer': f'{BASE_HTTPS}/cambiar-password-obligatorio'},
            data={
                'csrf_token': token,
                'nueva_password': 'ClaveDefinitiva2026!',
                'confirmacion': 'ClaveDefinitiva2026!',
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta.headers['Location'].endswith('/instructor/'))
        db.session.refresh(self.instructor)
        self.assertFalse(self.instructor.debe_cambiar_password)
        self.assertTrue(self.instructor.check_password('ClaveDefinitiva2026!'))

    def test_post_https_sin_referer_se_rechaza_y_no_cambia_la_password(self):
        """Documenta la causa: sin Referer, la protección CSRF rechaza el envío."""
        cliente = self._cliente_autenticado()
        pagina = cliente.get('/cambiar-password-obligatorio', base_url=BASE_HTTPS)
        token = self._token_csrf(pagina.data.decode('utf-8'))

        respuesta = cliente.post(
            '/cambiar-password-obligatorio',
            base_url=BASE_HTTPS,
            data={
                'csrf_token': token,
                'nueva_password': 'ClaveDefinitiva2026!',
                'confirmacion': 'ClaveDefinitiva2026!',
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(self.instructor)
        self.assertTrue(self.instructor.debe_cambiar_password)
        self.assertTrue(self.instructor.check_password('ClaveTemporal1!'))


if __name__ == '__main__':
    unittest.main()
