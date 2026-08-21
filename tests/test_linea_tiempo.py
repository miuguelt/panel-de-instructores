import unittest
from datetime import date, datetime
from types import SimpleNamespace

from app.services.calendario_formacion import construir_calendario, sumar_meses
from app.services.diagnostico_planeacion import revisar_datos_planeacion
from app.services.linea_tiempo import construir_linea_tiempo
from app.services.proyeccion_ficha import construir_proyeccion


def _ficha(inicio=date(2025, 7, 25), fin=date(2027, 10, 24), productiva=6):
    return SimpleNamespace(
        fecha_inicio=inicio,
        fecha_fin=fin,
        duracion_productiva_meses=productiva,
    )


def _item(**cambios):
    base = {
        'fase': 'ANÁLISIS',
        'actividad': 'AP01. Contextualizar',
        'competencia': 'Inducción',
        'competencia_tipo': 'tecnica',
        'rap': 'Identificar la dinámica organizacional del SENA.',
        'rap_codigo': '',
        'horas_total': 40,
        'horas_directas': 32,
        'horas_independientes': 8,
        'instructores': ['Bienestar al aprendiz'],
        'trimestres': ['Trimestre 1'],
        'trimestre': 'Trimestre 1',
        'total_juicios': 0,
        'aprobados': 0,
        'aprendices_aprobados': 0,
        'porcentaje_avance': 0,
        'fechas_aprobacion': [],
    }
    base.update(cambios)
    return base


