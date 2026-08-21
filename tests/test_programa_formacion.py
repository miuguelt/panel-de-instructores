import unittest
from tempfile import TemporaryDirectory

from app.services.contraste_programa import contrastar_con_programa
from app.services.programa_formacion import parsear_programa
from tests.apoyo_programa import crear_programa_pdf


def _unidad(**cambios):
    base = {
        'competencia': 'Establecer requisitos de la solución de software de acuerdo con estándares',
        'competencia_tipo': 'tecnica',
        'rap': '220501092 - 1 Caracterizar los procesos de la organización.',
        'rap_codigo': '220501092',
        'horas_total': 144,
    }
    base.update(cambios)
    return base


class ProgramaFormacionTestCase(unittest.TestCase):
    def test_extrae_duraciones_por_etapa_y_competencias_con_su_norma(self):
        with TemporaryDirectory() as carpeta:
            programa = parsear_programa(crear_programa_pdf(carpeta))

        self.assertEqual(programa['metadata']['codigo_programa'], '228118')
        self.assertEqual(programa['metadata']['horas_lectiva'], 1056)
        self.assertEqual(programa['metadata']['horas_productiva'], 864)
        self.assertEqual(programa['metadata']['horas_total'], 1920)
        self.assertEqual(len(programa['competencias']), 3)
        primera = programa['competencias'][0]
        self.assertEqual(primera['codigo_norma'], '220501092')
        self.assertEqual(primera['horas'], 144)
        self.assertEqual(len(primera['resultados']), 2)
        self.assertEqual(primera['tipo'], 'tecnica')

    def test_separa_la_etapa_productiva_de_las_competencias_lectivas(self):
        with TemporaryDirectory() as carpeta:
            programa = parsear_programa(crear_programa_pdf(carpeta))

        productiva = [c for c in programa['competencias'] if c['tipo'] == 'productiva']
        self.assertEqual(len(productiva), 1)
        self.assertEqual(productiva[0]['horas'], 864)
        self.assertEqual(programa['resumen']['horas_lectivas_declaradas'], 192)
        self.assertEqual(programa['resumen']['horas_tecnicas'], 144)

    def test_lee_los_resultados_numerados_con_guion(self):
        competencias = [{
            'codigo': '210201501',
            'nombre': 'Ejercer derechos fundamentales del trabajo',
            'horas': 48,
            'resultados': [
                '01- Reconocer el trabajo como factor de movilidad social.',
                '02- Valorar la importancia de la ciudadanía laboral.',
            ],
        }]
        with TemporaryDirectory() as carpeta:
            programa = parsear_programa(crear_programa_pdf(carpeta, competencias=competencias))

        resultados = programa['competencias'][0]['resultados']
        self.assertEqual(len(resultados), 2)
        self.assertEqual(resultados[0]['numero'], '01')
        self.assertIn('movilidad social', resultados[0]['nombre'])

    def test_rechaza_un_pdf_que_no_es_programa_de_formacion(self):
        with TemporaryDirectory() as carpeta:
            ruta = crear_programa_pdf(carpeta, competencias=[])
            with self.assertRaises(ValueError):
                parsear_programa(ruta)

    def test_extrae_conocimientos_criterios_y_perfil_docente(self):
        with TemporaryDirectory() as carpeta:
            programa = parsear_programa(crear_programa_pdf(carpeta))

        primera = programa['competencias'][0]
        self.assertTrue(len(primera.get('conocimientos_proceso', [])) > 0)
        self.assertIn('IDENTIFICAR PROCESOS DE LA ORGANIZACIÓN', primera['conocimientos_proceso'][0])

        self.assertTrue(len(primera.get('conocimientos_saber', [])) > 0)
        self.assertIn('TEORÍA GENERAL DE SISTEMAS', primera['conocimientos_saber'][0])

        self.assertTrue(len(primera.get('criterios_evaluacion', [])) > 0)
        self.assertIn('IDENTIFICA PROCESOS DE LA ORGANIZACIÓN', primera['criterios_evaluacion'][0])

        perfil = primera.get('perfil_instructor', {})
        self.assertIn('TECNÓLOGO O PROFESIONAL', perfil.get('requisitos_academicos', ''))
        self.assertIn('VEINTICUATRO', perfil.get('experiencia', ''))


