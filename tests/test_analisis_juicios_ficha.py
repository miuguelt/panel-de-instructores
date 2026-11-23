"""Estadísticas de juicios de una ficha (servicio puro)."""

import unittest
from datetime import datetime
from types import SimpleNamespace

from app.services.analisis_juicios_ficha import analizar_juicios_ficha, distribucion_aprobacion

AHORA = datetime(2026, 5, 10)


def aprendiz(id_, nombre, en_formacion=True, estado='EN_FORMACION'):
    return SimpleNamespace(id=id_, nombre=nombre, apellidos='Ruiz', documento=str(id_), en_formacion=en_formacion, estado=estado)


def juicio(aprendiz_id, competencia, valor, rap='R1', tipo=None, fecha=None, evaluador='Ana'):
    return SimpleNamespace(aprendiz_id=aprendiz_id, competencia=competencia, juicio=valor, resultado_aprendizaje=rap,
                           tipo_competencia=tipo, fecha_juicio=fecha, funcionario_registro=evaluador)


class DistribucionTest(unittest.TestCase):
    def test_rangos(self):
        self.assertEqual(distribucion_aprobacion([100, 99, 76, 75, 51, 50, 26, 25, 0]),
                         {'0-25': 2, '26-50': 2, '51-75': 2, '76-99': 2, '100': 1})
        self.assertEqual(distribucion_aprobacion([]), {'0-25': 0, '26-50': 0, '51-75': 0, '76-99': 0, '100': 0})


class AnalizarTest(unittest.TestCase):
    def setUp(self):
        self.aprendices = [aprendiz(1, 'Ana'), aprendiz(2, 'Luis'), aprendiz(3, 'Eva', False, 'CANCELADO'), aprendiz(4, 'Sin juicios')]
        self.juicios = [
            juicio(1, 'Programar', 'APROBADO', 'R1', 'tecnica', datetime(2026, 3, 1)),
            juicio(1, 'Interactuar en lengua inglesa', 'APROBADO', 'R2', None, datetime(2026, 4, 1), None),
            juicio(2, 'Programar', 'NO APROBADO', 'R1', 'tecnica', datetime(2026, 4, 2), 'Luz'),
            juicio(2, 'Ética', 'POR EVALUAR', 'R3', 'transversal', None, 'Luz'),
            juicio(2, 'Programar', 'AÚN NO APROBADO', 'R4', 'tecnica', None, 'Luz'),
            juicio(3, 'Programar', 'APROBADO', 'R9', 'tecnica'),  # aprendiz retirado: no cuenta
        ]
        self.r = analizar_juicios_ficha(self.juicios, self.aprendices)

    def test_estados_incluyen_a_todos_los_aprendices(self):
        self.assertEqual(self.r['estados'], {'EN_FORMACION': 3, 'CANCELADO': 1})
        self.assertEqual(self.r['total_aprendices'], 4)

    def test_aprobacion_global_solo_en_formacion(self):
        self.assertEqual(self.r['pct_global'], 40)

    def test_por_instructor(self):
        ana, luz, sin = (self.r['instructores_stats'][k] for k in ('Ana', 'Luz', 'Sin Registro'))
        self.assertEqual((ana['total'], ana['aprobados'], ana['tecnica'], ana['total_aprendices'], ana['total_aprendices_aprobados']), (1, 1, 1, 1, 1))
        self.assertEqual((luz['total'], luz['no_aprobados'], luz['transversal'], luz['total_aprendices_aprobados']), (3, 3, 1, 0))
        self.assertEqual(sin['ingles'], 1, 'sin tipo registrado se clasifica por el nombre')

    def test_riesgo_y_resultados_criticos(self):
        self.assertEqual([(t['aprendiz'].nombre, t['pendientes']) for t in self.r['top_aprendices']], [('Luis', 3)])
        self.assertEqual(self.r['top_resultados'], [('R1', 1), ('R3', 1), ('R4', 1)])

    def test_competencias(self):
        comps = {c['nombre']: c for c in self.r['competencias_stats']}
        programar = comps['Programar']
        self.assertEqual((programar['total'], programar['aprobados'], programar['pendientes'], programar['pct'], programar['num_aprendices']),
                         (3, 1, 2, 33, 2))
        self.assertEqual(programar['resultados_lista'], ['R1', 'R4'])
        self.assertEqual(programar['aprendices_aprobados_lista'], [{'id': 1, 'nombre_completo': 'Ana Ruiz', 'documento': '1'}])
        self.assertEqual(self.r['competencias_stats'][0]['nombre'], 'Programar', 'más pendientes primero')
        self.assertEqual(comps['Interactuar en lengua inglesa']['tipo'], 'ingles')
        self.assertEqual([c['nombre'] for c in self.r['mejores_competencias']][0], 'Interactuar en lengua inglesa')
        self.assertEqual([c['nombre'] for c in self.r['peores_competencias']][0], 'Ética')

    def test_linea_de_tiempo(self):
        self.assertEqual(self.r['timeline'], [('2026-03', {'total': 1, 'aprobados': 1}), ('2026-04', {'total': 2, 'aprobados': 1})])

    def test_resumen_y_distribucion(self):
        self.assertEqual(self.r['resumen'], {
            'total_aprendices_con_juicios': 2, 'total_competencias': 3, 'total_resultados': 4,
            'aprendices_con_todos': 1, 'aprendices_sin_ninguno': 1, 'promedio_juicios_por_aprendiz': 2.5,
            'transversales_vistas': 1, 'transversales_faltantes': 1, 'ingles_aprobados': 1, 'ingles_faltantes': 0,
        })
        self.assertEqual(self.r['distribucion_aprobacion'], {'0-25': 1, '26-50': 0, '51-75': 0, '76-99': 0, '100': 1})

    def test_juicio_sin_resultado_ni_competencia(self):
        r = analizar_juicios_ficha([juicio(1, None, 'POR EVALUAR', rap=None)], [aprendiz(1, 'Ana')])
        comp = r['competencias_stats'][0]
        self.assertEqual((comp['nombre'], comp['resultados_lista']), ('Sin nombre', []))
        self.assertEqual(r['resumen']['total_resultados'], 0)
        self.assertEqual(r['top_resultados'], [(None, 1)])

    def test_sin_juicios(self):
        r = analizar_juicios_ficha([], [aprendiz(1, 'Ana')])
        self.assertEqual((r['pct_global'], r['top_aprendices'], r['timeline']), (0, [], []))
        self.assertEqual(r['resumen']['promedio_juicios_por_aprendiz'], 0)


if __name__ == '__main__':
    unittest.main()
