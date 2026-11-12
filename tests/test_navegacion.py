"""Pruebas unitarias de app/navegacion.py (menú de la ficha como datos)."""

import unittest
from types import SimpleNamespace

from app import create_app
from app.navegacion import modulos_ficha


class ModulosFichaTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False})
        self.ctx = self.app.test_request_context('/')
        self.ctx.push()
        self.ficha = SimpleNamespace(id=7)

    def tearDown(self):
        self.ctx.pop()

    def _labels(self, menu):
        return [m['label'] for m in menu['principales']]

    def test_principales_incluyen_aseo_y_no_alertas(self):
        menu = modulos_ficha(self.ficha, 'instructor.tareas', 'instructor')
        self.assertEqual(self._labels(menu), ['Visión general', 'Asistencia', 'Tareas', 'Aprendices',
                                              'Juicios', 'Planeación', 'Aseo'])
        secundarios = [m['label'] for g in menu['grupos'] for m in g['modulos']]
        self.assertNotIn('Aseo', secundarios)
        self.assertNotIn('Alertas', secundarios)
        self.assertEqual(menu['alertas']['label'], 'Alertas')

    def test_un_solo_modulo_activo(self):
        menu = modulos_ficha(self.ficha, 'instructor.ver_entregas', 'instructor')
        activos = [m['label'] for m in menu['principales'] if m['activo']]
        self.assertEqual(activos, ['Tareas'])
        self.assertIsNone(menu['activo_secundario'])
        self.assertFalse(menu['alertas']['activo'])

    def test_activo_por_blueprint(self):
        self.assertTrue(next(m for m in modulos_ficha(self.ficha, 'aseo.turnos', 'aseo')['principales']
                             if m['label'] == 'Aseo')['activo'])
        menu = modulos_ficha(self.ficha, 'ranking.ranking', 'ranking')
        self.assertEqual(menu['activo_secundario']['label'], 'Ranking')
        self.assertFalse(any(m['activo'] for m in menu['principales']))

    def test_alertas_activo_y_contador(self):
        menu = modulos_ficha(self.ficha, 'instructor.alertas', 'instructor', alertas=4)
        self.assertTrue(menu['alertas']['activo'])
        self.assertEqual(menu['alertas']['count'], 4)

    def test_corte_se_propaga_en_urls(self):
        menu = modulos_ficha(self.ficha, 'instructor.asistencia', 'instructor', corte_id=3)
        self.assertIn('corte_id=3', menu['principales'][1]['url'])
        self.assertNotIn('corte_id', menu['principales'][3]['url'])

    def test_context_processor_expone_nav_ficha(self):
        with self.app.test_request_context('/instructor/'):
            from flask import render_template_string
            self.assertEqual(render_template_string('{{ nav_ficha(None) is none }}'), 'True')


if __name__ == '__main__':
    unittest.main()