class ContrasteProgramaTestCase(unittest.TestCase):
    def setUp(self):
        self.carpeta = TemporaryDirectory()
        self.programa = parsear_programa(crear_programa_pdf(self.carpeta.name))

    def tearDown(self):
        self.carpeta.cleanup()

    def test_compara_las_horas_planeadas_contra_las_del_programa(self):
        unidades = [_unidad(horas_total=100)]

        contraste = contrastar_con_programa(unidades, self.programa, meses_lectivos=6)

        self.assertTrue(contraste['disponible'])
        comparada = contraste['competencias'][0]
        self.assertEqual(comparada['horas_programa'], 144)
        self.assertEqual(comparada['horas_planeacion'], 100)
        self.assertEqual(comparada['diferencia'], -44)

    def test_reporta_las_competencias_del_programa_que_nadie_planeo(self):
        contraste = contrastar_con_programa([_unidad()], self.programa, meses_lectivos=6)

        faltantes = [c['nombre'] for c in contraste['competencias_sin_planear']]
        self.assertTrue(any('COMUNICACIÓN' in f.upper() or 'COMUNICACION' in f.upper() for f in faltantes))
        self.assertNotIn('RESULTADOS DE APRENDIZAJE ETAPA PRACTICA', faltantes)

    def test_calcula_la_intensidad_horaria_que_exige_el_calendario(self):
        contraste = contrastar_con_programa([_unidad()], self.programa, meses_lectivos=6)

        self.assertEqual(contraste['intensidad']['horas_lectivas'], 1056)
        self.assertEqual(contraste['intensidad']['meses'], 6)
        self.assertEqual(contraste['intensidad']['horas_mes'], 176)
        self.assertGreater(contraste['intensidad']['horas_semana'], 0)

    def test_empareja_aunque_la_planeacion_use_otro_nombre_para_la_competencia(self):
        """La planeación nombra las competencias distinto al programa oficial.

        La correspondencia real está en el texto de los resultados de
        aprendizaje, no en el nombre de la competencia.
        """
        unidades = [
            _unidad(competencia='Especificación de requisitos del software',
                    rap='Caracterizar los procesos de la organización.', horas_total=90),
            _unidad(competencia='Especificación de requisitos del software',
                    rap='Recolectar información del software a construir.', horas_total=54),
        ]

        contraste = contrastar_con_programa(unidades, self.programa, meses_lectivos=6)

        sin_planear = {c['codigo_norma'] for c in contraste['competencias_sin_planear']}
        self.assertNotIn('220501092', sin_planear)
        comparada = [c for c in contraste['competencias'] if c['codigo_norma'] == '220501092'][0]
        self.assertEqual(comparada['horas_planeacion'], 144)
        self.assertEqual(comparada['resultados_planeacion'], 2)
        self.assertEqual(comparada['estado'], 'coincide')

    def test_suma_las_variantes_de_nombre_de_una_misma_competencia(self):
        """La planeación reparte una competencia en dos rótulos distintos.

        Si el contraste toma solo uno, reporta horas faltantes que no existen.
        """
        unidades = [
            _unidad(competencia='Especificación de requisitos del software',
                    rap='Caracterizar los procesos de la organización.', horas_total=100),
            _unidad(competencia='Especificación de requisitos del software (220501092 - Establecer requisitos)',
                    rap='Recolectar información del software a construir.', horas_total=44),
        ]

        contraste = contrastar_con_programa(unidades, self.programa, meses_lectivos=6)
        comparada = [c for c in contraste['competencias'] if c['codigo_norma'] == '220501092'][0]

        self.assertEqual(comparada['horas_planeacion'], 144)
        self.assertEqual(comparada['estado'], 'coincide')
        self.assertEqual(comparada['resultados_planeacion'], 2)
        self.assertIn('Especificación de requisitos del software', contraste['mapa_competencias'])
        self.assertIn('Especificación de requisitos del software (220501092 - Establecer requisitos)',
                      contraste['mapa_competencias'])

    def test_un_nombre_de_una_sola_palabra_no_captura_rotulos_ajenos(self):
        """El programa titula competencias como "FISICA", "TIC" o "INGLES".

        Una sola palabra en común no basta para dar por emparejado un rótulo:
        si bastara, "FISICA" se quedaría con la competencia de hábitos de vida
        saludable solo porque menciona actividad física.
        """
        programa = {
            'metadata': {'horas_lectiva': 96, 'horas_total': 96, 'horas_productiva': 0},
            'competencias': [
                {'codigo_norma': '220201501', 'nombre': 'FISICA',
                 'norma': 'Aplicación de conocimientos de las ciencias naturales',
                 'horas': 48, 'tipo': 'transversal', 'resultados': []},
                {'codigo_norma': '230101507', 'nombre': 'ACTIVIDAD FÍSICA Y HÁBITOS DE VIDA SALUDABLE',
                 'norma': 'Generar hábitos saludables de vida mediante la aplicación de programas de actividad física',
                 'horas': 48, 'tipo': 'transversal', 'resultados': []},
            ],
            'resumen': {'horas_lectivas_declaradas': 96, 'horas_tecnicas': 0,
                        'horas_transversales': 96, 'horas_ingles': 0},
        }
        unidades = [
            _unidad(competencia='Generación de Hábitos saludables de vida mediante la aplicación de programas de actividad física',
                    competencia_tipo='transversal', rap='Aplicar programas de actividad física.',
                    rap_codigo='', horas_total=48),
        ]

        contraste = contrastar_con_programa(unidades, programa, meses_lectivos=6)
        por_codigo = {c['codigo_norma']: c for c in contraste['competencias']}

        self.assertEqual(por_codigo['230101507']['horas_planeacion'], 48)
        self.assertNotIn('220201501', por_codigo)

    def test_la_etapa_practica_no_se_asigna_a_una_competencia_lectiva(self):
        unidades = [
            _unidad(competencia='ETAPA PRACTICA', competencia_tipo='transversal',
                    rap='Aplicar en la resolución de problemas reales del sector productivo.',
                    rap_codigo='', horas_total=0),
        ]

        contraste = contrastar_con_programa(unidades, self.programa, meses_lectivos=6)

        for fila in contraste['competencias']:
            self.assertNotIn('ETAPA PRACTICA', fila['rotulos_planeacion'])

    def test_expone_el_mapa_entre_nombres_de_planeacion_y_competencia_oficial(self):
        unidades = [
            _unidad(competencia='Especificación de requisitos del software',
                    rap='Caracterizar los procesos de la organización.', horas_total=144),
        ]

        contraste = contrastar_con_programa(unidades, self.programa, meses_lectivos=6)
        mapa = contraste['mapa_competencias']

        self.assertIn('Especificación de requisitos del software', mapa)
        self.assertEqual(mapa['Especificación de requisitos del software']['codigo_norma'],
                         '220501092')

    def test_el_catalogo_pedagogico_resuelve_el_nombre_de_la_planeacion(self):
        """La ficha pedagógica debe abrir desde el nombre corto de la planeación."""
        from app.services.catalogo_pedagogico import construir_catalogo as _catalogo_pedagogico

        # El programa la titula "COMUNICACIÓN" y la planeación la escribe con el
        # nombre largo de la norma: por nombre no se encuentran.
        nombre_plan = 'Desarrollar procesos de comunicación eficaces y efectivos, teniendo en cuenta situaciones de orden social'
        unidades = [
            _unidad(competencia=nombre_plan, competencia_tipo='transversal',
                    rap='Interpretar el contexto comunicativo.', rap_codigo='',
                    horas_total=48),
        ]
        contraste = contrastar_con_programa(unidades, self.programa, meses_lectivos=6)
        linea = {'competencias': [{
            'nombre': nombre_plan, 'exigible': False, 'horas': 48, 'porcentaje_avance': 40,
        }]}

        catalogo = _catalogo_pedagogico(linea, contraste)
        entrada = catalogo.get(nombre_plan)

        self.assertIsNotNone(entrada)
        self.assertEqual(entrada['codigo_norma'], '240201524')
        self.assertTrue(entrada['conocimientos_proceso'])
        self.assertTrue(entrada['criterios_evaluacion'])
        self.assertEqual(entrada['horas_planeadas'], 48)

    def test_sin_programa_devuelve_un_contraste_no_disponible(self):
        contraste = contrastar_con_programa([_unidad()], None, meses_lectivos=6)

        self.assertFalse(contraste['disponible'])
        self.assertEqual(contraste['competencias'], [])

    def test_empareja_competencia_con_prefijo_enrique_low_murtra(self):
        """Competencias con prefijos institucionales se emparejan con la norma oficial."""
        from app.services.catalogo_pedagogico import construir_catalogo as _catalogo_pedagogico
        
        programa = {
            'metadata': {'horas_lectiva': 48, 'horas_total': 48, 'horas_productiva': 0},
            'competencias': [
                {
                    'codigo_norma': '240201526',
                    'nombre': 'ETICA Y CULTURA DE PAZ',
                    'norma': 'Interactuar en el contexto productivo y social de acuerdo con principios éticos para la construcción de una cultura de paz',
                    'horas': 48,
                    'tipo': 'transversal',
                    'resultados': [
                        {'numero': '01', 'nombre': 'Promover mi dignidad y la del otro a partir de los principios y valores éticos.'},
                        {'numero': '02', 'nombre': 'Establecer relaciones interpersonales armónicas.'},
                    ],
                    'conocimientos_saber': ['Dignidad humana', 'Principios y valores éticos universales'],
                    'conocimientos_proceso': ['Reconocer al otro como interlocutor válido'],
                    'criterios_evaluacion': ['Identifica los principios éticos en su actuar cotidiano'],
                    'perfil_instructor': {'requisitos_academicos': 'Profesional en áreas sociales o humanidades'},
                },
            ],
            'resumen': {'horas_lectivas_declaradas': 48, 'horas_tecnicas': 0, 'horas_transversales': 48, 'horas_ingles': 0},
        }

        nombre_rotulo_plan = 'Enrique Low Murtra-Interactuar en el contexto productivo y social de acuerdo con principios éticos para la construcción de una cultura de paz - ETICA Y CULTURA PAZ'
        unidades = [
            _unidad(
                competencia=nombre_rotulo_plan,
                competencia_tipo='transversal',
                rap='Promover mi dignidad y la del otro a partir de los principios y valores éticos.',
                rap_codigo='240201526',
                horas_total=48,
            ),
        ]

        contraste = contrastar_con_programa(unidades, programa, meses_lectivos=6)
        self.assertTrue(contraste['disponible'])
        self.assertEqual(len(contraste['competencias']), 1)
        self.assertEqual(contraste['competencias'][0]['codigo_norma'], '240201526')
        self.assertEqual(contraste['competencias'][0]['horas_planeacion'], 48)

        linea = {'competencias': [{
            'nombre': nombre_rotulo_plan, 'exigible': False, 'horas': 48, 'porcentaje_avance': 100,
        }]}
        catalogo = _catalogo_pedagogico(linea, contraste)
        entrada = catalogo.get(nombre_rotulo_plan)
        self.assertIsNotNone(entrada)
        self.assertEqual(entrada['codigo_norma'], '240201526')
        self.assertIn('Dignidad humana', entrada['conocimientos_saber'])
        self.assertIn('Reconocer al otro como interlocutor válido', entrada['conocimientos_proceso'])
        self.assertIn('Identifica los principios éticos en su actuar cotidiano', entrada['criterios_evaluacion'])


if __name__ == '__main__':
    unittest.main()