class CalendarioFormacionTestCase(unittest.TestCase):
    def test_suma_meses_respeta_el_ultimo_dia_del_mes(self):
        self.assertEqual(sumar_meses(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(sumar_meses(date(2025, 7, 25), 3), date(2025, 10, 25))

    def test_adso_reparte_veintiun_meses_lectivos_en_siete_trimestres(self):
        calendario = construir_calendario(_ficha(), hoy=date(2026, 8, 18))

        self.assertTrue(calendario['configurado'])
        self.assertEqual(calendario['meses_lectiva'], 21)
        self.assertEqual(calendario['meses_productiva'], 6)
        self.assertEqual(calendario['trimestres_lectivos'], 7)
        self.assertEqual(len(calendario['bloques']), 8)
        self.assertEqual(calendario['bloques'][0]['inicio'], date(2025, 7, 25))
        self.assertEqual(calendario['bloques'][0]['fin'], date(2025, 10, 24))
        self.assertEqual(calendario['bloques'][6]['fin'], date(2027, 4, 23))
        self.assertEqual(calendario['bloques'][7]['etapa'], 'productiva')
        self.assertEqual(calendario['bloques'][7]['inicio'], date(2027, 4, 24))
        self.assertEqual(calendario['bloques'][7]['fin'], date(2027, 10, 24))

    def test_ubica_el_trimestre_en_curso_y_los_dias_de_etapa_lectiva(self):
        calendario = construir_calendario(_ficha(), hoy=date(2026, 8, 18))

        self.assertEqual(calendario['bloque_actual']['numero'], 5)
        self.assertEqual(calendario['bloques'][4]['estado'], 'en_curso')
        self.assertEqual(calendario['bloques'][3]['estado'], 'cumplido')
        self.assertEqual(calendario['bloques'][5]['estado'], 'futuro')
        self.assertEqual(calendario['dias_restantes_lectiva'], (date(2027, 4, 23) - date(2026, 8, 18)).days)
        self.assertGreater(calendario['dias_transcurridos_lectiva'], 0)
        self.assertEqual(calendario['dias_totales_lectiva'], (date(2027, 4, 23) - date(2025, 7, 25)).days + 1)
        self.assertEqual(calendario['porcentaje_lectiva'], 61.1)
        # Cinco bloques de ocho, con algo más de un cuarto del quinto recorrido.
        self.assertGreater(calendario['posicion_hoy'], 50)
        self.assertLess(calendario['posicion_hoy'], 56)

    def test_sin_fechas_no_inventa_calendario(self):
        calendario = construir_calendario(_ficha(inicio=None, fin=None))

        self.assertFalse(calendario['configurado'])
        self.assertEqual(calendario['bloques'], [])
        self.assertIsNone(calendario['bloque_actual'])


class LineaTiempoTestCase(unittest.TestCase):
    def setUp(self):
        self.calendario = construir_calendario(_ficha(), hoy=date(2026, 8, 18))

    def test_hereda_el_trimestre_de_las_actividades_sin_declarar(self):
        items = [
            _item(actividad='AP10. Codificar', fase='EJECUCIÓN', competencia='Construcción',
                  trimestres=['Trimestre 5', 'Trimestre 6']),
            _item(actividad='AP12. Configurar', fase='EVALUACIÓN', competencia='Implantación',
                  trimestres=[], trimestre=''),
        ]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))
        resultados = {item['actividad']: item for item in linea['resultados']}

        self.assertEqual(resultados['AP10. Codificar']['trimestre_inicio'], 5)
        self.assertEqual(resultados['AP10. Codificar']['trimestre_fin'], 6)
        self.assertEqual(resultados['AP10. Codificar']['trimestre_origen'], 'declarado')
        self.assertEqual(resultados['AP12. Configurar']['trimestre_inicio'], 7)
        self.assertEqual(resultados['AP12. Configurar']['trimestre_origen'], 'estimado')

    def test_lleva_la_etapa_practica_al_bloque_productivo(self):
        items = [
            _item(actividad='AP01. Contextualizar', trimestres=['Trimestre 1']),
            _item(actividad='AP13. Demostrar', fase='EVALUACIÓN', competencia='ETAPA PRACTICA',
                  horas_total=0, trimestres=[], trimestre=''),
        ]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))
        practica = [item for item in linea['resultados'] if item['actividad'] == 'AP13. Demostrar'][0]

        self.assertEqual(practica['etapa'], 'productiva')
        self.assertEqual(practica['trimestre_inicio'], 8)

    def test_marca_como_critico_un_resultado_vencido_hace_mas_de_un_trimestre(self):
        items = [
            _item(competencia='Requisitos', trimestres=['Trimestre 1']),
            _item(competencia='Construcción', actividad='AP10. Codificar', fase='EJECUCIÓN',
                  trimestres=['Trimestre 5'], aprendices_aprobados=3, porcentaje_avance=30,
                  fechas_aprobacion=[datetime(2026, 8, 1, 9, 0)] * 3),
        ]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))
        estados = {item['competencia']: item['estado_tiempo'] for item in linea['resultados']}

        self.assertEqual(estados['Requisitos'], 'critico')
        self.assertEqual(estados['Construcción'], 'en_curso')

    def test_cierra_un_resultado_cuando_alcanza_el_umbral_de_aprendices(self):
        fechas = [datetime(2025, 9, day, 9, 0) for day in range(1, 9)]
        items = [_item(trimestres=['Trimestre 1'], aprendices_aprobados=8,
                       porcentaje_avance=80, fechas_aprobacion=fechas)]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))
        resultado = linea['resultados'][0]

        self.assertEqual(resultado['fecha_cierre_real'], date(2025, 9, 8))
        self.assertEqual(resultado['estado_tiempo'], 'a_tiempo')
        self.assertLessEqual(resultado['dias_desfase'], 0)

    def test_agrupa_en_fases_y_competencias_conservando_el_orden_del_documento(self):
        items = [
            _item(fase='ANÁLISIS', competencia='Requisitos', trimestres=['Trimestre 1']),
            _item(fase='ANÁLISIS', competencia='Requisitos', rap='Otro resultado',
                  trimestres=['Trimestre 1']),
            _item(fase='EJECUCIÓN', competencia='Construcción', actividad='AP10. Codificar',
                  trimestres=['Trimestre 5']),
        ]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))

        self.assertEqual([fase['nombre'] for fase in linea['fases']], ['ANÁLISIS', 'EJECUCIÓN'])
        analisis = linea['fases'][0]
        self.assertEqual(len(analisis['competencias']), 1)
        self.assertEqual(analisis['competencias'][0]['resultados_total'], 2)
        self.assertEqual(analisis['trimestre_inicio'], 1)
        self.assertEqual(linea['fases'][1]['trimestre_inicio'], 5)
        self.assertEqual(linea['resumen']['competencias_atrasadas'], 1)


