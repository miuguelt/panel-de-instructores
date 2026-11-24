"""Un solo juego de umbrales para colorear porcentajes.

DESIGN.md: verde desde 80 %, amarillo desde 60 % y rojo por debajo
(`app/services/visualizacion.py`). Las plantillas no escriben sus propios
cortes (85/70, 80/50…) ni colores literales: llaman a `viz_estado`. La única
excepción declarada es la meta TyT (70/50), que se pasa como argumento.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / 'app'
PLANTILLAS = RAIZ / 'templates'

# Comparaciones de un porcentaje contra un corte distinto del canónico.
CORTE_PROPIO = re.compile(r'\bpct\w*\s*>=\s*(50|70|75|85|90)\b')
# Un amarillo de 50 solo se admite con la meta TyT (verde=70).
AMARILLO_50 = re.compile(r'viz_estado\([^)]*amarillo=50')
META_TYT = re.compile(r'viz_estado\([^)]*verde=70, amarillo=50')
# Colores escritos a mano para un estado.
COLOR_LITERAL = re.compile(r"'#(059669|d97706|dc2626)' (if|else)")


def plantillas():
    return sorted(PLANTILLAS.rglob('*.html'))


class UmbralesUnicosTest(unittest.TestCase):
    def test_ninguna_plantilla_usa_cortes_propios(self):
        hallados = []
        for ruta in plantillas():
            for numero, linea in enumerate(ruta.read_text(encoding='utf-8').splitlines(), start=1):
                if CORTE_PROPIO.search(linea):
                    hallados.append(f'{ruta.relative_to(PLANTILLAS)}:{numero}: {linea.strip()[:90]}')
        self.assertEqual(hallados, [], 'Use viz_estado(pct) en lugar de cortes escritos a mano.')

    def test_el_amarillo_de_50_solo_acompana_la_meta_tyt(self):
        hallados = []
        for ruta in plantillas():
            texto = ruta.read_text(encoding='utf-8')
            for coincidencia in AMARILLO_50.finditer(texto):
                if not META_TYT.match(coincidencia.group(0)):
                    hallados.append(f'{ruta.relative_to(PLANTILLAS)}: {coincidencia.group(0)[:90]}')
        self.assertEqual(hallados, [])

    def test_sin_colores_de_estado_literales(self):
        hallados = [str(r.relative_to(PLANTILLAS)) for r in plantillas()
                    if COLOR_LITERAL.search(r.read_text(encoding='utf-8'))]
        self.assertEqual(hallados, [])

    def test_el_detector_reconoce_los_cortes_antiguos(self):
        # Protege la expresión regular: si deja de detectar, la prueba anterior pasaría sin revisar nada.
        self.assertTrue(CORTE_PROPIO.search("{% if pct_asistencia >= 85 %}"))
        self.assertTrue(CORTE_PROPIO.search("pct >= 50 ? 'var(--warning)'"))
        self.assertFalse(CORTE_PROPIO.search("{% if pct >= 80 %}"))
        self.assertTrue(AMARILLO_50.search('viz_estado(x, verde=80, amarillo=50)'))
        self.assertTrue(META_TYT.match('viz_estado(comp.pct, verde=70, amarillo=50'))


if __name__ == '__main__':
    unittest.main()
