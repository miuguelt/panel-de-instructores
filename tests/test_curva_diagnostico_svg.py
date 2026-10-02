"""Pruebas unitarias para el diagnóstico pedagógico y coordenadas SVG de la curva."""

import unittest

from app.services.curva_diagnostico import (
    generar_diagnostico_curva,
    obtener_ruta_recuperacion_formativa,
)
from app.services.curva_svg import construir_curva_svg_aprendiz


class CurvaDiagnosticoSvgTestCase(unittest.TestCase):
    def test_curva_svg_muchos_puntos_restringe_marcas_y_etiquetas(self):
        """Con más de 6 puntos, marcas_x debe tener entre 4 y 6 elementos para evitar saturación."""
        puntos = [
            {'fecha_str': f'{dia:02d}/03/2026', 'puntaje': 60.0 + (dia % 20)}
            for dia in range(1, 25)  # 24 puntos
        ]
        svg = construir_curva_svg_aprendiz(puntos, meta_pct=70.0)
        self.assertGreaterEqual(len(svg['marcas_x']), 4)
        self.assertLessEqual(len(svg['marcas_x']), 6)

        # Solo el pico y el último punto deben tener mostrar_etiqueta_puntaje=True
        etiquetas_visibles = [p for p in puntos if p.get('mostrar_etiqueta_puntaje')]
        self.assertLessEqual(len(etiquetas_visibles), 3)
        self.assertTrue(puntos[-1]['mostrar_etiqueta_puntaje'])

    def test_curva_svg_pocos_puntos_muestra_todas_marcas(self):
        """Con 3 puntos, todos tienen marca en el eje X y etiqueta de puntaje."""
        puntos = [
            {'fecha_str': '01/03/2026', 'puntaje': 70.0},
            {'fecha_str': '08/03/2026', 'puntaje': 75.0},
            {'fecha_str': '15/03/2026', 'puntaje': 80.0},
        ]
        svg = construir_curva_svg_aprendiz(puntos)
        self.assertEqual(len(svg['marcas_x']), 3)
        for p in puntos:
            self.assertTrue(p.get('mostrar_etiqueta_puntaje'))

    def test_curva_svg_un_solo_punto_y_vacio(self):
        """Maneja de forma segura 0 y 1 punto sin lanzar excepciones."""
        svg_vacio = construir_curva_svg_aprendiz([])
        self.assertEqual(svg_vacio['linea_puntaje'], '')

        un_punto = [{'fecha_str': '01/03/2026', 'puntaje': 80.0}]
        svg_uno = construir_curva_svg_aprendiz(un_punto)
        # La coordenada Y calculada para 80% es 55.0
        self.assertIn('55.0', svg_uno['linea_puntaje'])
        self.assertEqual(len(svg_uno['marcas_x']), 1)

    def test_diagnostico_curva_supera_meta(self):
        """Cuando supera la meta, el diagnóstico felicita la constancia."""
        diag = generar_diagnostico_curva(
            supera_meta=True,
            pt_actual=85.0,
            distancia_meta=15.0,
            dif=2.0,
            mejor_pt=88.0,
            tendencia='ascendente',
        )
        self.assertIn('Mantienes un promedio sobresaliente', diag)
        self.assertIn('85.0 pts', diag)

    def test_diagnostico_curva_descenso_fuerte_con_record_alto(self):
        """Si hubo caída brusca (dif <= -10) pero su récord es bueno, resalta capacidad de recuperación."""
        diag = generar_diagnostico_curva(
            supera_meta=False,
            pt_actual=60.0,
            distancia_meta=-10.0,
            dif=-12.0,
            mejor_pt=78.0,
            tendencia='descendente',
        )
        self.assertIn('Tu puntaje tuvo una variación de -12.0 pts', diag)
        self.assertIn('Tu récord histórico de 78.0 pts demuestra tu capacidad técnica', diag)

    def test_diagnostico_curva_bajo_meta_general(self):
        """Si no supera la meta y es regular, orienta a presentar evidencias y asistir."""
        diag = generar_diagnostico_curva(
            supera_meta=False,
            pt_actual=65.0,
            distancia_meta=-5.0,
            dif=-2.0,
            mejor_pt=68.0,
            tendencia='estable',
        )
        self.assertIn('Te encuentras a 5.0 pts de la meta aprobatoria', diag)

    def test_obtener_ruta_recuperacion_formativa(self):
        """Devuelve los 3 pasos accionables de la ruta de rescate formativo."""
        ruta = obtener_ruta_recuperacion_formativa()
        self.assertEqual(len(ruta), 3)
        self.assertIn('evidencias', ruta[0]['detalle'].lower())
        self.assertIn('asistencia', ruta[1]['paso'].lower())
        self.assertIn('desafíos', ruta[2]['paso'].lower())
