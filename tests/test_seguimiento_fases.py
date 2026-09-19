import unittest
from datetime import date, datetime
from types import SimpleNamespace

from app.services.calendario_formacion import construir_calendario
from app.services.linea_tiempo import construir_linea_tiempo
from app.services.seguimiento_fases import construir_seguimiento_fases


def _ficha():
    return SimpleNamespace(
        fecha_inicio=date(2025, 7, 25),
        fecha_fin=date(2027, 10, 24),
        duracion_productiva_meses=6,
    )


def _item(fase, actividad, trimestre, **cambios):
    item = {
        'fase': fase,
        'actividad': actividad,
        'competencia': f'Competencia {fase}',
        'competencia_tipo': 'tecnica',
        'rap': f'RAP {actividad}',
        'rap_codigo': '',
        'horas_total': 30,
        'horas_directas': 24,
        'horas_independientes': 6,
        'instructores': ['Instructor Técnico'],
        'trimestres': [f'Trimestre {trimestre}'],
        'trimestre': f'Trimestre {trimestre}',
        'total_juicios': 0,
        'aprobados': 0,
        'aprendices_evaluados': 0,
        'aprendices_aprobados': 0,
        'porcentaje_avance': 0,
        'fechas_aprobacion': [],
        'ultima_evaluacion': None,
    }
    item.update(cambios)
    return item


def _linea(items, hoy=date(2026, 8, 18), aprendices=10):
    calendario = construir_calendario(_ficha(), hoy=hoy)
    linea = construir_linea_tiempo(items, calendario, aprendices_meta=aprendices, hoy=hoy)
    return linea, calendario


class SeguimientoFasesTestCase(unittest.TestCase):
    def test_given_fecha_en_ejecucion_when_calculo_then_expone_fase_esperada_y_fase_real(self):
        """Given T5, When se calcula, Then la fase y el conteo son explícitos."""
        items = [
            _item('ANÁLISIS', 'AP01', 1, total_juicios=1, porcentaje_avance=100,
                  aprendices_evaluados=10, aprendices_aprobados=10,
                  ultima_evaluacion=datetime(2025, 9, 10)),
            _item('PLANEACIÓN', 'AP04', 2, total_juicios=1, porcentaje_avance=100,
                  aprendices_evaluados=10, aprendices_aprobados=10,
                  ultima_evaluacion=datetime(2026, 1, 10)),
            _item('EJECUCIÓN', 'AP10', 5),
            _item('EVALUACIÓN', 'AP12', 7),
        ]
        linea, calendario = _linea(items)

        seguimiento = construir_seguimiento_fases(linea, calendario, date(2026, 8, 18))

        self.assertEqual(seguimiento['fase_esperada']['nombre'], 'EJECUCIÓN')
        self.assertEqual(seguimiento['fase_real']['nombre'], 'EJECUCIÓN')
        self.assertEqual(seguimiento['resultados']['total'], 4)
        self.assertEqual(seguimiento['resultados']['evaluados'], 2)
        self.assertEqual(seguimiento['resultados']['aprobados'], 2)
        self.assertIn(seguimiento['estado'], {'atrasado', 'al_dia'})

    def test_given_fase_anterior_incompleta_when_fecha_avanza_then_marca_atraso(self):
        """Given ANÁLISIS incompleto, When el calendario está en T5, Then hay atraso."""
        items = [
            _item('ANÁLISIS', 'AP01', 1, total_juicios=1, porcentaje_avance=20,
                  aprendices_evaluados=2, aprendices_aprobados=2,
                  ultima_evaluacion=datetime(2025, 9, 10)),
            _item('PLANEACIÓN', 'AP04', 2),
            _item('EJECUCIÓN', 'AP10', 5),
            _item('EVALUACIÓN', 'AP12', 7),
        ]
        linea, calendario = _linea(items)

        seguimiento = construir_seguimiento_fases(linea, calendario, date(2026, 8, 18))

        self.assertEqual(seguimiento['fase_esperada']['nombre'], 'EJECUCIÓN')
        self.assertEqual(seguimiento['fase_real']['nombre'], 'ANÁLISIS')
        self.assertEqual(seguimiento['estado'], 'atrasado')
        self.assertLess(seguimiento['resultados']['evaluados'], seguimiento['resultados']['esperados'])
        self.assertEqual(seguimiento['proyeccion']['estado'], 'sin_datos')

    def test_given_ritmo_de_evaluacion_when_proyecto_then_compara_raps_con_fecha_objetivo(self):
        """Given RAPs evaluados recientemente, When se proyecta, Then mide si alcanza el fin."""
        items = [
            _item('ANÁLISIS', 'AP01', 1, total_juicios=1, porcentaje_avance=100,
                  aprendices_evaluados=10, aprendices_aprobados=10,
                  ultima_evaluacion=datetime(2026, 7, 1)),
            _item('PLANEACIÓN', 'AP04', 2, total_juicios=1, porcentaje_avance=100,
                  aprendices_evaluados=10, aprendices_aprobados=10,
                  ultima_evaluacion=datetime(2026, 8, 1)),
            _item('EJECUCIÓN', 'AP10', 5),
            _item('EVALUACIÓN', 'AP12', 7),
        ]
        linea, calendario = _linea(items)

        seguimiento = construir_seguimiento_fases(linea, calendario, date(2026, 8, 18))

        self.assertEqual(seguimiento['proyeccion']['resultados_pendientes'], 2)
        self.assertGreater(seguimiento['proyeccion']['ritmo_mensual'], 0)
        self.assertIsNotNone(seguimiento['proyeccion']['fecha_cierre'])
        self.assertIn(seguimiento['proyeccion']['estado'], {'viable', 'en_riesgo'})

    def test_given_filas_por_evaluar_when_mido_raps_then_no_las_cuenta_como_evaluadas(self):
        """Given filas POR EVALUAR, When se mide, Then no son juicios emitidos."""
        items = [_item(
            'ANÁLISIS', 'AP01', 1,
            total_juicios=10,
            aprendices_evaluados=10,
            total_juicios_evaluados=0,
            aprendices_con_juicio=0,
        )]
        linea, calendario = _linea(items, hoy=date(2025, 9, 10))

        seguimiento = construir_seguimiento_fases(linea, calendario, date(2025, 9, 10))

        self.assertEqual(seguimiento['resultados']['evaluados'], 0)
        self.assertEqual(seguimiento['proyeccion']['resultados_pendientes'], 1)


if __name__ == '__main__':
    unittest.main()
