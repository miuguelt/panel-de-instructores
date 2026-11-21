"""Biblioteca de visualización: cálculos puros (Tier 1) y macros accesibles."""

import re
import unittest

from flask import render_template_string

from app import create_app
from app.services import visualizacion as viz


class EstadoPorUmbralTest(unittest.TestCase):
    def test_niveles_en_los_limites(self):
        self.assertEqual(viz.estado_por_umbral(80), 'success')
        self.assertEqual(viz.estado_por_umbral(79.9), 'warning')
        self.assertEqual(viz.estado_por_umbral(60), 'warning')
        self.assertEqual(viz.estado_por_umbral(59.9), 'danger')
        self.assertEqual(viz.estado_por_umbral(0), 'danger')

    def test_umbrales_propios(self):
        self.assertEqual(viz.estado_por_umbral(70, verde=70, amarillo=50), 'success')
        self.assertEqual(viz.estado_por_umbral(49, verde=70, amarillo=50), 'danger')

    def test_sin_dato_no_inventa_estado(self):
        self.assertEqual(viz.estado_por_umbral(None), 'neutral')
        self.assertEqual(viz.estado_por_umbral('x'), 'neutral')

    def test_invertido_para_metricas_donde_menos_es_mejor(self):
        self.assertEqual(viz.estado_por_umbral(5, verde=10, amarillo=20, invertido=True), 'success')
        self.assertEqual(viz.estado_por_umbral(15, verde=10, amarillo=20, invertido=True), 'warning')
        self.assertEqual(viz.estado_por_umbral(25, verde=10, amarillo=20, invertido=True), 'danger')


class PorcentajeTest(unittest.TestCase):
    def test_acota_entre_cero_y_cien(self):
        self.assertEqual(viz.acotar_pct(-5), 0)
        self.assertEqual(viz.acotar_pct(140), 100)
        self.assertEqual(viz.acotar_pct(42.46), 42.5)
        self.assertIsInstance(viz.acotar_pct(55.0), int)

    def test_sin_dato(self):
        self.assertIsNone(viz.acotar_pct(None))
        self.assertIsNone(viz.acotar_pct('abc'))

    def test_porcentaje_de_conteos(self):
        self.assertEqual(viz.porcentaje(1, 3), 33.3)
        self.assertIsNone(viz.porcentaje(1, 0))
        self.assertIsNone(viz.porcentaje(None, 4))


class SegmentosTest(unittest.TestCase):
    def test_suma_exactamente_cien(self):
        segs = viz.segmentos([('Rojo', 1, 'danger'), ('Amarillo', 1, 'warning'), ('Verde', 1, 'success')])
        self.assertEqual(sum(s['pct'] for s in segs), 100)
        self.assertEqual([s['valor'] for s in segs], [1, 1, 1])
        self.assertEqual(segs[0]['estado'], 'danger')

    def test_omite_ceros_y_negativos_pero_conserva_total(self):
        segs = viz.segmentos([('A', 0, 'danger'), ('B', 3, 'success'), ('C', -2, 'warning')])
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]['pct'], 100)
        self.assertEqual(segs[0]['etiqueta'], 'B')

    def test_vacio(self):
        self.assertEqual(viz.segmentos([]), [])
        self.assertEqual(viz.segmentos([('A', 0, 'danger')]), [])
        self.assertEqual(viz.segmentos(None), [])

    def test_estado_por_defecto(self):
        segs = viz.segmentos([('A', 2), ('B', 2)])
        self.assertEqual({s['estado'] for s in segs}, {'neutral'})


class SparklineTest(unittest.TestCase):
    def test_puntos_dentro_del_lienzo(self):
        pts = viz.puntos_sparkline([0, 50, 100], ancho=100, alto=20)
        self.assertEqual(pts['puntos'], '0.0,20.0 50.0,10.0 100.0,0.0')
        self.assertEqual(pts['ultimo'], {'x': 100.0, 'y': 0.0, 'valor': 100})

    def test_serie_plana_queda_centrada(self):
        pts = viz.puntos_sparkline([70, 70], ancho=10, alto=20)
        self.assertEqual(pts['puntos'], '0.0,10.0 10.0,10.0')

    def test_escala_fija_cero_a_cien(self):
        pts = viz.puntos_sparkline([50, 50], ancho=10, alto=20, minimo=0, maximo=100)
        self.assertEqual(pts['puntos'], '0.0,10.0 10.0,10.0')

    def test_menos_de_dos_puntos_no_dibuja(self):
        self.assertIsNone(viz.puntos_sparkline([5]))
        self.assertIsNone(viz.puntos_sparkline([]))
        self.assertIsNone(viz.puntos_sparkline(None))
        self.assertIsNone(viz.puntos_sparkline([None, 'x']))

    def test_descarta_valores_no_numericos(self):
        pts = viz.puntos_sparkline([10, None, 20], ancho=10, alto=10)
        self.assertEqual(pts['n'], 2)


