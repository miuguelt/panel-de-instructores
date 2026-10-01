"""Escenarios del seguimiento de evaluaciones por RAP y tramo del Gantt."""

import unittest
from datetime import datetime
from types import SimpleNamespace

from app.services.evaluacion_planeacion import evaluar_resultado, construir_seguimiento


def aprendiz(numero, nombre, documento=None):
    return SimpleNamespace(id=numero, nombre_completo=nombre, documento=documento or str(numero))


def juicio(numero, estado, fecha=None, instructor=None, registro=1):
    return SimpleNamespace(aprendiz_id=numero, juicio=estado, fecha_juicio=fecha,
                           funcionario_registro=instructor, id=registro)


class EvaluacionPlaneacionTestCase(unittest.TestCase):
    def test_no_aprobado_es_evaluado_y_por_evaluar_o_sin_fila_es_pendiente(self):
        detalle = evaluar_resultado([aprendiz(1, 'Zulma'), aprendiz(2, 'Ángela'), aprendiz(3, 'Carlos')], [
            juicio(1, 'NO APROBADO', datetime(2026, 9, 1), 'Instructor A'),
            juicio(2, 'POR EVALUAR', instructor='Responsable previsto'),
        ])
        self.assertEqual(detalle['resumen'], dict(total=3, evaluados=1, pendientes=2, aprobados=0))
        self.assertEqual([a['nombre'] for a in detalle['aprendices']], ['Ángela', 'Carlos', 'Zulma'])
        self.assertIsNone(detalle['aprendices'][0]['instructor'])
        self.assertEqual(detalle['aprendices'][2]['instructor'], 'Instructor A')
        self.assertEqual(detalle['aprendices'][2]['fecha'], '01/09/2026')

    def test_duplicados_usan_el_ultimo_juicio_emitido_y_no_la_fila_administrativa(self):
        detalle = evaluar_resultado([aprendiz(1, 'Ana')], [
            juicio(1, 'APROBADO', datetime(2026, 8, 1), 'Primero'),
            juicio(1, 'NO APROBADO', datetime(2026, 9, 1), 'Último', 2),
            juicio(1, 'POR EVALUAR', datetime(2026, 9, 2), 'Asignado', 3),
            juicio(999, 'APROBADO', instructor='Otra ficha'),
        ])
        self.assertEqual(detalle['resumen']['evaluados'], 1)
        self.assertEqual(detalle['resumen']['aprobados'], 0)
        self.assertEqual(detalle['aprendices'][0]['instructor'], 'Último')

    def test_empate_fecha_resuelve_por_id_y_juicio_sin_fecha_no_inventa_datos(self):
        detalle = evaluar_resultado([aprendiz(1, 'Ana')], [
            juicio(1, 'NO APROBADO', registro=1), juicio(1, 'APROBADO', registro=2),
        ])
        self.assertEqual(detalle['resumen']['aprobados'], 1)
        self.assertIsNone(detalle['aprendices'][0]['fecha'])
        self.assertEqual(detalle['aprendices'][0]['instructor'], 'No registrado')

    def test_vacio_y_estados_administrativos_no_son_evaluaciones(self):
        self.assertEqual(evaluar_resultado([], [])['resumen']['total'], 0)
        for estado in [None, '', 'PENDIENTE', 'SIN EVALUAR', 'EN FORMACIÓN']:
            detalle = evaluar_resultado([aprendiz(1, 'Ana')], [juicio(1, estado)])
            self.assertEqual(detalle['resumen']['pendientes'], 1)
        for estado in ['A', 'NA', 'Aprobada', 'No aprobada']:
            detalle = evaluar_resultado([aprendiz(1, 'Ana')], [juicio(1, estado)])
            self.assertEqual(detalle['resumen']['evaluados'], 1)

    def test_tramo_agrega_por_persona_y_conserva_evaluador_de_cada_rap(self):
        grupo = [aprendiz(1, 'Ana'), aprendiz(2, 'Beatriz'), aprendiz(3, 'Carlos')]
        r1 = dict(rap='Resultado uno', rap_codigo='111111', actividad='AP01',
                  evaluacion=evaluar_resultado(grupo, [juicio(1, 'APROBADO', instructor='Uno'), juicio(2, 'NA', instructor='Dos')]))
        r2 = dict(rap='Resultado dos', rap_codigo='222222', actividad='AP02',
                  evaluacion=evaluar_resultado(grupo, [juicio(1, 'APROBADO', instructor='Tres')]))
        competencia = dict(nombre='Competencia', fase='ANÁLISIS', resultados=[r1, r2], etiqueta_trimestre='T1')
        linea = dict(competencias=[competencia, dict(competencia, fase='PLANEACIÓN', resultados=[r2])])
        catalogo = construir_seguimiento(linea)
        detalle = catalogo[competencia['seguimiento_id']]
        self.assertEqual(detalle['resumen'], dict(total=3, evaluados=1, pendientes=2,
            parciales=1, sin_evaluar=1, aprobados=1, evaluaciones_pendientes=3))
        self.assertEqual(detalle['aprendices'][0]['evaluados'], 2)
        self.assertEqual([r['instructor'] for r in detalle['aprendices'][0]['resultados']], ['Uno', 'Tres'])
        self.assertEqual(detalle['aprendices'][1]['estado'], 'parcial')
        self.assertEqual(detalle['aprendices'][2]['estado'], 'pendiente')
        self.assertEqual(detalle['resultados'][0]['actividad'], 'AP01')
        self.assertNotEqual(linea['competencias'][0]['seguimiento_id'], linea['competencias'][1]['seguimiento_id'])
        self.assertEqual(competencia['evaluacion_resumen'], detalle['resumen'])

    def test_tramo_sin_resultados_o_sin_aprendices_no_declara_evaluacion(self):
        linea = {'competencias': [dict(nombre='Vacía', resultados=[]),
            dict(nombre='Sin grupo', resultados=[dict(rap='RAP', evaluacion=evaluar_resultado([], []))])]}
        catalogo = construir_seguimiento(linea)
        self.assertEqual(len(catalogo), 2)
        self.assertEqual(catalogo['tramo-0']['resumen']['total'], 0)
        self.assertEqual(catalogo['tramo-1']['resumen']['evaluados'], 0)
