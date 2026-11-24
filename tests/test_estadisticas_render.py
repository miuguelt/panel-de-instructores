"""Estadísticas: resumen visual, competencias con menor aprobación y el resto plegado."""

import unittest
from types import SimpleNamespace

from flask import render_template

from app import create_app

RESUMEN = {
    'total_aprendices_con_juicios': 20, 'total_competencias': 8, 'total_resultados': 40,
    'aprendices_con_todos': 5, 'aprendices_sin_ninguno': 2, 'promedio_juicios_por_aprendiz': 12.5,
    'transversales_vistas': 10, 'transversales_faltantes': 4, 'ingles_aprobados': 3, 'ingles_faltantes': 1,
}


class EstadisticasRenderTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False})
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def render(self, resumen=RESUMEN, **cambios):
        contexto = dict(
            ficha=SimpleNamespace(id=1, codigo='999'), cronograma={'configurado': False},
            estados={'EN_FORMACION': 18, 'CANCELADO': 2}, total_aprendices=20, instructores_stats=[],
            top_aprendices=[], top_resultados=[], pct_global=55, competencias_stats=[], timeline=[],
            resumen=resumen, distribucion_aprobacion={'0-25': 2, '26-50': 3, '51-75': 6, '76-99': 4, '100': 5},
            mejores_competencias=[{'nombre': 'Programar software', 'pct': 90, 'aprobados': 18, 'total': 20}],
            peores_competencias=[{'nombre': 'Inglés técnico', 'pct': 30, 'aprobados': 6, 'total': 20}],
        )
        contexto.update(cambios)
        with self.app.test_request_context('/'):
            return render_template('instructor/estadisticas.html', **contexto)

    def test_resumen_visual(self):
        html = self.render()
        self.assertIn('aria-label="RAPs aprobados: 55%"', html)
        self.assertIn('aria-label="Transversales aprobadas"', html)
        self.assertIn('aria-valuenow="60"', html)
        self.assertIn('aria-label="Inglés aprobado"', html)
        self.assertIn('aria-valuenow="75"', html)
        self.assertIn('Aprendices según sus juicios aprobados: Con el 100% 5, En curso 13, Sin aprobados 2', html)
        self.assertIn('Aprendices por porcentaje de aprobación: 100% 5', html)
        # El estado de los aprendices vive en Aprendices (fichas de filtro).
        self.assertNotIn('Estado de los aprendices', html)
        self.assertNotIn('stats-overview-grid', html)

    def test_competencias_con_menor_aprobacion_y_el_resto_plegado(self):
        html = self.render(competencias_stats=[{'nombre': 'Programar software', 'tipo': 'tecnica', 'total': 20,
                                                'aprobados': 18, 'pendientes': 2, 'num_aprendices': 20, 'pct': 90,
                                                'resultados_lista': [], 'aprendices_aprobados_lista': []}])
        self.assertIn('Competencias con menor aprobación', html)
        # La tabla completa ya ordena todas: el panel de «mayor aprobación» la repetía.
        self.assertNotIn('Competencias con mayor aprobación', html)
        self.assertLess(html.index('Competencias con menor aprobación'), html.index('Ver todas las competencias'))
        self.assertIn('Inglés técnico', html)
        self.assertIn('6 de 20 juicios aprobados', html)
        self.assertIn('viz-bar--danger', html)

    def test_sin_juicios_no_inventa_porcentajes(self):
        html = self.render(resumen=None, distribucion_aprobacion={}, mejores_competencias=[],
                           peores_competencias=[], pct_global=0)
        self.assertIn('RAPs aprobados: sin datos', html)
        self.assertIn('Ir a Juicios', html)
        self.assertNotIn('Competencias con menor aprobación', html)

    def test_vocabulario_y_sin_repetir_otras_pantallas(self):
        from types import SimpleNamespace as N
        alumno = N(id=3, nombre='Ana', apellidos='Ruiz', documento='123', estado='EN_FORMACION')
        html = self.render(top_aprendices=[{'aprendiz': alumno, 'pendientes': 4}])
        self.assertIn('Rendimiento académico bajo', html)
        self.assertNotIn('Aprendices en Riesgo', html)
        self.assertNotIn('cronograma-plegado', html)
        self.assertNotIn('CC: 123', html)
        self.assertRegex(html, r'<h1[^>]*>\s*Estadísticas\s*</h1>')


if __name__ == '__main__':
    unittest.main()