class TransversalesFlexiblesTestCase(unittest.TestCase):
    """Las transversales: se sugieren, no se exigen."""

    def setUp(self):
        self.calendario = construir_calendario(_ficha(), hoy=date(2026, 8, 18))

    def test_una_transversal_vencida_no_cuenta_como_atrasada(self):
        items = [
            _item(competencia='Comunicación', competencia_tipo='transversal', trimestres=['Trimestre 1']),
            _item(competencia='Requisitos', competencia_tipo='tecnica', trimestres=['Trimestre 1']),
        ]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))
        estados = {item['competencia']: item for item in linea['resultados']}

        self.assertEqual(estados['Comunicación']['estado_tiempo'], 'recomendado')
        self.assertFalse(estados['Comunicación']['exigible'])
        self.assertEqual(estados['Comunicación']['dias_desfase'], 0)
        self.assertEqual(estados['Requisitos']['estado_tiempo'], 'critico')
        self.assertTrue(estados['Requisitos']['exigible'])
        self.assertEqual(linea['resumen']['competencias_atrasadas'], 1)

    def test_el_ingles_tambien_se_trata_como_recomendacion(self):
        items = [_item(competencia='Inglés', competencia_tipo='ingles', trimestres=['Trimestre 1'])]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))

        self.assertEqual(linea['resultados'][0]['estado_tiempo'], 'recomendado')
        self.assertEqual(linea['resumen']['competencias_atrasadas'], 0)

    def test_una_transversal_cerrada_tarde_se_reporta_como_cerrada(self):
        fechas = [datetime(2026, 7, day, 9, 0) for day in range(1, 9)]
        items = [_item(competencia='Comunicación', competencia_tipo='transversal',
                       trimestres=['Trimestre 1'], aprendices_aprobados=8,
                       porcentaje_avance=80, fechas_aprobacion=fechas)]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))

        self.assertEqual(linea['resultados'][0]['estado_tiempo'], 'a_tiempo')
        self.assertEqual(linea['resultados'][0]['dias_desfase'], 0)

    def test_las_transversales_no_entran_en_la_proyeccion_del_cierre_lectivo(self):
        fechas = [datetime(2026, 7, 10, 9, 0)] * 10
        items = [
            _item(competencia='Requisitos', competencia_tipo='tecnica', trimestres=['Trimestre 1'],
                  aprendices_aprobados=10, porcentaje_avance=100, fechas_aprobacion=fechas),
            _item(competencia='Comunicación', competencia_tipo='transversal', trimestres=['Trimestre 1']),
        ]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))
        proyeccion = construir_proyeccion(linea['resultados'], self.calendario,
                                          aprendices_meta=10, hoy=date(2026, 8, 18))

        self.assertEqual(proyeccion['pares_totales'], 10)
        self.assertEqual(proyeccion['pares_pendientes'], 0)
        self.assertEqual(proyeccion['estado'], 'completado')
        self.assertEqual(proyeccion['transversales']['resultados'], 1)
        self.assertEqual(proyeccion['transversales']['porcentaje_avance'], 0)