class DonaTest(unittest.TestCase):
    def test_arco(self):
        arco = viz.arco_dona(25)
        self.assertAlmostEqual(arco['longitud'], 2 * 3.14159 * 40 * 0.25, places=1)
        self.assertAlmostEqual(arco['circunferencia'], 2 * 3.14159 * 40, places=1)

    def test_arco_acotado_y_sin_dato(self):
        self.assertEqual(viz.arco_dona(150)['longitud'], viz.arco_dona(100)['longitud'])
        self.assertEqual(viz.arco_dona(None)['longitud'], 0)


class CuentaRegresivaTest(unittest.TestCase):
    def test_elige_el_hito_mas_urgente(self):
        crono = {'configurado': True, 'fase': 'por_iniciar', 'dias_para_iniciar_lectiva': 5, 'dias_cierre_ficha': 400}
        self.assertEqual(viz.hito_urgente(crono), {'tipo': 'inicio', 'dias': 5, 'estado': 'warning',
                                                   'texto': 'Inicia en 5 días'})

    def test_cierre_proximo(self):
        crono = {'configurado': True, 'fase': 'productiva', 'dias_para_iniciar_lectiva': None, 'dias_cierre_ficha': 10}
        self.assertEqual(viz.hito_urgente(crono)['estado'], 'danger')
        self.assertEqual(viz.hito_urgente(crono)['texto'], 'Cierra en 10 días')

    def test_textos_de_hoy_y_un_dia(self):
        self.assertEqual(viz.hito_urgente({'configurado': True, 'fase': 'por_iniciar',
                                           'dias_para_iniciar_lectiva': 0})['texto'], 'Inicia hoy')
        self.assertEqual(viz.hito_urgente({'configurado': True, 'fase': 'lectiva',
                                           'dias_cierre_ficha': 1})['texto'], 'Cierra en 1 día')
        self.assertEqual(viz.hito_urgente({'configurado': True, 'fase': 'lectiva',
                                           'dias_cierre_ficha': 0})['texto'], 'Cierra hoy')

    def test_cierre_lejano_es_informativo(self):
        crono = {'configurado': True, 'fase': 'lectiva', 'dias_cierre_ficha': 200}
        self.assertEqual(viz.hito_urgente(crono)['estado'], 'neutral')
        crono['dias_cierre_ficha'] = 30
        self.assertEqual(viz.hito_urgente(crono)['estado'], 'warning')

    def test_inicio_lejano(self):
        crono = {'configurado': True, 'fase': 'por_iniciar', 'dias_para_iniciar_lectiva': 60}
        self.assertEqual(viz.hito_urgente(crono)['estado'], 'neutral')

    def test_sin_fechas_o_finalizada(self):
        self.assertIsNone(viz.hito_urgente({'configurado': False}))
        self.assertIsNone(viz.hito_urgente({'configurado': True, 'fase': 'finalizada', 'dias_cierre_ficha': 3}))
        self.assertIsNone(viz.hito_urgente({'configurado': True, 'fase': 'lectiva', 'ficha_cerrada': True,
                                            'dias_cierre_ficha': 3}))
        self.assertIsNone(viz.hito_urgente(None))
        self.assertIsNone(viz.hito_urgente({'configurado': True, 'fase': 'lectiva'}))


class BrechaTest(unittest.TestCase):
    def test_textos(self):
        self.assertEqual(viz.brecha_texto(40, 52.3), {'delta': -12.3, 'estado': 'danger',
                                                      'texto': 'RAPs 12.3 pts por debajo del tiempo'})
        self.assertEqual(viz.brecha_texto(44, 50)['estado'], 'warning')
        self.assertEqual(viz.brecha_texto(49, 50)['estado'], 'success')
        self.assertEqual(viz.brecha_texto(60, 50)['texto'], 'RAPs 10.0 pts por delante del tiempo')
        self.assertEqual(viz.brecha_texto(60, 50)['estado'], 'success')
        self.assertEqual(viz.brecha_texto(50, 50)['texto'], 'RAPs al ritmo del tiempo')

    def test_sin_datos(self):
        self.assertIsNone(viz.brecha_texto(None, 50))
        self.assertIsNone(viz.brecha_texto(30, None))


class EstadosAprendizTest(unittest.TestCase):
    def test_etiquetas_legibles_en_orden_y_sin_ceros(self):
        items = viz.items_estados_aprendiz({'CANCELADO': 2, 'EN_FORMACION': 20, 'CERTIFICADO': 0, 'TRASLADO': 1})
        self.assertEqual(items, [('En formación', 20, 'info'), ('Cancelados', 2, 'danger'), ('Traslado', 1, 'neutral')])

    def test_vacio(self):
        self.assertEqual(viz.items_estados_aprendiz(None), [])


class MacrosTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                              'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False})

    def render(self, cuerpo, **ctx):
        with self.app.test_request_context():
            return render_template_string(
                '{% from "components/_viz.html" import kpi, barra, dona, apilada, semaforo, sparkline, vacio %}'
                + cuerpo, **ctx)

    def test_barra_valida_con_meta(self):
        html = self.render('{{ barra(42.5, "RAPs aprobados", meta=70) }}')
        self.assertIn('role="progressbar"', html)
        self.assertIn('aria-valuenow="42.5"', html)
        self.assertIn('--viz-value: 42.5%', html)
        self.assertIn('--viz-meta: 70%', html)
        self.assertIn('Meta 70%', html)
        self.assertIn('42.5%', html)
        self.assertIn('viz-bar--danger', html)

    def test_barra_comparada(self):
        html = self.render('{{ barra(40, "RAPs", comparar=55, comparar_label="Tiempo") }}')
        self.assertIn('--viz-compare: 55%', html)
        self.assertIn('Tiempo 55%', html)

    def test_barra_excedida_y_vacia(self):
        self.assertIn('--viz-value: 100%', self.render('{{ barra(180, "X") }}'))
        vacia = self.render('{{ barra(None, "Asistencia") }}')
        self.assertIn('Sin datos', vacia)
        self.assertNotIn('aria-valuenow', vacia)
        self.assertIn('viz-bar--neutral', vacia)

    def test_dona(self):
        html = self.render('{{ dona(75, "Asistencia") }}')
        self.assertIn('role="img"', html)
        self.assertIn('aria-label="Asistencia: 75%"', html)
        self.assertIn('stroke-dasharray', html)
        self.assertIn('viz-donut--warning', html)
        self.assertIn('Sin datos', self.render('{{ dona(None, "Asistencia") }}'))

    def test_dona_con_estado_explicito(self):
        self.assertIn('viz-donut--info', self.render('{{ dona(10, "Avance", estado="info") }}'))

    def test_apilada_con_leyenda(self):
        html = self.render('{{ apilada([("Rojo", 2, "danger"), ("Verde", 6, "success")], "Semáforo") }}')
        self.assertIn('aria-label="Semáforo: Rojo 2, Verde 6"', html)
        self.assertIn('--viz-value: 25%', html)
        self.assertIn('--viz-value: 75%', html)
        self.assertEqual(html.count('class="viz-legend-item'), 2)

    def test_apilada_vacia(self):
        html = self.render('{{ apilada([("Rojo", 0, "danger")], "Semáforo") }}')
        self.assertIn('Sin datos', html)

    def test_kpi_con_enlace_y_sin_enlace(self):
        html = self.render('{{ kpi("Por calificar", 7, estado="warning", detalle="entregas", url="/x") }}')
        self.assertIn('href="/x"', html)
        self.assertIn('viz-kpi--warning', html)
        self.assertIn('>7<', html)
        sin = self.render('{{ kpi("Aprendices", None) }}')
        self.assertNotIn('href', sin)
        self.assertIn('—', sin)

    def test_kpi_unidad(self):
        self.assertIn('85<small>%</small>', self.render('{{ kpi("Asistencia", 85, unidad="%") }}'))

    def test_semaforo_no_depende_solo_del_color(self):
        html = self.render('{{ semaforo("danger", "Riesgo alto") }}')
        self.assertIn('Riesgo alto', html)
        self.assertIn('data-lucide="alert-octagon"', html)
        self.assertIn('data-lucide="check-circle-2"', self.render('{{ semaforo("success", "Bien") }}'))
        self.assertIn('data-lucide="alert-triangle"', self.render('{{ semaforo("warning", "Ojo") }}'))
        self.assertIn('data-lucide="info"', self.render('{{ semaforo("neutral", "Sin datos") }}'))

    def test_sparkline(self):
        html = self.render('{{ sparkline([60, 80, 90], "Asistencia por sesión") }}')
        self.assertIn('<polyline', html)
        self.assertIn('aria-label="Asistencia por sesión: de 60 a 90"', html)
        self.assertIn('Sin datos', self.render('{{ sparkline([5], "Asistencia") }}'))

    def test_vacio_accionable(self):
        html = self.render('{{ vacio("Sin juicios", "Carga el reporte", url="/cargar", accion="Cargar") }}')
        self.assertIn('href="/cargar"', html)
        self.assertIn('Cargar', html)
        self.assertNotIn('href', self.render('{{ vacio("Nada") }}'))

    def test_sin_colores_literales(self):
        html = self.render('{{ barra(10, "x", meta=70) }}{{ dona(10, "x") }}{{ apilada([("a", 1, "danger")], "x") }}')
        self.assertIsNone(re.search(r'#[0-9a-fA-F]{3,6}\b', html))


if __name__ == '__main__':
    unittest.main()
