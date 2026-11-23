"""Resúmenes del reporte integral del aprendiz (funciones puras)."""

import unittest
from datetime import date, datetime
from types import SimpleNamespace

from app.services.juicios_aprendiz import competencias_por_tipo, tipo_competencia
from app.services.reporte_aprendiz import (
    detalle_asistencia,
    resumir_evidencias,
    resumir_seguimiento,
    ultima_actividad,
)


def juicio(competencia, valor, tipo=None, fecha=None, rap='R', evaluador=None):
    return SimpleNamespace(competencia=competencia, juicio=valor, tipo_competencia=tipo, fecha_juicio=fecha,
                           resultado_aprendizaje=rap, funcionario_registro=evaluador)


class TipoCompetenciaTest(unittest.TestCase):
    def test_usa_el_tipo_registrado_o_lo_clasifica(self):
        self.assertEqual(tipo_competencia(juicio('Cualquiera', 'APROBADO', tipo='transversal')), 'transversal')
        self.assertEqual(tipo_competencia(juicio('Interactuar en lengua inglesa', 'APROBADO')), 'ingles')
        self.assertEqual(tipo_competencia(juicio(None, 'APROBADO')), 'tecnica')
        self.assertEqual(tipo_competencia(juicio('X', 'APROBADO', tipo='desconocido')), 'tecnica')


class CompetenciasPorTipoTest(unittest.TestCase):
    def test_agrupa_con_estado_y_resumen(self):
        juicios = [
            juicio(' Programar ', 'APROBADO', 'tecnica', datetime(2026, 3, 1), 'R1', 'Ana'),
            juicio('Programar', 'NO APROBADO', 'tecnica', datetime(2026, 4, 1), 'R2'),
            juicio('Base de datos', 'APROBADO', 'tecnica', None, None),
            juicio('Ética', 'POR EVALUAR', 'transversal', None, 'R3'),
        ]
        por_tipo, resumen = competencias_por_tipo(juicios)
        self.assertEqual([c['nombre'] for c in por_tipo['tecnica']], ['Base de datos', 'Programar'])
        programar = por_tipo['tecnica'][1]
        self.assertEqual((programar['total_raps'], programar['aprobados_raps'], programar['pendientes_raps']), (2, 1, 1))
        self.assertEqual((programar['pct'], programar['estado'], programar['ultima_fecha']), (50, 'en_progreso', datetime(2026, 4, 1)))
        self.assertEqual(programar['raps'][0], {'resultado': 'R1', 'juicio': 'APROBADO', 'aprobado': True,
                                                'fecha': datetime(2026, 3, 1), 'instructor': 'Ana'})
        self.assertEqual(por_tipo['tecnica'][0]['estado'], 'completada')
        self.assertEqual(por_tipo['tecnica'][0]['raps'][0]['resultado'], 'Sin descripción de resultado')
        self.assertEqual(por_tipo['transversal'][0]['estado'], 'pendiente')
        self.assertEqual(por_tipo['transversal'][0]['raps'][0]['instructor'], 'Sistema')
        self.assertEqual(resumen['tecnica'], {'total': 2, 'completadas': 1, 'en_progreso': 1, 'pendientes': 0,
                                              'total_raps': 3, 'aprobados_raps': 2, 'pct_raps': 67})
        self.assertEqual(resumen['ingles']['pct_raps'], 0)

    def test_sin_nombre_y_juicio_vacio(self):
        por_tipo, _ = competencias_por_tipo([juicio(None, None, 'tecnica')])
        self.assertEqual(por_tipo['tecnica'][0]['nombre'], 'Sin nombre')
        self.assertEqual(por_tipo['tecnica'][0]['raps'][0]['juicio'], 'Sin registrar')


