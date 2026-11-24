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
    'instructor/notificaciones.html',
    'tyt/detalle.html',
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
        for viejo, archivo in (('Nueva Tarea', 'instructor/tareas.html'),
                               ('Cargar Juicios', 'instructor/juicios.html'),
                               ('Casos De Seguimiento', 'instructor/alertas.html')):
            self.assertNotIn(viejo, leer(archivo))


class SiglasExplicadasTest(unittest.TestCase):
    def test_siglas_con_abbr(self):
        alertas = leer('instructor/alertas.html')
        self.assertRegex(alertas, r'<abbr title="[^"]+">CC/TI</abbr>')
        self.assertRegex(leer('tyt/_tarjeta.html'),
                         r'<abbr title="[^"]*Saber TyT[^"]*">TyT</abbr>')
        self.assertRegex(leer('instructor/juicios.html'), r'<abbr title="Resultados de aprendizaje">RAP</abbr>')
        panorama = leer('instructor/_planeacion_panorama.html')
        self.assertRegex(panorama, r'<abbr title="[^"]+">EVM</abbr>')
        self.assertRegex(panorama, r'<abbr title="[^"]+">CFD</abbr>')

    def test_corte_de_trabajo_tiene_un_texto_visible_claro(self):
        for relativa in ('instructor/asistencia.html', 'instructor/tareas.html', 'instructor/ranking.html'):
            with self.subTest(plantilla=relativa):
                html = leer(relativa)
                self.assertNotIn('Corte de trabajo', html)
                self.assertIn('Periodo de evaluación', html)


class VocabularioDeRiesgoTest(unittest.TestCase):
    def test_alertas_y_vision_general_usan_las_mismas_tres_etiquetas(self):
        # Visión general muestra el semáforo agregado; Alertas, los filtros de la lista.
        segmentos = re.compile(r"apilada\(\[\('([^']+)'[^)]*\), \('([^']+)'[^)]*\), \('([^']+)'")
        vision = segmentos.search(leer('instructor/vision_general.html'))
        filtros = re.compile(r"\('rojo', '([^']+)', 'danger'\), \('amarillo', '([^']+)', 'warning'\), \('verde', '([^']+)'")
        alertas = filtros.search(leer('instructor/alertas.html'))
        self.assertIsNotNone(alertas)
        self.assertEqual(alertas.groups(), ('Riesgo alto', 'En seguimiento', 'Al día'))
        self.assertEqual(alertas.groups(), vision.groups())
        self.assertNotIn('apilada(', leer('instructor/alertas.html'))

    def test_las_insignias_de_alertas_no_usan_el_vocabulario_anterior(self):
        html = leer('instructor/alertas.html')
        self.assertIn("{% if d.nivel == 'rojo' %}Riesgo alto{% elif d.nivel == 'amarillo' %}En seguimiento{% else %}Al día{% endif %}", html)
        for viejo in ("'En alerta'", "'En riesgo'", '</span> Riesgo</span>', '</span> Alerta</span>'):
            self.assertNotIn(viejo, html)


class EntregasSinRepetirTest(unittest.TestCase):
    def test_entregas_muestra_por_calificar_y_cada_cifra_una_vez(self):
        html = leer('instructor/entregas.html')
        # «Por calificar» es la acción de esta pantalla: antes se calculaba y no se mostraba.
        self.assertRegex(html, r"kpi\('Por calificar', stats\.sin_calificar")
        # «Participación» y «Puntualidad» repetían las tarjetas de entregas y a tiempo.
        self.assertNotIn('Resumen de Progreso', html)
        self.assertNotIn('Participación (Aprendices con evidencia subida)', html)
        self.assertEqual(html.count('stats.a_tiempo }}'), 0)


class PlaneacionOrdenadaTest(unittest.TestCase):
    def test_cabecera_sin_modulos_de_la_barra_y_una_sola_accion_principal(self):
        cabecera = leer('instructor/_planeacion_cabecera.html')
        self.assertNotIn("url_for('instructor.juicios'", cabecera)
        self.assertNotIn("url_for('instructor.estadisticas'", cabecera)
        self.assertEqual(cabecera.count('btn btn-primary'), 1, 'Solo «Cargar archivos» cuando aún no hay análisis.')

    def test_el_diagnostico_de_datos_va_antes_del_estado(self):
        pagina = leer('instructor/planeacion.html')
        self.assertLess(pagina.index('_planeacion_diagnostico.html'), pagina.index('_planeacion_estado.html'))
        self.assertNotIn('seccion-diagnostico', leer('instructor/_planeacion_detalle.html'))

    def test_el_ritmo_se_mide_una_vez_y_la_curva_s_arranca_plegada(self):
        panorama = leer('instructor/_planeacion_panorama.html')
        self.assertNotIn('Ritmo de evaluación', panorama)
        self.assertIn('id="seccion-curva-s" data-collapse-default="cerrado"', panorama)
        self.assertNotIn('Planeación v{{', leer('instructor/_planeacion_carga_unificada.html'))


class AseoEnUnSoloLugarTest(unittest.TestCase):
    def test_el_panel_enlaza_a_la_gestion_en_vez_de_repetir_el_formulario(self):
        aseo = leer('aprendiz/panel/_aseo.html')
        self.assertNotIn('generar_como_aprendiz', aseo)
        self.assertIn("url_for('aseo_aprendiz.gestionar'", aseo)


class TareasSencillasTest(unittest.TestCase):
    def test_eliminar_no_compite_con_la_accion_principal_de_la_tarjeta(self):
        tarjeta = leer('instructor/_tarea_card.html')
        pie = tarjeta[tarjeta.index('class="task-card-footer"'):tarjeta.index('</div>', tarjeta.index('class="task-card-footer"'))]
        self.assertNotIn('eliminar_tarea', pie)
        self.assertNotIn('btn-danger', pie)
        # Eliminar vive al final del panel de edición, separado de «Guardar cambios».
        edicion = tarjeta[tarjeta.index('data-form-tarea'):]
        self.assertLess(edicion.index('Guardar cambios'), edicion.index('Eliminar tarea'))

    def test_la_tarjeta_no_repite_el_plazo_en_insignias(self):
        tarjeta = leer('instructor/_tarea_card.html')
        cabecera = tarjeta[tarjeta.index('task-badges-cluster'):tarjeta.index('tarea-progreso-tiempo-box')]
        for repetido in ('Vencida', 'Urgente', 'En plazo', 'Sin fecha límite'):
            self.assertNotIn(repetido, cabecera)

    def test_crear_tarea_arranca_plegado_y_muestra_lo_esencial(self):
        html = leer('instructor/tareas.html')
        self.assertRegex(html, r'id="contenedor-formulario-tarea"[^>]*\bhidden\b')
        formulario = html[html.index('id="contenedor-formulario-tarea"'):html.index('Crear tarea</button>')]
        avanzadas = formulario[formulario.index('tarea-opciones-avanzadas'):]
        for esencial in ('name="titulo"', 'name="fecha_limite"', 'name="modalidad"'):
            self.assertNotIn(esencial, avanzadas)
        for opcional in ('name="enlace_externo"', 'name="material_apoyo"', 'name="tipo_asignacion"'):
            self.assertIn(opcional, avanzadas)


if __name__ == '__main__':
    unittest.main()
