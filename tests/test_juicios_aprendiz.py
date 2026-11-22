"""Análisis de los juicios de un aprendiz (servicio puro, sin base de datos)."""

import unittest
from datetime import datetime
from types import SimpleNamespace

from app.services.juicios_aprendiz import analizar_juicios, deduplicar_juicios


def juicio(competencia, rap, valor, fecha=None, evaluador=None, tipo='tecnica'):
    return SimpleNamespace(competencia=competencia, resultado_aprendizaje=rap, juicio=valor,
                           fecha_juicio=fecha, funcionario_registro=evaluador, tipo_competencia=tipo)


class DeduplicarTest(unittest.TestCase):
    def test_conserva_el_aprobado_y_luego_el_que_tiene_evaluador(self):
        pendiente = juicio('C1', 'R1', 'POR EVALUAR')
        aprobado = juicio(' c1 ', 'r1 ', 'APROBADO')
        self.assertEqual(deduplicar_juicios([pendiente, aprobado]), [aprobado])
        sin_nombre = juicio('C2', 'R2', 'POR EVALUAR')
        con_nombre = juicio('C2', 'R2', 'POR EVALUAR', evaluador='Ana')
        self.assertEqual(deduplicar_juicios([sin_nombre, con_nombre]), [con_nombre])
        self.assertEqual(deduplicar_juicios([aprobado, pendiente]), [aprobado], 'un pendiente no reemplaza al aprobado')

    def test_vacio(self):
        self.assertEqual(deduplicar_juicios([]), [])


class AnalizarTest(unittest.TestCase):
    def setUp(self):
        self.juicios = [
            juicio('Programar', 'R1', 'APROBADO', datetime(2026, 3, 5), 'Ana Gómez'),
            juicio('Programar', 'R2', 'NO APROBADO', datetime(2026, 4, 2), '1020304050'),
            juicio('Inglés', 'R3', 'AÚN NO APROBADO', None, None, tipo='ingles'),
            juicio(None, None, None, datetime(2026, 4, 20), 'Ana Gómez', tipo='transversal'),
        ]
        self.resultado = analizar_juicios(self.juicios)

    def test_estadisticas_por_tipo_con_la_regla_canonica(self):
        stats = self.resultado['stats_juicios']
        self.assertEqual((stats['total'], stats['aprobados'], stats['pct_total']), (4, 1, 25))
        self.assertEqual((stats['tecnica'], stats['tecnica_aprobada'], stats['pct_tecnica']), (2, 1, 50))
        self.assertEqual((stats['ingles'], stats['pct_ingles'], stats['pct_transversal']), (1, 0, 0))
        self.assertEqual(len(self.resultado['juicios_aprobados']), 1)
        self.assertEqual(len(self.resultado['juicios_pendientes']), 3)

    def test_evaluadores_excluyen_documentos_numericos(self):
        self.assertEqual(self.resultado['evaluadores'], ['Ana Gómez'])

    def test_competencias_ordenadas_con_estado(self):
        competencias = {c['nombre']: c for c in self.resultado['competencias']}
        self.assertEqual([c['tipo'] for c in self.resultado['competencias']], ['ingles', 'tecnica', 'transversal'])
        programar = competencias['Programar']
        self.assertEqual((programar['pct'], programar['estado_label'], programar['fecha_ultima']), (50, 'En Progreso', datetime(2026, 4, 2)))
        self.assertEqual(competencias['Inglés']['estado_label'], 'Pendiente')
        self.assertEqual(competencias['Sin nombre']['raps'][0],
                         {'rap': 'Sin descripción', 'juicio': 'POR EVALUAR', 'es_aprobado': False, 'fecha': '20/04/2026', 'evaluador': 'Ana Gómez'})
        self.assertEqual(competencias['Inglés']['raps'][0]['fecha'], 'Pendiente')
        self.assertEqual(competencias['Inglés']['raps'][0]['evaluador'], 'Sin registro')

    def test_competencia_completa(self):
        resultado = analizar_juicios([juicio('Base de datos', 'R1', 'APROBADO')])
        self.assertEqual(resultado['competencias'][0]['estado_label'], 'Completada')

    def test_linea_de_tiempo_e_instructores(self):
        self.assertEqual(self.resultado['timeline'], [('2026-03', {'total': 1, 'aprobados': 1}), ('2026-04', {'total': 2, 'aprobados': 0})])
        instructores = self.resultado['instructores']
        self.assertEqual(instructores['Ana Gómez'], {'total': 2, 'aprobados': 1, 'pendientes': 1, 'pct': 50})
        self.assertEqual(instructores['Sin registro']['total'], 1)

    def test_resumen(self):
        resumen = self.resultado['resumen']
        self.assertEqual(resumen['total_competencias'], 3)
        self.assertEqual(resumen['total_instructores'], 3)
        self.assertEqual(resumen['promedio_por_instructor'], 1.3)
        self.assertEqual((resumen['primera_evaluacion'], resumen['ultima_evaluacion']), (datetime(2026, 3, 5), datetime(2026, 4, 20)))
        self.assertEqual(resumen['dias_entre_evaluaciones'], 46)

    def test_sin_juicios(self):
        resultado = analizar_juicios([])
        self.assertEqual(resultado['stats_juicios']['pct_total'], 0)
        self.assertEqual(resultado['resumen']['promedio_por_instructor'], 0)
        self.assertIsNone(resultado['resumen']['primera_evaluacion'])
        self.assertEqual(resultado['resumen']['dias_entre_evaluaciones'], 0)


if __name__ == '__main__':
    unittest.main()
