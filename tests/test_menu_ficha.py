"""Menú de módulos de la ficha: principales visibles y el resto en «Más módulos»."""

import re
import tempfile
import unittest
from datetime import date, timedelta

from flask import g

from app import create_app, db
from app.models import (
    ConfiguracionAlertas,
    ConfiguracionAlertasComite,
    ConfiguracionAseo,
    ConfiguracionRanking,
    Ficha,
    Instructor,
)

PRINCIPALES = ('Visión general', 'Asistencia', 'Tareas', 'Aprendices', 'Juicios', 'Planeación', 'Alertas')
SECUNDARIOS = ('Observador', 'Casos de seguimiento', 'Novedades', 'Fila de atención', 'Seguimiento TyT',
               'Aseo', 'Estadísticas', 'Materiales', 'Ranking', 'Grupos')


class MenuFichaTestCase(unittest.TestCase):
    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'UPLOAD_FOLDER': self.uploads.name,
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        instructor = Instructor(nombre='Instructora de prueba', correo='menu@sena.edu.co', rol='admin')
        instructor.set_password('clave-segura')
        db.session.add(instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='3000002', codigo_ficha='3000002', nombre_programa='Programa de prueba',
                           instructor_id=instructor.id, fecha_inicio=date.today() - timedelta(days=30),
                           fecha_fin=date.today() + timedelta(days=330))
        db.session.add(self.ficha)
        db.session.flush()
        db.session.add_all([ConfiguracionAlertas(ficha_id=self.ficha.id),
                            ConfiguracionAlertasComite(ficha_id=self.ficha.id),
                            ConfiguracionRanking(ficha_id=self.ficha.id),
                            ConfiguracionAseo(ficha_id=self.ficha.id)])
        db.session.commit()
        self.cliente = self.app.test_client()
        g.pop('_login_user', None)
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(instructor.id)
            sesion['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def _menu(self, ruta):
        respuesta = self.cliente.get(ruta)
        self.assertEqual(respuesta.status_code, 200, ruta)
        html = respuesta.get_data(as_text=True)
        nav = re.search(r'<nav class="ficha-nav"[\s\S]*?</nav>', html)
        self.assertIsNotNone(nav, f'{ruta} debe mostrar el menú de la ficha')
        mas = re.search(r'<div id="ficha-nav-mas"[^>]*popover[\s\S]*?</div>\s*</div>', html)
        self.assertIsNotNone(mas, f'{ruta} debe incluir el panel «Más módulos»')
        return nav.group(0), mas.group(0)

    @staticmethod
    def _textos(fragmento):
        return [re.sub(r'\s+', ' ', t).strip() for t in re.findall(r'<span class="ficha-nav-label">([^<]*)</span>', fragmento)]

    def test_modulos_principales_visibles_y_resto_en_mas(self):
        nav, mas = self._menu(f'/instructor/fichas/{self.ficha.id}/tareas')
        self.assertEqual(self._textos(nav.split('ficha-nav-more')[0]), list(PRINCIPALES))
        self.assertEqual(self._textos(mas), list(SECUNDARIOS))
        self.assertIn('popovertarget="ficha-nav-mas"', nav)
        self.assertIn('aria-current="page"', nav.split('ficha-nav-more')[0])

    def test_panel_mas_agrupa_los_modulos_con_titulo(self):
        _, mas = self._menu(f'/instructor/fichas/{self.ficha.id}/tareas')
        self.assertEqual(re.findall(r'<p class="ficha-nav-group-title"[^>]*>([^<]+)</p>', mas),
                         ['Seguimiento y convivencia', 'Recursos y participación'])

    def test_modulo_activo_dentro_de_mas_resalta_el_boton(self):
        nav, mas = self._menu(f'/instructor/fichas/{self.ficha.id}/ranking')
        boton = re.search(r'<button[^>]*ficha-nav-more[^>]*>[\s\S]*?</button>', nav).group(0)
        self.assertIn('is-active', boton)
        self.assertIn('Ranking', boton)
        self.assertRegex(mas, r'aria-current="page"[^>]*>[\s\S]*?Ranking')
        self.assertNotIn('aria-current="page"', nav.split('ficha-nav-more')[0])

    def test_boton_mas_sin_modulo_activo_dice_mas_modulos(self):
        nav, _ = self._menu(f'/instructor/fichas/{self.ficha.id}/asistencia')
        boton = re.search(r'<button[^>]*ficha-nav-more[^>]*>[\s\S]*?</button>', nav).group(0)
        self.assertNotIn('is-active', boton)
        self.assertIn('Más módulos', boton)

    def test_menu_visible_en_fila_tyt_y_novedades(self):
        for ruta, etiqueta in ((f'/instructor/fichas/{self.ficha.id}/fila-atencion', 'Fila de atención'),
                               (f'/instructor/fichas/{self.ficha.id}/seguimiento-tyt', 'Seguimiento TyT'),
                               (f'/instructor/fichas/{self.ficha.id}/novedades-productiva', 'Novedades')):
            nav, _ = self._menu(ruta)
            boton = re.search(r'<button[^>]*ficha-nav-more[^>]*>[\s\S]*?</button>', nav).group(0)
            self.assertIn(etiqueta, boton, ruta)

    def test_paginas_sin_ficha_no_muestran_el_menu(self):
        html = self.cliente.get('/instructor/').get_data(as_text=True)
        self.assertNotIn('class="ficha-nav"', html)


if __name__ == '__main__':
    unittest.main()