class ProyeccionFichaTestCase(unittest.TestCase):
    def setUp(self):
        self.calendario = construir_calendario(_ficha(), hoy=date(2026, 8, 18))

    def test_proyecta_el_cierre_lectivo_con_el_ritmo_real_de_aprobaciones(self):
        fechas = [datetime(2026, 6, 10, 9, 0)] * 5 + [datetime(2026, 7, 10, 9, 0)] * 5
        items = [
            _item(trimestres=['Trimestre 1'], aprendices_aprobados=10, porcentaje_avance=100,
                  fechas_aprobacion=fechas),
            _item(competencia='Construcción', actividad='AP10. Codificar', fase='EJECUCIÓN',
                  trimestres=['Trimestre 5'], aprendices_aprobados=0),
        ]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))
        proyeccion = construir_proyeccion(linea['resultados'], self.calendario,
                                          aprendices_meta=10, hoy=date(2026, 8, 18))

        self.assertEqual(proyeccion['pares_totales'], 20)
        self.assertEqual(proyeccion['pares_aprobados'], 10)
        self.assertEqual(proyeccion['pares_pendientes'], 10)
        self.assertGreater(proyeccion['ritmo_mensual'], 0)
        self.assertGreater(proyeccion['ritmo_requerido'], 0)
        self.assertIsNotNone(proyeccion['brecha_ritmo'])
        self.assertIsNotNone(proyeccion['fecha_proyectada'])
        self.assertEqual(len(proyeccion['curva']), len(self.calendario['bloques']))
        self.assertEqual(proyeccion['curva'][0]['planeado'], 50)

    def test_sin_aprobaciones_no_proyecta_una_fecha_falsa(self):
        items = [_item(trimestres=['Trimestre 1'])]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))
        proyeccion = construir_proyeccion(linea['resultados'], self.calendario,
                                          aprendices_meta=10, hoy=date(2026, 8, 18))

        self.assertEqual(proyeccion['ritmo_mensual'], 0)
        self.assertIsNone(proyeccion['fecha_proyectada'])
        self.assertEqual(proyeccion['estado'], 'sin_datos')

    def test_el_valor_planeado_se_mide_a_hoy_y_no_al_cierre_del_trimestre(self):
        """PV y EV deben compararse en el mismo instante.

        Si el valor planeado se acumula hasta el fin del trimestre en curso y
        el ganado hasta hoy, el SPI sale inflado y una ficha atrasada aparece
        como adelantada.
        """
        # Un resultado que cierra en T5, sin ninguna aprobación todavía.
        items = [_item(competencia='Construcción', actividad='AP10. Codificar',
                       fase='EJECUCIÓN', trimestres=['Trimestre 5'], horas_total=100)]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10,
                                       hoy=date(2026, 8, 18))
        proyeccion = construir_proyeccion(linea['resultados'], self.calendario,
                                          aprendices_meta=10, hoy=date(2026, 8, 18))

        # Hoy va apenas un 27 % del trimestre 5 (25/07/2026 a 24/10/2026),
        # así que solo esa fracción de las 100 horas está comprometida.
        self.assertLess(proyeccion['evm']['pv_horas'], 100)
        self.assertGreater(proyeccion['evm']['pv_horas'], 0)

    def test_calcula_metricas_evm_y_cfd_con_probabilidad(self):
        fechas = [datetime(2026, 6, 10, 9, 0)] * 8 + [datetime(2026, 7, 10, 9, 0)] * 2
        items = [
            _item(competencia='Construcción', trimestres=['Trimestre 1'], horas_total=100,
                  aprendices_aprobados=10, porcentaje_avance=100, fechas_aprobacion=fechas),
            _item(competencia='Calidad', trimestres=['Trimestre 2'], horas_total=50,
                  aprendices_aprobados=0, porcentaje_avance=0),
        ]
        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))
        proyeccion = construir_proyeccion(linea['resultados'], self.calendario,
                                          aprendices_meta=10, hoy=date(2026, 8, 18))

        self.assertIn('evm', proyeccion)
        self.assertGreater(proyeccion['evm']['total_horas'], 0)
        self.assertGreaterEqual(proyeccion['evm']['spi'], 0)
        self.assertIn('cfd', proyeccion)
        self.assertEqual(len(proyeccion['cfd']), len(self.calendario['bloques']))
        self.assertIn('proyeccion_probabilistica', proyeccion)
        self.assertIn('p10', proyeccion['proyeccion_probabilistica'])
        self.assertIn('p50', proyeccion['proyeccion_probabilistica'])
        self.assertIn('p90', proyeccion['proyeccion_probabilistica'])



class DiagnosticoPlaneacionTestCase(unittest.TestCase):
    def setUp(self):
        self.calendario = construir_calendario(_ficha(), hoy=date(2026, 8, 18))

    def test_reporta_los_resultados_sin_trimestre_declarado(self):
        items = [
            _item(trimestres=['Trimestre 1']),
            _item(actividad='AP12. Configurar', competencia='Implantación', trimestres=[], trimestre=''),
        ]
        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))

        hallazgos = revisar_datos_planeacion(
            linea['resultados'], self.calendario,
            resumen={'resultados_sin_planeacion': 0},
            aprobaciones_previas=0,
        )
        claves = {hallazgo['clave']: hallazgo for hallazgo in hallazgos}

        self.assertIn('trimestre_estimado', claves)
        self.assertIn('1 resultado', claves['trimestre_estimado']['detalle'])

    def test_advierte_cuando_la_planeacion_declara_mas_trimestres_que_la_ficha(self):
        items = [_item(trimestres=['Trimestre 9'])]
        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))

        hallazgos = revisar_datos_planeacion(
            linea['resultados'], self.calendario,
            resumen={'resultados_sin_planeacion': 0},
            aprobaciones_previas=0,
        )

        self.assertIn('duracion_inconsistente', {hallazgo['clave'] for hallazgo in hallazgos})

    def test_sin_hallazgos_devuelve_lista_vacia(self):
        items = [_item(trimestres=['Trimestre 1'])]
        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))

        hallazgos = revisar_datos_planeacion(
            linea['resultados'], self.calendario,
            resumen={'resultados_sin_planeacion': 0},
            aprobaciones_previas=0,
            contraste={'disponible': True, 'horas': {'estado': 'coincide'},
                       'competencias_sin_planear': [], 'resultados_sin_planear': [],
                       'intensidad': {'horas_semana': 32}},
        )

        self.assertEqual(hallazgos, [])

    def test_reclama_el_programa_de_formacion_cuando_no_esta_cargado(self):
        items = [_item(trimestres=['Trimestre 1'])]
        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))

        hallazgos = revisar_datos_planeacion(
            linea['resultados'], self.calendario,
            resumen={'resultados_sin_planeacion': 0},
            aprobaciones_previas=0,
        )

        self.assertIn('sin_programa', {hallazgo['clave'] for hallazgo in hallazgos})


