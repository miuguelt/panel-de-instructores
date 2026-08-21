import unittest
from datetime import date
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.services.planeacion import (
    calcular_fechas_estimadas,
    comparar_fuentes,
    componente_instructor,
    normalizar_instructor,
    parsear_planeacion,
)
from app import create_app, db
from app.models import Aprendiz, ArchivoFichaVersion, Ficha, Instructor, JuicioEvaluativo
from app.services.analisis_planeacion import construir_analisis
from app.services.emparejamiento_juicios import es_aprobado as _aprobado
from app.services.graficos_planeacion import (
    construir_curva_svg,
    construir_fases_progreso,
    construir_heatmap_docente,
)
from tests.apoyo_planeacion import crear_planeacion_xlsx


class PlaneacionServiceTestCase(unittest.TestCase):
    def _crear_archivo(self, carpeta):
        return crear_planeacion_xlsx(carpeta)

    def test_parsea_celdas_combinadas_y_consolida_resultados(self):
        with TemporaryDirectory() as carpeta:
            resultado = parsear_planeacion(self._crear_archivo(carpeta))

        self.assertEqual(resultado['metadata']['codigo_programa'], '228118 v 1.0')
        self.assertEqual(len(resultado['unidades']), 2)
        primera = resultado['unidades'][0]
        self.assertEqual(primera['fase'], 'ANÁLISIS')
        self.assertEqual(primera['actividad'], 'AP01. Contextualizar')
        self.assertEqual(primera['horas_total'], 22)
        self.assertEqual(resultado['resumen']['resultados'], 2)
        self.assertEqual(resultado['resumen']['horas_total'], 47)

    def test_calcula_fechas_ponderadas_por_carga_horaria(self):
        unidades = [
            {'horas_total': 10, 'rap': 'Uno'},
            {'horas_total': 30, 'rap': 'Dos'},
        ]

        resultado = calcular_fechas_estimadas(
            unidades,
            date(2026, 1, 1),
            date(2026, 2, 9),
        )

        self.assertEqual(resultado[0]['fecha_inicio_estimada'], date(2026, 1, 1))
        self.assertEqual(resultado[0]['fecha_fin_estimada'], date(2026, 1, 10))
        self.assertEqual(resultado[1]['fecha_inicio_estimada'], date(2026, 1, 11))
        self.assertEqual(resultado[1]['fecha_fin_estimada'], date(2026, 2, 9))

    def test_comparar_fuentes_advierte_programa_distinto(self):
        resultado = comparar_fuentes(
            {
                'codigo_programa': '228118 v 1.0',
                'nombre_programa': 'Tecnólogo en Analisis y Desarrollo de Software',
            },
            {
                'codigo_programa': '133100',
                'nombre_programa': 'CONTABILIZACION DE OPERACIONES COMERCIALES Y FINANCIERAS.',
            },
        )

        self.assertFalse(resultado['alineado'])
        self.assertTrue(any('código' in motivo.lower() for motivo in resultado['motivos']))
        self.assertTrue(any('nombre' in motivo.lower() for motivo in resultado['motivos']))

    def test_solo_el_estado_aprobado_cuenta_como_aprobado(self):
        self.assertTrue(_aprobado('APROBADO'))
        self.assertFalse(_aprobado('NO APROBADO'))
        self.assertFalse(_aprobado('AÚN NO APROBADO'))
        self.assertFalse(_aprobado('POR EVALUAR'))


class AnalisisPlaneacionTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        self.instructor = Instructor(nombre='Uno', correo='uno-analisis@sena.edu.co')
        self.instructor.set_password('x')
        db.session.add(self.instructor)
        db.session.flush()
        self.ficha = Ficha(
            codigo='3336360',
            codigo_ficha='3336360',
            codigo_programa='228118',
            nombre_programa='Tecnólogo en Analisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 2, 9),
        )
        db.session.add(self.ficha)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def test_usa_fecha_del_reporte_y_calcula_avance_esperado_por_horas(self):
        contenido = {
            'metadata': {
                'codigo_programa': '228118 v 1.0',
                'nombre_programa': 'Tecnólogo en Analisis y Desarrollo de Software',
            },
            'unidades': [
                {'fase': 'ANÁLISIS', 'actividad': 'AP01', 'competencia': 'Tecnología',
                 'competencia_tipo': 'tecnica', 'rap': '601390 - Uno', 'rap_codigo': '601390',
                 'horas_total': 10, 'horas_directas': 8, 'horas_independientes': 2,
                 'trimestre': 'Trimestre 1'},
                {'fase': 'PLANEACIÓN', 'actividad': 'AP02', 'competencia': 'Comunicación',
                 'competencia_tipo': 'transversal', 'rap': '601401 - Dos', 'rap_codigo': '601401',
                 'horas_total': 30, 'horas_directas': 20, 'horas_independientes': 10,
                 'trimestre': 'Trimestre 2'},
            ],
            'resumen': {
                'horas_total': 40,
                'horas_directas': 28,
                'horas_independientes': 12,
            },
        }
        aprendiz = Aprendiz(
            documento='1001', nombre='Ana', apellidos='Pérez',
            estado='EN_FORMACION', ficha_id=self.ficha.id,
        )
        db.session.add(aprendiz)
        db.session.commit()
        version_reporte = SimpleNamespace(
            metadata_json='{"fecha_reporte":"2026-01-20"}',
        )

        analisis = construir_analisis(
            self.ficha,
            contenido,
            version_reporte=version_reporte,
        )

        self.assertEqual(analisis['fecha_corte'], date(2026, 1, 20))
        self.assertEqual(analisis['resumen']['avance_esperado'], 50)
        self.assertEqual(analisis['resumen']['aprendices_total'], 1)
        self.assertEqual(analisis['resumen']['aprendices_inactivos'], 0)

    def test_considera_todos_los_estados_academicos_de_planeacion(self):
        estados = ('CONDICIONADO', 'Inducción', 'POR CERTIFICAR', 'CERTIFICADO', 'APLAZADO')
        db.session.add_all([
            Aprendiz(
                documento=str(2000 + indice),
                nombre='Aprendiz',
                apellidos=estado,
                estado=estado,
                ficha_id=self.ficha.id,
            )
            for indice, estado in enumerate(estados, start=1)
        ])
        db.session.add(Aprendiz(
            documento='2999',
            nombre='Aprendiz',
            apellidos='Retirado',
            estado='RETIRO_VOLUNTARIO',
            ficha_id=self.ficha.id,
        ))
        db.session.commit()

        analisis = construir_analisis(
            self.ficha,
            {'metadata': {}, 'unidades': [], 'resumen': {}},
            hoy=date(2026, 1, 20),
        )
        estados_vista = {
            estado['codigo']: estado['cantidad']
            for estado in analisis['estados_aprendices']
        }

        self.assertEqual(analisis['resumen']['aprendices_total'], 6)
        self.assertEqual(analisis['resumen']['aprendices_analizados'], 5)
        self.assertEqual(analisis['resumen']['aprendices_activos'], 3)
        self.assertEqual(analisis['resumen']['aprendices_inactivos'], 3)
        self.assertEqual(estados_vista['CONDICIONADO'], 1)
        self.assertEqual(estados_vista['INDUCCION'], 1)
        self.assertEqual(estados_vista['POR_CERTIFICAR'], 1)
        self.assertEqual(estados_vista['CERTIFICADO'], 1)
        self.assertEqual(estados_vista['APLAZADO'], 1)

    def test_construir_curva_svg_genera_abanico_y_puntos(self):
        proyeccion = {
            'curva': [
                {'numero': 1, 'etiqueta': 'T1', 'nombre': 'Trimestre 1', 'etapa': 'lectiva', 'estado': 'cumplido', 'planeado': 10, 'real': 15, 'pv_horas': 300, 'ev_horas': 450},
                {'numero': 2, 'etiqueta': 'T2', 'nombre': 'Trimestre 2', 'etapa': 'lectiva', 'estado': 'en_curso', 'planeado': 25, 'real': 30, 'pv_horas': 750, 'ev_horas': 900},
                {'numero': 3, 'etiqueta': 'T3', 'nombre': 'Trimestre 3', 'etapa': 'lectiva', 'estado': 'futuro', 'planeado': 50, 'real': None, 'pv_horas': 1500, 'ev_horas': None},
                {'numero': 4, 'etiqueta': 'EP', 'nombre': 'Etapa productiva', 'etapa': 'productiva', 'estado': 'futuro', 'planeado': 100, 'real': None, 'pv_horas': 3000, 'ev_horas': None},
            ],
            'evm': {'pv_horas': 750, 'ev_horas': 900, 'total_horas': 3000, 'spi': 1.2, 'sv_horas': 150, 'tono': 'success', 'label': 'Adelantado'},
            'proyeccion_probabilistica': {
                'p10': {'fecha': date(2027, 3, 17)},
                'p50': {'fecha': date(2027, 5, 8)},
                'p90': {'fecha': date(2027, 8, 25)},
            },
        }
        calendario = {
            'configurado': True,
            'posicion_hoy': 35.0,
            'bloques': [
                {'numero': 1, 'etiqueta': 'T1', 'inicio': date(2026, 1, 1), 'fin': date(2026, 3, 31)},
                {'numero': 2, 'etiqueta': 'T2', 'inicio': date(2026, 4, 1), 'fin': date(2026, 6, 30)},
                {'numero': 3, 'etiqueta': 'T3', 'inicio': date(2026, 7, 1), 'fin': date(2026, 9, 30)},
                {'numero': 4, 'etiqueta': 'EP', 'inicio': date(2026, 10, 1), 'fin': date(2027, 3, 31)},
            ],
        }
        svg_data = construir_curva_svg(proyeccion, calendario, hoy=date(2026, 5, 15))
        self.assertIsNotNone(svg_data)
        self.assertTrue(len(svg_data['puntos_datos']) == 4)
        self.assertIsNotNone(svg_data['proyeccion'])
        self.assertIn('poligono_abanico', svg_data['proyeccion'])
        self.assertIn('linea_p50', svg_data['proyeccion'])
        self.assertEqual(svg_data['puntos_datos'][0]['sv_horas'], 150.0)

    def test_construir_fases_progreso_calcula_resumen(self):
        linea = {
            'fases': [
                {
                    'nombre': 'ANÁLISIS',
                    'horas': 240.0,
                    'porcentaje_avance': 85,
                    'resultados_total': 6,
                    'estado_label': 'Al día',
                    'estado_tono': 'success',
                    'etiqueta_trimestre': 'T1–T2',
                    'dias_desfase': 0,
                    'competencias': [
                        {'nombre': 'Tecnología', 'exigible': True},
                        {'nombre': 'Comunicación', 'exigible': False},
                    ],
                }
            ]
        }
        fases = construir_fases_progreso(linea)
        self.assertEqual(len(fases), 1)
        self.assertEqual(fases[0]['icono'], '🔍')
        self.assertEqual(fases[0]['competencias_tecnicas'], 1)
        self.assertEqual(fases[0]['competencias_transversales'], 1)

    def test_normalizar_instructor_unifica_variantes_y_prefijos(self):
        self.assertEqual(normalizar_instructor('1 Instructor'), 'Instructor Técnico')
        self.assertEqual(normalizar_instructor('1 Instructor Técnico'), 'Instructor Técnico')
        self.assertEqual(normalizar_instructor('1 Instructor técnico'), 'Instructor Técnico')
        self.assertEqual(normalizar_instructor('Instructor Tecnico'), 'Instructor Técnico')
        self.assertEqual(normalizar_instructor('1 Instructor Inglés'), 'Instructor de Bilingüismo (Inglés)')
        self.assertEqual(normalizar_instructor('Instructor Comunicación'), 'Instructor de Comunicación')
        self.assertEqual(normalizar_instructor('Instructor Matemáticas'), 'Instructor de Matemáticas')
        self.assertEqual(normalizar_instructor('Instructor actividad física'), 'Instructor de Actividad Física')
        self.assertEqual(normalizar_instructor('Instructor de Derechos fundamentales del trabajo'), 'Instructor de Derechos Fundamentales del Trabajo')
        self.assertEqual(normalizar_instructor('Instructor de Salud ocupacional'), 'Instructor de SST / Salud Ocupacional')
        self.assertEqual(normalizar_instructor('Bienestar al aprendiz'), 'Bienestar al Aprendiz / Inducción')

    def test_construir_heatmap_docente_unifica_filas_y_calcula_totales(self):
        linea = {
            'resultados': [
                {
                    'rap': 'RAP 1',
                    'competencia': 'Desarrollar software',
                    'competencia_tipo': 'tecnica',
                    'instructores': ['1 Instructor Técnico'],
                    'horas_directas': 120.0,
                    'horas_independientes': 24.0,
                    'horas_total': 144.0,
                    'trimestre_inicio': 1,
                    'trimestre_fin': 1,
                },
                {
                    'rap': 'RAP 2',
                    'competencia': 'Desarrollar software',
                    'competencia_tipo': 'tecnica',
                    'instructores': ['1 Instructor técnico'],
                    'horas_directas': 96.0,
                    'horas_independientes': 24.0,
                    'horas_total': 120.0,
                    'trimestre_inicio': 1,
                    'trimestre_fin': 1,
                },
                {
                    'rap': 'RAP 3',
                    'competencia': 'Inglés técnico',
                    'competencia_tipo': 'bilinguismo',
                    'instructores': ['Instructor Inglés'],
                    'horas_directas': 48.0,
                    'horas_independientes': 12.0,
                    'horas_total': 60.0,
                    'trimestre_inicio': 1,
                    'trimestre_fin': 1,
                },
            ]
        }
        calendario = {
            'bloques': [
                {'numero': 1, 'etiqueta': 'T1', 'inicio': date(2026, 1, 1), 'fin': date(2026, 3, 25)},  # 84 días inclusivos = 12 semanas exactas
                {'numero': 2, 'etiqueta': 'T2', 'inicio': date(2026, 4, 1), 'fin': date(2026, 6, 23)},
            ]
        }
        heatmap = construir_heatmap_docente(linea, calendario)
        self.assertIsNotNone(heatmap)
        self.assertEqual(len(heatmap['filas']), 2)  # Instructor Técnico e Instructor de Bilingüismo (Inglés)

        doc_tecnico = next(f for f in heatmap['filas'] if f['instructor'] == 'Instructor Técnico')
        # Total de horas directas unificadas: 120 + 96 = 216
        self.assertEqual(doc_tecnico['total_horas_directas'], 216.0)
        self.assertEqual(doc_tecnico['total_horas_totales'], 264.0)

        # Intensidad semanal en T1 (84 días / 7 = 12 semanas): 216 / 12 = 18.0 h/sem
        celda_t1 = doc_tecnico['celdas'][0]
        self.assertEqual(celda_t1['horas_directas'], 216.0)
        self.assertEqual(celda_t1['intensidad_semanal'], 18.0)
        self.assertEqual(celda_t1['nivel'], 'medio')  # 10..28 es medio

        # Verificar totales de la ficha
        totales_f = heatmap['totales_ficha']
        self.assertEqual(len(totales_f), 2)
        # Total directas ficha T1: 216 + 48 = 264h -> 264 / 12 = 22.0 h/sem
        self.assertEqual(totales_f[0]['horas_directas'], 264.0)
        self.assertEqual(totales_f[0]['intensidad_semanal'], 22.0)


if __name__ == '__main__':
    unittest.main()
