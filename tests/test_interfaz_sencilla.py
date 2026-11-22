"""Interfaz sencilla: íconos del sistema, botones en mayúscula inicial y siglas explicadas.

Los emojis se ven distinto en cada sistema y los lectores de pantalla los leen
en voz alta; en las vistas principales se usan íconos Lucide decorativos. Las
siglas propias del SENA (RAP, TyT, CC/TI) llevan `<abbr title>` para que quien
no las conozca pueda leer su significado.
"""

import re
import unittest
from pathlib import Path

PLANTILLAS = Path(__file__).resolve().parents[1] / 'app' / 'templates'
SIN_EMOJIS = (
    'instructor/alertas.html',
    'instructor/asistencia.html',
    'instructor/tareas.html',
    'instructor/_tarea_card.html',
    'instructor/juicios.html',
    'instructor/planeacion.html',
    'instructor/_planeacion_cabecera.html',
    'aprendiz/panel/_progreso.html',
    'aprendiz/panel/_pestanas.html',
)
EMOJI = re.compile('[\U0001F000-\U0001FAFF⌀-⏿☀-➿⬀-⯿️]')
BOTON = re.compile(r'<(button|a)\b[^>]*class="[^"]*\bbtn\b[^"]*"[^>]*>(.*?)</\1>', re.S)
# Siglas y nombres propios que conservan mayúscula dentro de un botón.
PERMITIDAS = {'SENA', 'SOFIA', 'Plus', 'PDF', 'CSV', 'Excel', 'TyT', 'RAP', 'RAPs', 'Asiste', 'WhatsApp'}


def leer(relativa):
    return (PLANTILLAS / relativa).read_text(encoding='utf-8')


class IconosSinEmojiTest(unittest.TestCase):
    def test_las_vistas_principales_no_usan_emojis_como_iconos(self):
        for relativa in SIN_EMOJIS:
            with self.subTest(plantilla=relativa):
                hallados = sorted({m.group(0) for m in EMOJI.finditer(leer(relativa))})
                self.assertEqual(hallados, [], 'Use <i data-lucide="..." aria-hidden="true">.')

    def test_los_iconos_lucide_son_decorativos(self):
        for relativa in SIN_EMOJIS:
            html = leer(relativa)
            for icono in re.findall(r'<i data-lucide="[^"]+"[^>]*>', html):
                with self.subTest(plantilla=relativa, icono=icono):
                    contenedor = html[max(0, html.index(icono) - 120):html.index(icono)]
                    self.assertTrue('aria-hidden="true"' in icono or 'aria-hidden="true"' in contenedor.rsplit('<', 1)[-1])

    def test_el_js_del_panel_del_aprendiz_no_escribe_emojis(self):
        js = (PLANTILLAS.parent / 'static' / 'js' / 'aprendiz_panel.js').read_text(encoding='utf-8')
        self.assertNotIn('📑', js)
        self.assertNotIn('📜', js)


class BotonesMayusculaInicialTest(unittest.TestCase):
    def test_botones_con_mayuscula_solo_en_la_primera_palabra(self):
        incorrectos = []
        for relativa in SIN_EMOJIS + ('instructor/vision_general.html', 'instructor/turnos_aseo.html'):
            for _, contenido in BOTON.findall(leer(relativa)):
                for rama in re.split(r'\{[{%].*?[%}]\}|\$\{.*?\}', re.sub(r'<[^>]+>|&\w+;', ' ', contenido)):
                    palabras = re.findall(r'[A-Za-zÁÉÍÓÚÑáéíóúñ][\wÁÉÍÓÚÑáéíóúñ-]*', rama)
                    if any(p[0].isupper() and p not in PERMITIDAS for p in palabras[1:]):
                        incorrectos.append(f'{relativa}: {" ".join(rama.split())[:60]}')
        self.assertEqual(incorrectos, [])

    def test_los_botones_senalados_quedan_en_mayuscula_inicial(self):
        self.assertIn('Nueva tarea', leer('instructor/tareas.html'))
        self.assertIn('Cargar juicios', leer('instructor/juicios.html'))
        self.assertIn('Tomar asistencia hoy', leer('instructor/alertas.html'))
        for viejo, archivo in (('Nueva Tarea', 'instructor/tareas.html'),
                               ('Cargar Juicios', 'instructor/juicios.html'),
                               ('Tomar Asistencia Hoy', 'instructor/alertas.html')):
            self.assertNotIn(viejo, leer(archivo))


class SiglasExplicadasTest(unittest.TestCase):
    def test_siglas_con_abbr(self):
        alertas = leer('instructor/alertas.html')
        self.assertRegex(alertas, r'<abbr title="[^"]+">CC/TI</abbr>')
        self.assertRegex(alertas, r'<abbr title="[^"]*Saber TyT[^"]*">TyT</abbr>')
        self.assertRegex(leer('instructor/juicios.html'), r'<abbr title="Resultados de aprendizaje">RAP</abbr>')

    def test_corte_de_trabajo_tiene_un_texto_visible_claro(self):
        for relativa in ('instructor/asistencia.html', 'instructor/tareas.html', 'instructor/ranking.html'):
            with self.subTest(plantilla=relativa):
                html = leer(relativa)
                self.assertNotIn('Corte de trabajo', html)
                self.assertIn('Periodo de evaluación', html)


class VocabularioDeRiesgoTest(unittest.TestCase):
    def test_alertas_y_vision_general_usan_las_mismas_tres_etiquetas(self):
        segmentos = re.compile(r"apilada\(\[\('([^']+)'[^)]*\), \('([^']+)'[^)]*\), \('([^']+)'")
        alertas = segmentos.search(leer('instructor/alertas.html'))
        vision = segmentos.search(leer('instructor/vision_general.html'))
        self.assertIsNotNone(alertas)
        self.assertEqual(alertas.groups(), ('Riesgo alto', 'En seguimiento', 'Al día'))
        self.assertEqual(alertas.groups(), vision.groups())

    def test_las_insignias_de_alertas_no_usan_el_vocabulario_anterior(self):
        html = leer('instructor/alertas.html')
        self.assertIn("{% if d.nivel == 'rojo' %}Riesgo alto{% elif d.nivel == 'amarillo' %}En seguimiento{% else %}Al día{% endif %}", html)
        for viejo in ("'En alerta'", "'En riesgo'", '</span> Riesgo</span>', '</span> Alerta</span>'):
            self.assertNotIn(viejo, html)


if __name__ == '__main__':
    unittest.main()