class GanttSecuencialTestCase(unittest.TestCase):
    def setUp(self):
        self.calendario = construir_calendario(_ficha(), hoy=date(2026, 8, 18))

    def test_fase_analisis_inicia_con_induccion_y_encadena_tecnicas_secuenciales(self):
        items = [
            _item(fase='ANÁLISIS', actividad='AP01. Contextualizar', competencia='Análisis de especificación',
                  horas_total=170, trimestres=['Trimestre 1']),
            _item(fase='ANÁLISIS', actividad='AP02. Modelar', competencia='Especificación de requisitos',
                  horas_total=144, trimestres=['Trimestre 1']),
            _item(fase='ANÁLISIS', actividad='AP01. Contextualizar', competencia='Inducción',
                  horas_total=58, trimestres=['Trimestre 1']),
            _item(fase='PLANEACIÓN', actividad='AP04. Diseñar', competencia='Diseño de software',
                  horas_total=120, trimestres=['Trimestre 2']),
        ]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))

        # 1. ANÁLISIS es la primera fase
        self.assertEqual(linea['fases'][0]['nombre'], 'ANÁLISIS')
        analisis_comps = linea['fases'][0]['competencias']
        nombres = [c['nombre'] for c in analisis_comps]

        # 2. Inducción encabeza ANÁLISIS, seguida de Análisis y Especificación
        self.assertEqual(nombres, ['Inducción', 'Análisis de especificación', 'Especificación de requisitos'])

        induccion = analisis_comps[0]
        analisis = analisis_comps[1]
        especificacion = analisis_comps[2]

        # 3. Encadenamiento secuencial sin solapamiento
        self.assertEqual(induccion['fecha_plan_inicio'], self.calendario['bloques'][0]['inicio'])
        self.assertLessEqual(induccion['fecha_plan_fin'], analisis['fecha_plan_inicio'])
        self.assertLessEqual(analisis['fecha_plan_fin'], especificacion['fecha_plan_inicio'])
        self.assertLessEqual(especificacion['fecha_plan_fin'], self.calendario['bloques'][0]['fin'])

        # 4. Proporcionalidad en coordenadas y duración
        self.assertLess(induccion['gantt_width_pct'], especificacion['gantt_width_pct'])
        self.assertLess(especificacion['gantt_width_pct'], analisis['gantt_width_pct'])
        self.assertIn('58h', induccion['etiqueta_duracion'])
        self.assertIn('170h', analisis['etiqueta_duracion'])

    def test_ingles_se_solapa_en_paralelo_con_competencias_tecnicas(self):
        items = [
            _item(fase='ANÁLISIS', actividad='AP01', competencia='Inducción',
                  competencia_tipo='tecnica', horas_total=58, trimestres=['Trimestre 1']),
            _item(fase='ANÁLISIS', actividad='AP01', competencia='Análisis',
                  competencia_tipo='tecnica', horas_total=170, trimestres=['Trimestre 1']),
            _item(fase='ANÁLISIS', actividad='AP01', competencia='Inglés Técnico',
                  competencia_tipo='ingles', horas_total=64, trimestres=['Trimestre 1', 'Trimestre 2']),
        ]

        linea = construir_linea_tiempo(items, self.calendario, aprendices_meta=10, hoy=date(2026, 8, 18))
        analisis_comps = linea['fases'][0]['competencias']
        ingles = [c for c in analisis_comps if c['nombre'] == 'Inglés Técnico'][0]
        induccion = [c for c in analisis_comps if c['nombre'] == 'Inducción'][0]

        # Inglés corre en paralelo abarcando T1 a T2 completo
        self.assertFalse(ingles['exigible'])
        self.assertEqual(ingles['trimestre_inicio'], 1)
        self.assertEqual(ingles['trimestre_fin'], 2)
        self.assertEqual(ingles['fecha_plan_inicio'], self.calendario['bloques'][0]['inicio'])
        self.assertEqual(ingles['fecha_plan_fin'], self.calendario['bloques'][1]['fin'])
        # Inducción solo ocupa su fracción inicial de T1
        self.assertLess(induccion['fecha_plan_fin'], self.calendario['bloques'][0]['fin'])


if __name__ == '__main__':
    unittest.main()

