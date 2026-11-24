"""Reglas de composición de la tarjeta de ficha en «Mis fichas».

La tarjeta no tiene padding propio: el encabezado y el cuerpo ponen el suyo.
Sin padding en el cuerpo, el contenido queda pegado al borde y se sale de él.
"""

import re
import unittest
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / 'app' / 'static' / 'css'


def bloques(css, selector):
    """Devuelve el cuerpo de cada regla cuyo selector contiene `selector` exacto."""
    patron = re.compile(r'([^{}]+)\{([^{}]*)\}')
    salida = []
    for sel, cuerpo in patron.findall(re.sub(r'/\*.*?\*/', '', css, flags=re.S)):
        nombres = [s.strip() for s in sel.split(',')]
        if selector in nombres:
            salida.append(cuerpo)
    return salida


class FichasPanelCssTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = (CSS / 'fichas_panel.css').read_text(encoding='utf-8')
        cls.estilos = (CSS / 'styles.css').read_text(encoding='utf-8')

    def test_cuerpo_de_la_tarjeta_tiene_margen_y_contenedor(self):
        cuerpo = ' '.join(bloques(self.panel, '.ficha-card-body'))
        self.assertRegex(cuerpo, r'padding\s*:')
        self.assertRegex(cuerpo, r'min-inline-size\s*:\s*0')
        # @container no aplica estilos al propio contenedor: lo es la tarjeta.
        tarjeta = ' '.join(bloques(self.panel, '.ficha-card-v2'))
        self.assertRegex(tarjeta, r'container-type\s*:\s*inline-size')

    def test_dos_columnas_cuando_la_tarjeta_es_amplia(self):
        self.assertRegex(self.panel, r'@container\s*\(min-width:\s*56rem\)')

    def test_la_tarjeta_no_simula_ser_un_enlace(self):
        for selector in ('.card-ficha', '.card-ficha:hover', '.dashboard-cards .card-ficha:hover'):
            for cuerpo in bloques(self.estilos, selector):
                self.assertNotIn('cursor: pointer', cuerpo, selector)
                self.assertNotIn('translateY', cuerpo, selector)

    def test_rejilla_sin_columnas_vacias(self):
        rejilla = ' '.join(bloques(self.estilos, '.dashboard-cards'))
        self.assertIn('auto-fit', rejilla)
        self.assertNotIn('auto-fill', rejilla)
        # Como máximo dos columnas: cada una mide al menos la mitad del ancho.
        self.assertIn('calc((100% - 20px) / 2)', rejilla)
        impar = ' '.join(bloques(self.panel, '.dashboard-cards > .card-ficha:last-child:nth-child(odd)'))
        self.assertRegex(impar, r'grid-column\s*:\s*1\s*/\s*-1')


if __name__ == '__main__':
    unittest.main()
