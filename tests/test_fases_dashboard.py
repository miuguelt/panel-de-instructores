"""Pruebas unitarias para el servicio de fases_dashboard."""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import create_app, db
from app.models.ficha import Ficha
from app.models.archivo_ficha import ArchivoFichaVersion, TIPO_PLANEACION
from app.models.instructor import Instructor
from app.services.fases_dashboard import (
    UMBRALES_ESTANDAR_FASES,
    _buscar_version_planeacion,
    _calcular_estimado_por_juicios,
    obtener_seguimiento_fases_dashboard,
)


class FasesDashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
        })
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.instructor = Instructor(
            nombre='Instructor Prueba',
            correo='instructor_fases@sena.edu.co',
            rol='instructor',
        )
        self.instructor.set_password('clave123')
        db.session.add(self.instructor)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
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

        # Validar campos enriquecidos en fases y resumen
        self.assertIn('esperados', resultado['resumen_raps'])
        self.assertIn('porcentaje_esperados', resultado['resumen_raps'])
        self.assertIn('raps_vencidos_pendientes', resultado['resumen_raps'])
        self.assertIn('fases_vencidas', resultado['resumen_raps'])

        fase_primera = resultado['fases'][0]
        self.assertIn('resultados_esperados', fase_primera)
        self.assertIn('resultados_pendientes', fase_primera)
        self.assertIn('brecha_resultados', fase_primera)
        self.assertIn('competencias_pendientes', fase_primera)

    @patch('app.services.fases_dashboard._buscar_version_planeacion')
    @patch('app.services.fases_dashboard._obtener_planeacion_parseada')
    @patch('app.services.fases_dashboard._calcular_con_planeacion')
    def test_obtener_seguimiento_fases_dashboard_con_planeacion(
        self, mock_calcular, mock_parseada, mock_buscar_version
    ):
        """Si la ficha tiene versión y unidades de planeación, calcula con planeación GFPI."""
        ficha = Ficha(
            id=101,
            codigo='101010',
            nombre_programa='ADSO',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2025, 7, 25),
            fecha_fin=date(2027, 4, 23),
        )
        db.session.add(ficha)
        db.session.commit()

        mock_version = SimpleNamespace(id=50, tipo='planeacion_pedagogica', tamano_bytes=100, hash_sha256='hash50')
        mock_buscar_version.return_value = mock_version
        mock_parseada.return_value = {'unidades': [{'rap': 'RAP 1'}]}
        mock_calcular.return_value = {
            'disponible': True,
            'fuente': 'planeacion_gfpi',
            'planeacion_sincronizada': True,
            'desfase_fases': 0,
            'fases': [
                {
                    'nombre': 'ANÁLISIS',
                    'inicio': date(2025, 7, 25),
                    'fin': date(2026, 1, 24),
                    'resultados_esperados': 5,
                    'resultados_pendientes': 1,
                    'competencias_pendientes': [],
                }
            ],
            'resumen_raps': {
                'esperados': 5,
                'total': 10,
                'raps_vencidos_pendientes': 1,
                'fases_vencidas': [],
            },
        }

        resultado = obtener_seguimiento_fases_dashboard(ficha, hoy=date(2026, 10, 2))

        self.assertTrue(resultado['disponible'])
        self.assertEqual(resultado['fuente'], 'planeacion_gfpi')
        self.assertTrue(resultado['planeacion_sincronizada'])
        mock_calcular.assert_called_once()

    @patch('app.services.fases_dashboard._buscar_version_planeacion', return_value=None)
    def test_obtener_seguimiento_fases_dashboard_sin_planeacion(self, _mock_buscar):
        """Si la ficha no tiene planeación, usa el fallback estimado por juicios."""
        ficha = Ficha(
            id=102,
            codigo='102020',
            nombre_programa='ADSO',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2025, 7, 25),
            fecha_fin=date(2027, 4, 23),
        )
        db.session.add(ficha)
        db.session.commit()

        resultado = obtener_seguimiento_fases_dashboard(ficha, hoy=date(2026, 10, 2))
        self.assertTrue(resultado['disponible'])
        self.assertEqual(resultado['fuente'], 'estimado_reporte')

    @patch('app.services.fases_dashboard._buscar_version_planeacion')
    @patch('app.services.fases_dashboard._obtener_planeacion_parseada')
    @patch('app.services.fases_dashboard._calcular_con_planeacion', side_effect=RuntimeError('Error simulado'))
    def test_obtener_seguimiento_fases_dashboard_fallback_en_error(
        self, _mock_calc, mock_parseada, mock_buscar
    ):
        """Si el cálculo con planeación falla, se degrada elegantemente a juicios."""
        ficha = Ficha(
            id=103,
            codigo='103030',
            nombre_programa='ADSO',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2025, 7, 25),
            fecha_fin=date(2027, 4, 23),
        )
        db.session.add(ficha)
        db.session.commit()

        mock_buscar.return_value = SimpleNamespace(id=51, tipo='planeacion_pedagogica', tamano_bytes=100, hash_sha256='hash51')
        mock_parseada.return_value = {'unidades': [{'rap': 'RAP 1'}]}

        resultado = obtener_seguimiento_fases_dashboard(ficha, hoy=date(2026, 10, 2))
        self.assertTrue(resultado['disponible'])
        self.assertEqual(resultado['fuente'], 'estimado_reporte')

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

    @patch('app.services.fases_dashboard.construir_seguimiento_fases')
    @patch('app.services.fases_dashboard.construir_linea_tiempo')
    @patch('app.services.fases_dashboard.construir_calendario')
    @patch('app.services.fases_dashboard.construir_analisis')
    def test_calcular_con_planeacion_campos_enriquecidos(self, mock_analisis, mock_calendario, mock_linea, mock_seguimiento):
        """Prueba unitaria de _calcular_con_planeacion validando competencias y fases vencidas."""
        from app.services.fases_dashboard import _calcular_con_planeacion
        ficha = Ficha(id=1, codigo='1234', nombre_programa='ADSO', fecha_inicio=date(2025, 7, 25), fecha_fin=date(2027, 4, 23))
        version = SimpleNamespace(id=1, tamano_bytes=100, hash_sha256='abc')
        mock_analisis.return_value = {'resumen': {'aprendices_analizados': 10}, 'items': []}
        mock_calendario.return_value = {'configurado': True}
        mock_linea.return_value = {
            'resultados': [
                {'fase': 'ANÁLISIS', 'competencia': 'TIC', 'rap': 'RAP TIC Vencido', 'fecha_plan_fin': date(2026, 1, 24), 'porcentaje_avance': 20},
                {'fase': 'ANÁLISIS', 'competencia': 'TIC', 'rap': 'RAP TIC Aprobado', 'fecha_plan_fin': date(2026, 1, 24), 'porcentaje_avance': 100},
                {'fase': 'PLANEACIÓN', 'competencia': 'FÍSICA', 'rap': 'RAP Física Vencido', 'fecha_plan_fin': date(2026, 7, 24), 'porcentaje_avance': 10},
            ]
        }
        mock_seguimiento.return_value = {
            'fases': [
                {
                    'orden': 0, 'nombre': 'ANÁLISIS', 'icono': '🔍',
                    'inicio': date(2025, 7, 25), 'fin': date(2026, 1, 24),
                    'estado_tiempo': 'vencida', 'estado_ritmo': 'atrasado',
                    'porcentaje_tiempo': 100, 'porcentaje_aprobados': 50,
                    'porcentaje_evaluados': 100, 'resultados_esperados': 2,
                    'resultados_aprobados': 1, 'resultados_pendientes': 1,
                    'resultados_total': 2, 'brecha_resultados': 0,
                    'horas': 100, 'competencias_total': 1,
                },
                {
                    'orden': 1, 'nombre': 'PLANEACIÓN', 'icono': '📐',
                    'inicio': date(2026, 1, 25), 'fin': date(2026, 7, 24),
                    'estado_tiempo': 'vencida', 'estado_ritmo': 'atrasado',
                    'porcentaje_tiempo': 100, 'porcentaje_aprobados': 0,
                    'porcentaje_evaluados': 100, 'resultados_esperados': 1,
                    'resultados_aprobados': 0, 'resultados_pendientes': 1,
                    'resultados_total': 1, 'brecha_resultados': -1,
                    'horas': 100, 'competencias_total': 1,
                },
            ],
            'fase_esperada': {'orden': 2, 'nombre': 'EJECUCIÓN', 'icono': '⚙️', 'porcentaje_tiempo': 50},
            'fase_real': {'orden': 0, 'nombre': 'ANÁLISIS', 'icono': '🔍', 'porcentaje_aprobados': 50, 'resultados_aprobados': 1, 'resultados_total': 2},
            'estado': 'atrasado',
            'resultados': {'total': 3, 'aprobados': 1, 'evaluados': 3, 'pendientes': 2, 'esperados': 3, 'brecha': 0, 'porcentaje_aprobados': 33.3},
        }

        res = _calcular_con_planeacion(ficha, version, {'unidades': []}, date(2026, 10, 2))
        self.assertTrue(res['disponible'])
        self.assertEqual(res['fuente'], 'planeacion_gfpi')
        self.assertEqual(res['desfase_fases'], 2)
        self.assertEqual(res['resumen_raps']['raps_vencidos_pendientes'], 2)
        self.assertEqual(len(res['resumen_raps']['fases_vencidas']), 2)
        self.assertIn('raps_vencidos_detalle', res['resumen_raps'])
        self.assertEqual(len(res['resumen_raps']['raps_vencidos_detalle']), 2)
        self.assertEqual(res['resumen_raps']['raps_vencidos_detalle'][0]['rap'], 'RAP TIC Vencido')
        self.assertEqual(res['resumen_raps']['raps_vencidos_detalle'][0]['competencia_tipo'], 'tecnica')
        fase_0 = res['fases'][0]
        self.assertEqual(fase_0['competencias_pendientes'][0]['competencia'], 'TIC')
        self.assertEqual(fase_0['competencias_pendientes'][0]['pendientes'], 1)

    def test_buscar_version_planeacion_directa_y_por_programa(self):
        """Verifica resolución directa y fallback a otra ficha del mismo programa."""
        ficha1 = Ficha(
            id=201, codigo='201', codigo_programa='228118', nombre_programa='ADSO',
            instructor_id=self.instructor.id, fecha_inicio=date(2025, 1, 1),
        )
        ficha2 = Ficha(
            id=202, codigo='202', codigo_programa='228118', nombre_programa='ADSO',
            instructor_id=self.instructor.id, fecha_inicio=date(2025, 1, 1),
        )
        db.session.add_all([ficha1, ficha2])
        db.session.commit()

        # Sin versión en ninguna ficha
        self.assertIsNone(_buscar_version_planeacion(ficha1))

        # Versión disponible en ficha hermana del mismo programa
        v2 = ArchivoFichaVersion(
            ficha_id=ficha2.id, instructor_id=self.instructor.id, tipo=TIPO_PLANEACION, version=1, estado='procesado',
            nombre_archivo='planeacion.xlsx', ruta_archivo='planeacion.xlsx',
            tamano_bytes=100, hash_sha256='hash202',
        )
        db.session.add(v2)
        db.session.commit()
        encontrada = _buscar_version_planeacion(ficha1)
        self.assertIsNotNone(encontrada)
        self.assertEqual(encontrada.id, v2.id)

        # Versión propia en la ficha toma prioridad
        v1 = ArchivoFichaVersion(
            ficha_id=ficha1.id, instructor_id=self.instructor.id, tipo=TIPO_PLANEACION, version=1, estado='procesado',
            nombre_archivo='planeacion1.xlsx', ruta_archivo='planeacion1.xlsx',
            tamano_bytes=100, hash_sha256='hash201',
        )
        db.session.add(v1)
        db.session.commit()
        self.assertEqual(_buscar_version_planeacion(ficha1).id, v1.id)


if __name__ == '__main__':
    unittest.main()
