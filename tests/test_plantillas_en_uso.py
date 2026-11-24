"""Toda plantilla se usa: la renderiza una ruta o la incluye otra plantilla.

Una plantilla huérfana confunde a quien mantiene la app (parece una pantalla
viva y no lo es) y suele quedar con datos o textos desactualizados.
"""

import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / 'app'
PLANTILLAS = APP / 'templates'
REFERENCIA = re.compile(r"""['"]([\w/.-]+\.html)['"]""")


def referencias():
    nombres = set()
    for ruta in [*APP.rglob('*.py'), *PLANTILLAS.rglob('*.html')]:
        nombres.update(REFERENCIA.findall(ruta.read_text(encoding='utf-8')))
    return nombres


class PlantillasEnUsoTest(unittest.TestCase):
    def test_ninguna_plantilla_queda_huerfana(self):
        usadas = referencias()
        huerfanas = []
        for ruta in sorted(PLANTILLAS.rglob('*.html')):
            relativa = ruta.relative_to(PLANTILLAS).as_posix()
            # Las rutas de un blueprint pueden nombrar la plantilla sin su carpeta.
            if relativa not in usadas and ruta.name not in usadas and relativa != 'base.html':
                huerfanas.append(relativa)
        self.assertEqual(huerfanas, [])

    def test_el_detector_encuentra_includes_y_render_template(self):
        self.assertEqual(REFERENCIA.findall("render_template('alertas.html')"), ['alertas.html'])
        self.assertEqual(REFERENCIA.findall('{% include "instructor/_ficha_card.html" %}'),
                         ['instructor/_ficha_card.html'])


if __name__ == '__main__':
    unittest.main()
