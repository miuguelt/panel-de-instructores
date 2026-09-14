"""Pruebas de renderizado para el dashboard de instructores y su nuevo módulo de tiempo en 2 columnas."""

import unittest
from datetime import date
from types import SimpleNamespace

from flask import render_template
from app import create_app


class DashboardRenderTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_dashboard_template_renders_hero_and_two_columns(self):
        with self.app.test_request_context('/instructor/dashboard'):
            ficha = SimpleNamespace(
                id=1,
                codigo='3235642',
                codigo_programa='228118',
                nombre_programa='ANALISIS Y DESARROLLO DE SOFTWARE.',
                fecha_inicio=date(2025, 7, 25),
                fecha_fin=date(2027, 10, 24),
                duracion_productiva_meses=6,
            )
            cronograma = {
                'configurado': True,
                'porcentaje': 64.9,
                'porcentaje_lectiva': 64.9,
                'porcentaje_restante': 35.1,
                'fase': 'lectiva',
                'fase_label': 'Etapa lectiva',
                'inicio_lectiva': date(2025, 7, 25),
                'fin_lectiva': date(2027, 4, 23),
                'inicio_productiva': date(2027, 4, 24),
                'fin_productiva': date(2027, 10, 24),
                'dias_transcurridos': 414,
                'dias_totales': 638,
                'dias_restantes': 407,
                'dias_restantes_lectiva': 224,
                'meses_restantes_lectiva': 7.4,
                'meses_restantes_total': 13.4,
                'meses_productiva': 6,
                'mensaje': 'La etapa productiva dura 6 meses.',
            }
            fases_data = {
                'disponible': True,
                'planeacion_sincronizada': True,
                'desfase_fases': 2,
                'fase_esperada': {'nombre': 'EJECUCIÓN', 'icono': '⚙️', 'orden': 3},
                'fase_real': {'nombre': 'ANÁLISIS', 'icono': '🔍', 'orden': 1},
                'fases': [
                    {'nombre': 'ANÁLISIS', 'porcentaje_aprobados': 38, 'resultados_aprobados': 8, 'resultados_total': 21, 'orden': 1},
                    {'nombre': 'PLANEACIÓN', 'porcentaje_aprobados': 52, 'resultados_aprobados': 14, 'resultados_total': 27, 'orden': 2},
                    {'nombre': 'EJECUCIÓN', 'porcentaje_aprobados': 55, 'resultados_aprobados': 6, 'resultados_total': 11, 'orden': 3},
                    {'nombre': 'EVALUACIÓN', 'porcentaje_aprobados': 6, 'resultados_aprobados': 1, 'resultados_total': 17, 'orden': 4},
                ],
                'resumen_raps': {'porcentaje_aprobados': 38, 'aprobados': 29, 'total': 76},
                'mensaje_veredicto': 'Fase esperada por tiempo: Ejecución · Fase según RAPs: Análisis (Retraso de 2 fases).',
            }
            extra = {
                'total_aprendices': 23,
                'sesiones': 6,
                'pct_asistencia': 93.5,
                'pct_entregas': 0,
                'tareas_totales': 8,
                'entregas_totales': 12,
                'pendientes': 3,
                'planes_pendientes': 2,
                'aprendices_certificados': 0,
                'alertas_activas': 0,
                'top_competencias': [],
            }

            html = render_template(
                'instructor/dashboard.html',
                fichas=[ficha],
                cronogramas={1: cronograma},
                fases_fichas={1: fases_data},
                estadisticas_fichas={1: {'activos': 23, 'total': 27, 'estados': {'EN_FORMACION': 23, 'CANCELADO': 4}}},
                estadisticas_extra={1: extra},
                progreso_tyt=lambda f, n: None,
            )

            # Verificar que el módulo hero de tiempo esté presente
            self.assertIn('ficha-time-hero', html)
            self.assertIn('time-hero-col-progress', html)
            self.assertIn('time-hero-col-group', html)

            # Verificar datos clave de cuánto tiempo falta
            self.assertIn('Faltan 224', html)
            self.assertIn('meses para iniciar', html)
            self.assertIn('Fin Etapa Lectiva', html)
            self.assertIn('23/04/2027', html)

            # Verificar datos de tiempo transcurrido
            self.assertIn('64.9%', html)
            self.assertIn('414', html)
            self.assertIn('638', html)
            self.assertIn('Hito 70%', html)

            # El hero compara tiempo contra el promedio de avance del grupo.
            self.assertIn('group-average-progress', html)
            self.assertIn('group-average-track', html)
            self.assertIn('Promedio de avance del grupo', html)
            self.assertIn('38%', html)
            self.assertIn('76 RAPs cerrados', html)
            self.assertIn('29', html)
            self.assertNotIn('time-countdown-track', html)
            self.assertNotIn('time-countdown-bar', html)
            self.assertNotIn('time-countdown-rem-bar', html)

            # Verificar hitos visuales complementarios en la Columna 2
            self.assertIn('is-lectiva-card', html)
            self.assertIn('is-productiva-card', html)

            # Verificar los KPIs operativos sin repetir el avance grupal
            self.assertIn('ficha-bento-kpis-2', html)
            self.assertNotIn('Avance RAPs (Grupo)', html)
            self.assertIn('Asistencia', html)
            self.assertIn('Estado del Grupo', html)

            # Verificar el bloque operativo y la semántica accesible de progreso
            self.assertIn('ficha-operational-panel', html)
            self.assertIn('Tareas publicadas', html)
            self.assertIn('Entregas recibidas', html)
            self.assertIn('Planes de mejoramiento', html)
            self.assertIn('8', html)
            self.assertIn('12 entregas registradas', html)
            self.assertIn('role="progressbar"', html)
            self.assertIn('aria-label="Tiempo lectivo transcurrido"', html)

            # Verificar que la tarjeta incluya las tres fechas clave solicitadas
            self.assertIn('Inicio etapa lectiva', html)
            self.assertIn('25/07/2025', html)
            self.assertIn('Inicio etapa productiva', html)
            self.assertIn('24/04/2027', html)
            self.assertIn('Fin de la ficha', html)
            self.assertIn('24/10/2027', html)

            # Verificar título sin punto final sobrante en la tarjeta
            self.assertIn('<h2 class="card-title">ANALISIS Y DESARROLLO DE SOFTWARE</h2>', html)

    def test_dashboard_template_renders_speedometers_and_visual_figures(self):
        """Verifica que se rendericen velocímetros, barras de progreso, iconos y diagramas de etapas."""
        with self.app.test_request_context('/instructor/dashboard'):
            ficha = SimpleNamespace(
                id=1,
                codigo='3235642',
                codigo_programa='228118',
                nombre_programa='ANALISIS Y DESARROLLO DE SOFTWARE',
                fecha_inicio=date(2025, 7, 25),
                fecha_fin=date(2027, 10, 24),
                duracion_productiva_meses=6,
            )
            cronograma = {
                'configurado': True,
                'porcentaje': 64.9,
                'porcentaje_lectiva': 64.9,
                'porcentaje_restante': 35.1,
                'fase': 'lectiva',
                'fase_label': 'Etapa lectiva',
                'inicio_lectiva': date(2025, 7, 25),
                'fin_lectiva': date(2027, 4, 23),
                'inicio_productiva': date(2027, 4, 24),
                'fin_productiva': date(2027, 10, 24),
                'dias_transcurridos': 414,
                'dias_totales': 638,
                'dias_restantes': 407,
                'dias_restantes_lectiva': 224,
                'meses_restantes_lectiva': 7.4,
                'meses_productiva': 6,
                'mensaje': 'La etapa productiva dura 6 meses.',
            }
            extra = {
                'total_aprendices': 23,
                'sesiones': 6,
                'pct_asistencia': 93.5,
                'pct_entregas': 0,
                'aprendices_certificados': 0,
                'alertas_activas': 0,
                'top_competencias': [],
                'notas_positivas': 3,
                'notas_negativas': 1,
                'notas_total': 4,
            }
            fake_tyt = {
                'total_resultados': 75,
                'meta_resultados': 53,
                'pendientes_evaluacion': 22,
                'faltan_evaluar': 516,
                'promedio_evaluados': 70.7,
                'error': False,
            }

            fases_data = {
                'disponible': True,
                'planeacion_sincronizada': True,
                'desfase_fases': 0,
                'fase_esperada': {'nombre': 'EJECUCIÓN', 'icono': '⚙️', 'orden': 3},
                'fase_real': {'nombre': 'EJECUCIÓN', 'icono': '⚙️', 'orden': 3},
                'fases': [
                    {'nombre': 'ANÁLISIS', 'porcentaje_aprobados': 100, 'resultados_aprobados': 21, 'resultados_total': 21, 'orden': 1},
                    {'nombre': 'PLANEACIÓN', 'porcentaje_aprobados': 100, 'resultados_aprobados': 27, 'resultados_total': 27, 'orden': 2},
                    {'nombre': 'EJECUCIÓN', 'porcentaje_aprobados': 55, 'resultados_aprobados': 6, 'resultados_total': 11, 'orden': 3},
                    {'nombre': 'EVALUACIÓN', 'porcentaje_aprobados': 0, 'resultados_aprobados': 0, 'resultados_total': 17, 'orden': 4},
                ],
                'resumen_raps': {'porcentaje_aprobados': 71, 'aprobados': 54, 'total': 76},
                'mensaje_veredicto': 'Al día con el cronograma.',
            }

            html = render_template(
                'instructor/dashboard.html',
                fichas=[ficha],
                cronogramas={1: cronograma},
                fases_fichas={1: fases_data},
                estadisticas_fichas={1: {'activos': 23, 'total': 27, 'estados': {'EN_FORMACION': 23}}},
                estadisticas_extra={1: extra},
                progreso_tyt=lambda f, n: fake_tyt,
            )

            # 1. El Hero separa el tiempo del promedio de avance del grupo
            self.assertIn('group-average-track', html)
            self.assertIn('Promedio de avance del grupo', html)
            self.assertNotIn('time-countdown-track', html)
            self.assertNotIn('ritmo lectivo', html)

            # 2. Tarjetas secundarias estructuradas con iconos e imágenes representativas
            self.assertIn('detail-kpi-card', html)
            self.assertIn('is-tyt-card', html)
            self.assertIn('is-productiva-card', html)
            self.assertIn('is-cert-card', html)
            self.assertIn('is-integral-card', html)

            # 3. Velocímetro en Meta Saber TyT
            self.assertIn('kpi-speedometer-svg', html)
            self.assertIn('53 de 75 resultados (70%)', html)
            self.assertIn('22', html)
            self.assertIn('516', html)

            # 4. Pipeline visual en Etapa Productiva
            self.assertIn('stage-pipeline', html)
            self.assertIn('Lectiva', html)
            self.assertIn('Productiva (6M)', html)
            self.assertIn('Certificación', html)
            self.assertIn('24/04/2027', html)
            self.assertIn('24/10/2027', html)

            # 5. Anillo / Indicador radial en Certificación
            self.assertIn('kpi-ring-svg', html)
            self.assertIn('0 de 23 aprendices', html)

            # 6. Barra de balance en Formación Integral
            self.assertIn('behavior-balance-bar', html)
            self.assertIn('4 observaciones', html)
            self.assertIn('3', html)
            self.assertIn('reconocimientos', html)
            self.assertIn('1', html)
            self.assertIn('llamados de atención', html)


if __name__ == '__main__':
    unittest.main()
