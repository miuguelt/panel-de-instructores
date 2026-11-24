"""«Mis fichas» es la única lista de fichas.

«Inicio» y «Fichas» eran dos listas de lo mismo. Ahora la barra superior tiene
una sola entrada, «Mis fichas», y crear o importar una ficha se hace desde un
diálogo en esa misma página. La dirección antigua `/instructor/fichas` responde
302 hacia «Mis fichas» para no romper marcadores; el POST de crear se conserva.
"""

import re
import secrets
import unittest

from app import create_app, db
from app.models import Ficha, Instructor


class MisFichasUnificadaTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
                               'RATELIMIT_ENABLED': False, 'SECRET_KEY': secrets.token_hex(16)})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.instructor = Instructor(nombre='Instructor Uno', correo='mis-fichas@example.com')
        self.instructor.set_password(secrets.token_urlsafe(16))
        db.session.add(self.instructor)
        db.session.commit()
        self.cliente = self.app.test_client()
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_la_direccion_antigua_lleva_a_mis_fichas(self):
        respuesta = self.cliente.get('/instructor/fichas')
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta.headers['Location'].endswith('/instructor/'))

    def test_crear_ficha_manual_vuelve_a_mis_fichas(self):
        respuesta = self.cliente.post('/instructor/fichas', data={'codigo': '4040', 'nombre_programa': 'ADSO'})
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta.headers['Location'].endswith('/instructor/'))
        self.assertIsNotNone(Ficha.query.filter_by(codigo='4040').first())

    def test_crear_e_importar_viven_en_un_dialogo_de_mis_fichas(self):
        html = self.cliente.get('/instructor/').get_data(as_text=True)
        dialogo = re.search(r'<dialog id="nueva-ficha"[\s\S]*?</dialog>', html)
        self.assertIsNotNone(dialogo)
        self.assertIn('action="/instructor/fichas/importar-reporte"', dialogo.group(0))
        self.assertIn('name="archivo"', dialogo.group(0))
        self.assertIn('action="/instructor/fichas"', dialogo.group(0))
        self.assertIn('data-abrir-modal="nueva-ficha"', html)

    def test_sin_fichas_hay_una_sola_accion(self):
        html = self.cliente.get('/instructor/').get_data(as_text=True)
        contenido = html[html.index('<main'):html.index('<dialog id="nueva-ficha"')]
        self.assertEqual(contenido.count('data-abrir-modal="nueva-ficha"'), 1)
        self.assertNotIn('href="/instructor/fichas', contenido)

    def test_la_barra_superior_tiene_una_sola_entrada_de_fichas(self):
        html = self.cliente.get('/instructor/').get_data(as_text=True)
        barra = re.search(r'<div class="nav-primary"[\s\S]*?</div>', html).group(0)
        etiquetas = re.findall(r'<span>([^<]+)</span>', barra)
        self.assertIn('Mis fichas', etiquetas)
        self.assertIn('Fichas por certificar', etiquetas)
        for vieja in ('Inicio', 'Fichas', 'Comité'):
            self.assertNotIn(vieja, etiquetas)
        self.assertRegex(html, r'<h1 id="dashboard-title">Mis fichas</h1>')

    def test_notificaciones_no_se_repite_en_el_menu_de_escritorio(self):
        html = self.cliente.get('/instructor/').get_data(as_text=True)
        menu = re.search(r'<div id="nav-user-menu"[\s\S]*?</form>', html).group(0)
        movil = re.search(r'<div class="nav-user-links"[\s\S]*?</div>', menu).group(0)
        # El enlace del menú queda solo dentro del bloque móvil; en escritorio está la campana.
        self.assertEqual(menu.count('/instructor/notificaciones'), movil.count('/instructor/notificaciones'))
        self.assertEqual(movil.count('/instructor/notificaciones'), 1)


if __name__ == '__main__':
    unittest.main()
