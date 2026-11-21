"""Desde un módulo de la ficha, «Volver» lleva a la visión general de esa ficha."""

import re
import unittest
from pathlib import Path

PLANTILLAS = Path(__file__).resolve().parent.parent / 'app' / 'templates' / 'instructor'
MODULOS = ('alertas', 'aprendices', 'asistencia', 'casos_seguimiento', 'estadisticas', 'juicios',
           'materiales', 'observador', 'ranking', 'tareas', 'turnos_aseo', '_planeacion_cabecera')
ENLACE_VOLVER = re.compile(r'<a href="([^"]+)"[^>]*class="[^"]*(?:btn-back|pl-back-link)[^"]*"[^>]*>(.*?)</a>', re.S)


class VolverALaFichaTest(unittest.TestCase):
    def test_cada_modulo_vuelve_a_la_vision_general(self):
        for nombre in MODULOS:
            with self.subTest(plantilla=nombre):
                html = (PLANTILLAS / f'{nombre}.html').read_text(encoding='utf-8')
                enlaces = ENLACE_VOLVER.findall(html)
                self.assertTrue(enlaces, 'sin enlace de volver')
                href, texto = enlaces[0]
                self.assertIn("url_for('instructor.vision_general', ficha_id=ficha.id)", href)
                self.assertIn('Visión general', texto)


if __name__ == '__main__':
    unittest.main()
