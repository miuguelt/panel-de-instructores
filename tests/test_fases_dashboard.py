"""Pruebas unitarias para el servicio de fases_dashboard."""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import create_app, db
from app.models.ficha import Ficha
from app.models.instructor import Instructor
from app.services.fases_dashboard import (
    UMBRALES_ESTANDAR_FASES,
    _buscar_version_planeacion,
    _calcular_estimado_por_juicios,
    obtener_seguimiento_fases_dashboard,
)


class FasesDashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_umbrales_cubren_ciclo_completo(self):
        """Los umbrales estándar de proyectos deben sumar del 0 al 100%."""
        self.assertEqual(UMBRALES_ESTANDAR_FASES[0][0], 'ANÁLISIS')
        self.assertEqual(UMBRALES_ESTANDAR_FASES[0][2], 0.0)
        self.assertEqual(UMBRALES_ESTANDAR_FASES[-1][0], 'EVALUACIÓN')
        self.assertEqual(UMBRALES_ESTANDAR_FASES[-1][3], 100.0)

    def test_estimado_por_juicios_calcula_fases_sin_excepciones(self):
        """Si una ficha solo tiene juicios y fechas, debe calcular fases estimadas con degradación elegante."""
        ficha = Ficha(
            id=99999,
            codigo='9999999',
            nombre_programa='Prueba sin planeación',
            fecha_inicio=date(2025, 1, 1),
            fecha_fin=date(2026, 12, 31),
        )
        cronograma = {
            'configurado': True,
            'porcentaje': 65.0,
            'porcentaje_lectiva': 65.0,
            'fase': 'lectiva',
            'fase_label': 'Etapa lectiva',
            'inicio_lectiva': date(2025, 1, 1),
            'fin_lectiva': date(2026, 6, 30),
        }
        hoy = date(2025, 10, 1)

        resultado = _calcular_estimado_por_juicios(ficha, cronograma, hoy)

        self.assertTrue(resultado['disponible'])
        self.assertEqual(resultado['fuente'], 'estimado_reporte')
        self.assertFalse(resultado['planeacion_sincronizada'])
        self.assertEqual(resultado['fase_esperada']['nombre'], 'EJECUCIÓN')
        self.assertEqual(len(resultado['fases']), 4)
        self.assertIn('mensaje_veredicto', resultado)

    def test_ficha_existente_con_planeacion_retorna_fuente_gfpi(self):
        """La ficha 3 de prueba que tiene GFPI-F-134 debe identificarse como sincronizada."""
        ficha3 = db.session.get(Ficha, 3)
        if not ficha3:
            self.skipTest('Ficha 3 no disponible en la base de datos local.')

        resultado = obtener_seguimiento_fases_dashboard(ficha3, hoy=date(2026, 9, 11))

        self.assertTrue(resultado['disponible'])
        self.assertEqual(resultado['fuente'], 'planeacion_gfpi')
        self.assertTrue(resultado['planeacion_sincronizada'])
        self.assertIn('EJECUCIÓN', resultado['fase_esperada']['nombre'].upper())
        self.assertEqual(len(resultado['fases']), 4)
        self.assertGreaterEqual(resultado['desfase_fases'], 0)

    def test_ficha_sin_fechas_configuradas_manejo_seguro(self):
        """Una ficha sin fechas no debe lanzar error y debe indicar fechas pendientes."""
        ficha_sin_fechas = Ficha(
            id=88888,
            codigo='8888888',
            nombre_programa='Programa sin fechas',
            fecha_inicio=None,
            fecha_fin=None,
        )
        cronograma_invalido = {
            'configurado': False,
            'porcentaje': 0,
            'porcentaje_lectiva': 0,
            'fase': 'sin_fechas',
            'fase_label': 'Fechas pendientes',
        }

        resultado = _calcular_estimado_por_juicios(ficha_sin_fechas, cronograma_invalido, date.today())

        self.assertTrue(resultado['disponible'])
        self.assertEqual(resultado['fase_esperada']['nombre'], 'Fechas pendientes')
        self.assertEqual(resultado['estado'], 'sin_datos')


if __name__ == '__main__':
    unittest.main()
