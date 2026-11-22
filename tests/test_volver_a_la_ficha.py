"""Los módulos de la ficha no repiten «← Visión general»: la barra de la ficha ya lo ofrece."""

import re
import unittest
from pathlib import Path

PLANTILLAS = Path(__file__).resolve().parent.parent / 'app' / 'templates' / 'instructor'
MODULOS = ('alertas', 'aprendices', 'asistencia', 'casos_seguimiento', 'estadisticas', 'juicios',
           'materiales', 'observador', 'ranking', 'tareas', 'turnos_aseo', '_planeacion_cabecera')
ENLACE_VOLVER = re.compile(
    r'<a href="[^"]*instructor\.vision_general[^"]*"[^>]*class="[^"]*(?:btn-back|pl-back-link|nav-context-btn-back)[^"]*"',
    re.S)


class VolverALaFichaTest(unittest.TestCase):
    def test_ningun_modulo_repite_el_enlace_a_la_vision_general(self):
        for nombre in MODULOS:
            with self.subTest(plantilla=nombre):
                html = (PLANTILLAS / f'{nombre}.html').read_text(encoding='utf-8')
                self.assertIsNone(ENLACE_VOLVER.search(html))
                self.assertNotIn('&larr; Visión general', html)

    def test_la_barra_de_la_ficha_conserva_el_acceso_a_la_vision_general(self):
        from types import SimpleNamespace
        from app import create_app
        from app.navegacion import modulos_ficha
        app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                          'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False})
        with app.test_request_context('/'):
            menu = modulos_ficha(SimpleNamespace(id=5), 'instructor.tareas', 'instructor')
        primero = menu['principales'][0]
        self.assertEqual(primero['label'], 'Visión general')
        self.assertRegex(primero['url'], r'^/instructor/fichas/5(/resumen)?$')


if __name__ == '__main__':
    unittest.main()