class DetalleAsistenciaTest(unittest.TestCase):
    def registro(self, estado, fecha, causal=None, soporte=None):
        sesion = SimpleNamespace(fecha=fecha, observaciones='Clase') if fecha else None
        return SimpleNamespace(estado=estado, sesion=sesion, causal_justificacion=causal, nota=None, soporte_url=soporte)

    def test_conteos_mensuales_y_detalle(self):
        registros = [self.registro('ASISTE', date(2026, 5, 2)), self.registro('TARDANZA', date(2026, 5, 3)),
                     self.registro('FALTA', date(2026, 4, 1)), self.registro('EXCUSA_MEDICA', date(2026, 4, 2), 'CITA', 'x.pdf'),
                     self.registro('FALTA_JUSTIFICADA', None), self.registro('OTRO', date(2026, 4, 3))]
        detalle = detalle_asistencia(registros)
        estados = detalle['estados']
        self.assertEqual((estados['ASISTE']['count'], estados['SIN_REGISTRO']['count']), (1, 1))
        self.assertEqual((detalle['faltas_injustificadas'], detalle['faltas_justificadas']), (1, 2))
        self.assertEqual(detalle['mensual'], [
            ('2026-05', {'total': 2, 'asistio': 1, 'tardanzas': 1, 'faltas': 0, 'justificadas': 0}),
            ('2026-04', {'total': 3, 'asistio': 0, 'tardanzas': 0, 'faltas': 1, 'justificadas': 1})])
        self.assertEqual(detalle['registros'][3], {'fecha': date(2026, 4, 2), 'estado': 'EXCUSA_MEDICA', 'causal': 'CITA',
                                                   'nota': None, 'soporte': True, 'observaciones_sesion': 'Clase'})
        self.assertEqual(detalle['registros'][4]['fecha'], None)

    def test_vacio(self):
        detalle = detalle_asistencia([])
        self.assertEqual((detalle['mensual'], detalle['registros'], detalle['faltas_injustificadas']), ([], [], 0))


class EvidenciasYSeguimientoTest(unittest.TestCase):
    def test_resumen_de_evidencias(self):
        e = lambda calificacion=None, calificada=False: SimpleNamespace(calificacion=calificacion, calificada=calificada)
        items = [{'estado': 'entregada', 'entrega': e('4,5', True)}, {'estado': 'retraso', 'entrega': e('3')},
                 {'estado': 'correccion', 'entrega': e('no numérica')}, {'estado': 'pendiente', 'entrega': None},
                 {'estado': 'vencida', 'entrega': None}]
        resumen = resumir_evidencias(items)
        self.assertEqual(resumen, {'total': 5, 'entregas': 3, 'a_tiempo': 1, 'retrasos': 1, 'pendientes': 1, 'vencidas': 1,
                                   'correcciones': 1, 'calificadas': 1, 'promedio': 3.75, 'pct_entrega': 60, 'pct_a_tiempo': 20})
        self.assertEqual(resumir_evidencias([])['promedio'], None)
        self.assertEqual(resumir_evidencias([])['pct_entrega'], 0)

    def test_resumen_de_seguimiento(self):
        a = lambda estado, nivel='amarilla': SimpleNamespace(estado=estado, nivel=nivel)
        p = lambda estado: SimpleNamespace(estado=estado)
        resumen = resumir_seguimiento([a('activa', 'roja'), a('escalada_comite', 'roja'), a('resuelta'), a('activa')],
                                      [p('pendiente'), p('cumplido'), p('vencido'), p('vencido')])
        self.assertEqual(resumen, {'alertas_total': 4, 'alertas_activas': 2, 'alertas_rojas': 2, 'alertas_resueltas': 1,
                                   'planes_total': 4, 'planes_pendientes': 1, 'planes_cumplidos': 1, 'planes_vencidos': 2})

    def test_ultima_actividad_combina_fechas_y_fechas_con_hora(self):
        self.assertEqual(ultima_actividad(datetime(2026, 3, 1, 9), date(2026, 3, 5), None), datetime(2026, 3, 5))
        self.assertIsNone(ultima_actividad(None, None, None))


if __name__ == '__main__':
    unittest.main()
