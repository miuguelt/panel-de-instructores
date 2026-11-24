"""Un solo vocabulario de reconocimiento en lo que leen instructores y aprendices.

- «insignia»: reconocimiento individual.
- «reconocimiento de grupo»: lo que antes se llamaba medalla o condecoración.
- «grupo»: nunca «escuadrón» ni «liga de escuadrones» («equipo» queda para los
  equipos de instructores en Programación).

Se revisa el texto visible: las plantillas sin etiquetas ni expresiones de Jinja
y los mensajes que los servicios muestran. Los identificadores internos
(`medallas_count`, `mi_escuadron`) no se cambian para no romper datos guardados.
"""

import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / 'app'
RETIRADOS = re.compile(r'\b(medallas?|condecoraci[oó]n(es)?|escuadr[oó]n(es)?)\b|liga de escuadrones', re.I)
CODIGO = re.compile(r'\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}|<script[\s\S]*?</script>|<!--[\s\S]*?-->', re.S)
ETIQUETA = re.compile(r'<[^>]+>')
ATRIBUTO_VISIBLE = re.compile(r'(?:title|aria-label|placeholder|alt)="([^"]*)"')
CADENA = re.compile(r"""f?(['"])((?:(?!\1).)*)\1""")


def texto_visible(html):
    atributos = ' '.join(ATRIBUTO_VISIBLE.findall(html))
    return ETIQUETA.sub(' ', CODIGO.sub(' ', html)) + ' ' + atributos


class VocabularioReconocimientoTest(unittest.TestCase):
    def test_las_plantillas_no_usan_el_vocabulario_retirado(self):
        hallados = []
        for ruta in sorted((APP / 'templates').rglob('*.html')):
            for palabra in RETIRADOS.finditer(texto_visible(ruta.read_text(encoding='utf-8'))):
                hallados.append(f'{ruta.relative_to(APP)}: {palabra.group(0)}')
        self.assertEqual(hallados, [])

    def test_los_mensajes_de_los_servicios_tampoco(self):
        hallados = []
        for ruta in [APP / 'routes' / 'grupos.py', APP / 'services' / 'ranking.py',
                     APP / 'services' / 'curva_diagnostico.py']:
            for _, cadena in CADENA.findall(ruta.read_text(encoding='utf-8')):
                if ' ' in cadena and RETIRADOS.search(cadena):
                    hallados.append(f'{ruta.name}: {cadena[:60]}')
        self.assertEqual(hallados, [])

    def test_el_detector_ignora_identificadores_y_ve_el_texto(self):
        self.assertEqual(RETIRADOS.findall(texto_visible('<b>{{ g.medallas_count }}</b>')), [])
        self.assertTrue(RETIRADOS.search(texto_visible('<span>Medallas</span>')))
        self.assertTrue(RETIRADOS.search(texto_visible('<button title="Otorgar medalla">')))


class InsigniasAccionesPrimeroTest(unittest.TestCase):
    def test_crear_y_otorgar_van_antes_del_catalogo(self):
        html = (APP / 'templates' / 'instructor' / 'insignias.html').read_text(encoding='utf-8')
        self.assertLess(html.index('two-column-layout'), html.index('badge-catalog'))


if __name__ == '__main__':
    unittest.main()
