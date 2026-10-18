import json
import unittest
from datetime import date, timedelta
from app import create_app, db
from app.models import Ficha, Instructor, FichaInstructor, JuicioEvaluativo, Aprendiz
from app.models.archivo_ficha import ArchivoFichaVersion, TIPO_PLANEACION
from app.models.juicio import FichaCompetenciaProgramacion


class ProgramacionCompetenciasTestCase(unittest.TestCase):
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

        # Instructores
        self.inst1 = Instructor(nombre='Instructor Uno', correo='inst1@sena.edu.co')
        self.inst1.set_password('pass123')
        self.inst2 = Instructor(nombre='Instructor Dos', correo='inst2@sena.edu.co')
        self.inst2.set_password('pass123')
        self.inst_ajeno = Instructor(nombre='Instructor Ajeno', correo='ajeno@sena.edu.co')
        self.inst_ajeno.set_password('pass123')
        db.session.add_all([self.inst1, self.inst2, self.inst_ajeno])
        db.session.commit()

        # Ficha con fechas definidas
        self.ficha = Ficha(
            codigo=222333,
            nombre_programa='ANALISIS Y DESARROLLO DE SOFTWARE',
            instructor_id=self.inst1.id,
            fecha_inicio=date(2025, 8, 1),
            fecha_fin=date(2027, 4, 30),
            duracion_productiva_meses=6,
        )
        db.session.add(self.ficha)
        db.session.commit()

        # Asociar inst2 a ficha
        fi = FichaInstructor(ficha_id=self.ficha.id, instructor_id=self.inst2.id)
        db.session.add(fi)
        db.session.commit()

        # Crear aprendiz y juicios de prueba
        self.aprendiz = Aprendiz(
            documento='1001',
            nombre='Carlos',
            apellidos='Pérez',
            correo='carlos@sena.edu.co',
            ficha_id=self.ficha.id,
            estado='EN_FORMACION',
        )
        db.session.add(self.aprendiz)
        db.session.commit()

        self.j1 = JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            competencia='38362 - Diseñar la solución de software',
            tipo_competencia='tecnica',
            resultado_aprendizaje='RAP 1 Especificación',
            juicio='APROBADO',
            fecha_juicio=date(2025, 8, 20),
        )
        self.j2 = JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            competencia='38362 - Diseñar la solución de software',
            tipo_competencia='tecnica',
            resultado_aprendizaje='RAP 2 Modelado',
            juicio='POR EVALUAR',
        )
        db.session.add_all([self.j1, self.j2])
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _autenticar(self, instructor):
        from flask import g
        g.pop('_login_user', None)
        with self.client.session_transaction() as sesion:
            sesion['_user_id'] = str(instructor.id)
            sesion['_fresh'] = True

    def test_modelo_ficha_competencia_programacion_persistencia(self):
        """Verifica que se pueda persistir y consultar la programación de una competencia."""
        prog = FichaCompetenciaProgramacion(
            ficha_id=self.ficha.id,
            competencia='38362 - Diseñar la solución de software',
            fecha_inicio=date(2025, 9, 1),
            fecha_fin=date(2025, 10, 15),
            instructor_id=self.inst1.id,
        )
        db.session.add(prog)
        db.session.commit()

        recuperado = FichaCompetenciaProgramacion.query.filter_by(
            ficha_id=self.ficha.id,
            competencia='38362 - Diseñar la solución de software'
        ).first()

        self.assertIsNotNone(recuperado)
        self.assertEqual(recuperado.fecha_inicio, date(2025, 9, 1))
        self.assertEqual(recuperado.fecha_fin, date(2025, 10, 15))
        self.assertEqual(recuperado.instructor_id, self.inst1.id)

    def test_servicio_distribucion_temporal_raps(self):
        """Verifica que los RAPs se distribuyan secuencialmente en el periodo de la competencia."""
        from app.services.programacion_competencias import distribuir_raps_en_periodo

        raps = ['RAP 1 Requisitos', 'RAP 2 Casos de Uso', 'RAP 3 Diagramas', 'RAP 4 Prototipo']
        inicio = date(2025, 9, 1)
        fin = date(2025, 9, 30)

        distribucion = distribuir_raps_en_periodo(raps, inicio, fin)

        self.assertEqual(len(distribucion), 4)
        self.assertEqual(distribucion[0]['fecha_inicio'], inicio)
        self.assertEqual(distribucion[-1]['fecha_fin'], fin)

        for i in range(len(distribucion) - 1):
            self.assertLessEqual(distribucion[i]['fecha_fin'], distribucion[i + 1]['fecha_inicio'])
            self.assertLessEqual(distribucion[i]['fecha_inicio'], distribucion[i]['fecha_fin'])

    def test_distribuir_raps_casos_borde(self):
        """Verifica casos borde como lista vacía, fechas nulas o rango invertido."""
        from app.services.programacion_competencias import distribuir_raps_en_periodo

        self.assertEqual(distribuir_raps_en_periodo([], date(2025, 1, 1), date(2025, 1, 31)), [])

        raps = ['RAP 1', 'RAP 2']
        res_nulo = distribuir_raps_en_periodo(raps, None, date(2025, 1, 31))
        self.assertEqual(len(res_nulo), 2)
        self.assertIsNone(res_nulo[0]['fecha_inicio'])

        res_invertido = distribuir_raps_en_periodo(raps, date(2025, 2, 1), date(2025, 1, 1))
        self.assertEqual(len(res_invertido), 2)
        self.assertIsNone(res_invertido[0]['fecha_inicio'])

        # Con pesos de horas
        pesos = {'RAP 1': 40.0, 'RAP 2': 80.0}
        res_pesos = distribuir_raps_en_periodo(raps, date(2025, 1, 1), date(2025, 1, 31), pesos_horas=pesos)
        self.assertEqual(len(res_pesos), 2)
        self.assertLess(res_pesos[0]['dias'], res_pesos[1]['dias'])

    def test_guardar_y_limpiar_programacion_competencia(self):
        """Verifica las funciones de guardar y limpiar programación en el servicio."""
        from app.services.programacion_competencias import (
            guardar_programacion_competencia,
            limpiar_programacion_competencia,
            obtener_programacion_competencias,
        )

        comp = '38368 - DESARROLLAR LA SOLUCIÓN'
        f_ini = date(2025, 10, 1)
        f_fin = date(2025, 12, 15)

        prog = guardar_programacion_competencia(self.ficha.id, comp, f_ini, f_fin, self.inst1.id)
        self.assertIsNotNone(prog)
        self.assertEqual(prog.fecha_inicio, f_ini)
        self.assertEqual(prog.fecha_fin, f_fin)

        mapa = obtener_programacion_competencias(self.ficha.id)
        self.assertIn(comp, mapa)
        self.assertEqual(mapa[comp]['fecha_inicio'], f_ini)

        # Actualizar existente
        f_fin_nueva = date(2025, 12, 20)
        prog_act = guardar_programacion_competencia(self.ficha.id, comp, f_ini, f_fin_nueva, self.inst2.id)
        self.assertEqual(prog_act.fecha_fin, f_fin_nueva)
        self.assertEqual(prog_act.instructor_id, self.inst2.id)

        # Limpiar
        limpiado = limpiar_programacion_competencia(self.ficha.id, comp)
        self.assertTrue(limpiado)
        mapa_post = obtener_programacion_competencias(self.ficha.id)
        self.assertNotIn(comp, mapa_post)

        # Limpiar inexistente devuelve False
        self.assertFalse(limpiar_programacion_competencia(self.ficha.id, 'NO EXISTE'))

    def test_calcular_fechas_competencias_con_planeacion(self):
        """Verifica el cruce con la planeación pedagógica cargada en la ficha."""
        from app.services.programacion_competencias import calcular_fechas_competencias_y_raps

        # Agregar juicio sin competencia para validar condición de robustez
        j_sin_comp = JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            competencia='',
            tipo_competencia='tecnica',
            resultado_aprendizaje='RAP 1 Especificación',
            juicio='APROBADO',
        )
        db.session.add(j_sin_comp)
        db.session.commit()

        # Crear versión de planeación con unidades en orden inverso para ejercitar ini < entry['inicio']
        version_plan = ArchivoFichaVersion(
            ficha_id=self.ficha.id,
            instructor_id=self.inst1.id,
            tipo=TIPO_PLANEACION,
            version=1,
            nombre_archivo='planeacion.xlsx',
            ruta_archivo='fichas/222333/planeacion.xlsx',
            estado='procesado',
            contenido_extraido_json={
                'unidades': [
                    {
                        'competencia': 'Diseñar la solución de software',
                        'rap': 'RAP 2 Modelado',
                        'horas_total': 48.0,
                    },
                    {
                        'competencia': 'Diseñar la solución de software',
                        'rap': 'RAP 1 Especificación',
                        'horas_total': 48.0,
                    }
                ]
            }
        )
        db.session.add(version_plan)
        db.session.commit()

        comps_summary = [{
            'nombre': '38362 - Diseñar la solución de software',
            'detalles': [
                {'rap': 'RAP 1 Especificación'},
                {'rap': 'RAP 2 Modelado'},
            ]
        }]

        enriquecidas = calcular_fechas_competencias_y_raps(self.ficha, comps_summary)
        comp = enriquecidas[0]
        self.assertIsNotNone(comp['fecha_inicio'])
        self.assertIsNotNone(comp['fecha_fin'])
        self.assertFalse(comp['es_programacion_manual'])
        self.assertIn('raps_distribucion', comp)
        self.assertEqual(len(comp['raps_distribucion']), 2)

    def test_endpoint_programar_competencia_api(self):
        """Verifica la API POST para que el instructor defina las fechas de la competencia."""
        self._autenticar(self.inst1)

        comp = '38392 - Establecer requisitos'
        resp = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/programar',
            json={
                'competencia': comp,
                'fecha_inicio': '2025-08-15',
                'fecha_fin': '2025-09-30',
            }
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['fecha_inicio'], '2025-08-15')
        self.assertEqual(data['fecha_fin'], '2025-09-30')
        self.assertTrue(data['es_manual'])
        self.assertIn('raps_tiempo', data)

        # Validación: fin menor a inicio
        resp_invalido = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/programar',
            json={
                'competencia': comp,
                'fecha_inicio': '2025-10-01',
                'fecha_fin': '2025-09-01',
            }
        )
        self.assertEqual(resp_invalido.status_code, 400)
        self.assertFalse(resp_invalido.get_json()['success'])

        # Validación: competencia vacía
        resp_vacia = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/programar',
            json={'competencia': '   '}
        )
        self.assertEqual(resp_vacia.status_code, 400)

        # Probar limpiar programación
        resp_limpiar = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/programar',
            json={
                'competencia': comp,
                'limpiar': True,
            }
        )
        self.assertEqual(resp_limpiar.status_code, 200)
        data_limpio = resp_limpiar.get_json()
        self.assertTrue(data_limpio['success'])
        self.assertFalse(data_limpio['es_manual'])

    def test_permisos_endpoint_programar_competencia(self):
        """Verifica restricciones de acceso y permisos."""
        # Sin autenticar
        resp_anon = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/programar',
            json={'competencia': '38362 - Diseñar'}
        )
        self.assertEqual(resp_anon.status_code, 302)

        # Instructor ajeno sin permisos en la ficha
        self._autenticar(self.inst_ajeno)
        resp_ajeno = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/programar',
            json={'competencia': '38362 - Diseñar'}
        )
        self.assertEqual(resp_ajeno.status_code, 403)

    def test_vista_juicios_renderiza_fechas_y_controles(self):
        """Verifica que la página de juicios renderice las fechas y elementos interactivos."""
        self._autenticar(self.inst1)

        # Programar una competencia previamente
        prog = FichaCompetenciaProgramacion(
            ficha_id=self.ficha.id,
            competencia='38362 - Diseñar la solución de software',
            fecha_inicio=date(2025, 9, 1),
            fecha_fin=date(2025, 10, 15),
            instructor_id=self.inst1.id,
        )
        db.session.add(prog)
        db.session.commit()

        resp = self.client.get(f'/instructor/fichas/{self.ficha.id}/juicios')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Verificar presencia de elementos en HTML
        self.assertIn('Programación de fechas de la competencia', html)
        self.assertIn('modal-input-fecha-inicio', html)
        self.assertIn('modal-input-fecha-fin', html)
        self.assertIn('comp-fechas-row', html)
        self.assertIn('01/09/2025', html)
        self.assertIn('15/10/2025', html)
        self.assertIn('raps_distribucion_mapa', html)

    def test_parsear_fecha_formatos_y_tipos(self):
        """Verifica el parsing de datetime, date, formatos varios e inválidos."""
        from datetime import datetime
        from app.services.programacion_competencias import _parsear_fecha

        dt = datetime(2025, 9, 15, 10, 30)
        self.assertEqual(_parsear_fecha(dt), date(2025, 9, 15))
        self.assertEqual(_parsear_fecha('15-09-2025'), date(2025, 9, 15))
        self.assertIsNone(_parsear_fecha('no-es-fecha'))
        self.assertIsNone(_parsear_fecha(''))

    def test_guardar_programacion_fechas_invalidas_lanza_error(self):
        """Verifica que fechas inconsistentes lancen ValueError en el servicio."""
        from app.services.programacion_competencias import guardar_programacion_competencia

        with self.assertRaises(ValueError):
            guardar_programacion_competencia(
                self.ficha.id,
                '38362 - Diseñar',
                date(2025, 10, 1),
                date(2025, 9, 1),
                self.inst1.id
            )

    def test_calcular_fechas_competencias_casos_especiales(self):
        """Verifica cálculo sin resumen de competencias o en fichas sin fechas lectivas."""
        from app.services.programacion_competencias import calcular_fechas_competencias_y_raps

        # Lista vacía
        self.assertEqual(calcular_fechas_competencias_y_raps(self.ficha, []), [])

        # Ficha sin fechas configuradas
        ficha_sin_fechas = Ficha(
            codigo=999999,
            nombre_programa='SIN FECHAS',
            instructor_id=self.inst1.id,
        )
        db.session.add(ficha_sin_fechas)
        db.session.commit()

        comps = [{'nombre': 'Comp 1', 'detalles': [{'rap': 'RAP 1'}]}]
        res = calcular_fechas_competencias_y_raps(ficha_sin_fechas, comps)
        self.assertIsNone(res[0]['fecha_inicio'])
        self.assertIsNone(res[0]['fecha_fin'])

    def test_modelo_propiedades_calculadas_y_observacion(self):
        """Verifica las propiedades calculadas y el campo observación de FichaCompetenciaProgramacion."""
        prog = FichaCompetenciaProgramacion(
            ficha_id=self.ficha.id,
            competencia='38362 - Diseñar',
            fecha_inicio=date(2025, 8, 1),
            fecha_fin=date(2025, 8, 14),
            instructor_id=self.inst1.id,
            observacion='Programación oficial concertada con el equipo técnico',
        )
        db.session.add(prog)
        db.session.commit()

        # Rango válido: 14 días (del 1 al 14 inclusive)
        self.assertEqual(prog.dias_duracion, 14)
        self.assertEqual(prog.semanas, 2.0)
        self.assertTrue(prog.esta_definida)
        self.assertEqual(prog.observacion, 'Programación oficial concertada con el equipo técnico')

        # Sin fecha_fin
        prog.fecha_fin = None
        self.assertIsNone(prog.dias_duracion)
        self.assertIsNone(prog.semanas)
        self.assertFalse(prog.esta_definida)

        # Sin fechas
        prog.fecha_inicio = None
        self.assertIsNone(prog.dias_duracion)
        self.assertIsNone(prog.semanas)
        self.assertFalse(prog.esta_definida)

        # Fechas incoherentes
        prog.fecha_inicio = date(2025, 8, 20)
        prog.fecha_fin = date(2025, 8, 10)
        self.assertIsNone(prog.dias_duracion)

    def test_archivo_ficha_version_metadata_dict_y_obtener_version_activa(self):
        """Verifica metadata_dict seguro y la recuperación de la versión activa de un archivo."""
        v1 = ArchivoFichaVersion(
            ficha_id=self.ficha.id,
            instructor_id=self.inst1.id,
            tipo=TIPO_PLANEACION,
            version=1,
            nombre_archivo='planeacion_v1.xlsx',
            ruta_archivo='/tmp/v1.xlsx',
            estado='procesado',
            metadata_json='{"total_horas": 120, "fase": "Analisis"}',
        )
        v2 = ArchivoFichaVersion(
            ficha_id=self.ficha.id,
            instructor_id=self.inst1.id,
            tipo=TIPO_PLANEACION,
            version=2,
            nombre_archivo='planeacion_v2.xlsx',
            ruta_archivo='/tmp/v2.xlsx',
            estado='error',
            metadata_json='no-es-json-valido',
        )
        v3 = ArchivoFichaVersion(
            ficha_id=self.ficha.id,
            instructor_id=self.inst1.id,
            tipo=TIPO_PLANEACION,
            version=3,
            nombre_archivo='planeacion_v3.xlsx',
            ruta_archivo='/tmp/v3.xlsx',
            estado='procesado',
            metadata_json=None,
        )
        db.session.add_all([v1, v2, v3])
        db.session.commit()

        # metadata_dict
        self.assertEqual(v1.metadata_dict, {'total_horas': 120, 'fase': 'Analisis'})
        self.assertEqual(v2.metadata_dict, {})
        self.assertEqual(v3.metadata_dict, {})

        # Caso en que metadata_json ya es un diccionario (ej. asignado en memoria o dialecto nativo)
        v_temp = ArchivoFichaVersion()
        v_temp.metadata_json = {'horas': 40}
        self.assertEqual(v_temp.metadata_dict, {'horas': 40})

        # obtener_version_activa debe retornar la v3 (la más reciente con estado='procesado')
        activa = ArchivoFichaVersion.obtener_version_activa(self.ficha.id, TIPO_PLANEACION)
        self.assertIsNotNone(activa)
        self.assertEqual(activa.version, 3)
        self.assertEqual(activa.nombre_archivo, 'planeacion_v3.xlsx')

        # Para un tipo que no tiene versiones
        sin_activa = ArchivoFichaVersion.obtener_version_activa(self.ficha.id, 'tipo_inexistente')
        self.assertIsNone(sin_activa)

    def test_auditar_duracion_programa_completo_y_casos_borde(self):
        """Verifica la auditoría de duración del programa: 21 meses lectivos, 6 productivos y casos borde."""
        from app.services.programacion_competencias import auditar_duracion_programa

        # Caso 1: Ficha estándar ADSO (21 meses lectivos: 25/07/2025 al 23/04/2027, fin total 24/10/2027)
        ficha_adso = Ficha(
            codigo=3235642,
            nombre_programa='ANALISIS Y DESARROLLO DE SOFTWARE',
            instructor_id=self.inst1.id,
            fecha_inicio=date(2025, 7, 25),
            fecha_fin=date(2027, 10, 24),
            duracion_productiva_meses=6,
        )
        db.session.add(ficha_adso)
        db.session.commit()

        auditoria = auditar_duracion_programa(ficha_adso)
        self.assertTrue(auditoria['configurado'])
        self.assertTrue(auditoria['cumple_21_meses'])
        self.assertAlmostEqual(auditoria['meses_lectivos'], 21.0, delta=0.5)
        self.assertAlmostEqual(auditoria['meses_productivos'], 6.0, delta=0.2)
        self.assertAlmostEqual(auditoria['meses_totales'], 27.0, delta=0.5)
        self.assertEqual(auditoria['inicio_lectiva_texto'], '25/07/2025')
        self.assertEqual(auditoria['fin_lectiva_texto'], '23/04/2027')
        self.assertEqual(auditoria['inicio_productiva_texto'], '24/04/2027')
        self.assertEqual(auditoria['fin_productiva_texto'], '24/10/2027')
        self.assertIn('21', auditoria['resumen_texto'])
        self.assertIn('Etapa lectiva', auditoria['resumen_texto'])

        # Caso 2: Ficha sin fechas
        ficha_incompleta = Ficha(
            codigo=999888,
            nombre_programa='PROGRAMA SIN FECHAS',
            instructor_id=self.inst1.id,
            fecha_inicio=None,
            fecha_fin=None,
        )
        db.session.add(ficha_incompleta)
        db.session.commit()

        aud_inc = auditar_duracion_programa(ficha_incompleta)
        self.assertFalse(aud_inc['configurado'])
        self.assertFalse(aud_inc['cumple_21_meses'])
        self.assertEqual(aud_inc['meses_lectivos'], 0.0)
        self.assertEqual(aud_inc['resumen_texto'], 'Fechas de formación incompletas o no configuradas.')

        # Caso 3: Ficha con duración menor a 21 meses (ej. tecnólogo corto de 12 meses lectivos)
        ficha_corta = Ficha(
            codigo=555444,
            nombre_programa='TECNICO CORTO',
            instructor_id=self.inst1.id,
            fecha_inicio=date(2025, 1, 1),
            fecha_fin=date(2026, 6, 30),
            duracion_productiva_meses=6,
        )
        db.session.add(ficha_corta)
        db.session.commit()

        aud_corta = auditar_duracion_programa(ficha_corta)
        self.assertTrue(aud_corta['configurado'])
        self.assertFalse(aud_corta['cumple_21_meses'])
        self.assertLess(aud_corta['meses_lectivos'], 19.5)

    def test_calcular_fechas_competencias_horas_y_distribucion_21_meses(self):
        """Verifica que las competencias reciban horas oficiales/planeadas, los RAPs sus horas y la etapa lectiva respete 21 meses."""
        from app.models.archivo_ficha import TIPO_PROGRAMA
        from app.services.programacion_competencias import calcular_fechas_competencias_y_raps

        # Ficha configurada con 21 meses lectivos + 6 productivos
        ficha_prog = Ficha(
            codigo=777888,
            nombre_programa='ANALISIS Y DESARROLLO DE SOFTWARE',
            instructor_id=self.inst1.id,
            fecha_inicio=date(2025, 7, 25),
            fecha_fin=date(2027, 10, 24),
            duracion_productiva_meses=6,
        )
        db.session.add(ficha_prog)
        db.session.commit()

        # Versión de programa curricular con horas oficiales
        v_prog = ArchivoFichaVersion(
            ficha_id=ficha_prog.id,
            instructor_id=self.inst1.id,
            tipo=TIPO_PROGRAMA,
            version=1,
            nombre_archivo='programa.pdf',
            ruta_archivo='fichas/777888/programa.pdf',
            estado='procesado',
            contenido_extraido_json={
                'metadata': {'horas_productiva': 864.0},
                'competencias': [
                    {
                        'codigo_norma': '220501096',
                        'nombre': 'Desarrollar la solución de software',
                        'horas': 384.0,
                    }
                ]
            }
        )

        # Versión de planeación pedagógica con horas por RAP
        v_plan = ArchivoFichaVersion(
            ficha_id=ficha_prog.id,
            instructor_id=self.inst1.id,
            tipo=TIPO_PLANEACION,
            version=1,
            nombre_archivo='planeacion.xlsx',
            ruta_archivo='fichas/777888/planeacion.xlsx',
            estado='procesado',
            contenido_extraido_json={
                'unidades': [
                    {
                        'competencia': '220501096 - Desarrollar la solución de software',
                        'rap': 'Construir la interfaz de usuario',
                        'horas_total': 120.0,
                        'fecha_inicio_estimada': '2025-08-01',
                        'fecha_fin_estimada': '2025-09-30',
                    },
                    {
                        'competencia': '220501096 - Desarrollar la solución de software',
                        'rap': 'Codificar el backend del sistema',
                        'horas_total': 264.0,
                        'fecha_inicio_estimada': '2025-10-01',
                        'fecha_fin_estimada': '2025-12-15',
                    }
                ]
            }
        )
        db.session.add_all([v_prog, v_plan])
        db.session.commit()

        resumen_comps = [
            {
                'nombre': '220501096 - Desarrollar la solución de software',
                'detalles': [
                    {'rap': 'Construir la interfaz de usuario'},
                    {'rap': 'Codificar el backend del sistema'},
                ]
            },
            {
                'nombre': '2 - RESULTADOS DE APRENDIZAJE ETAPA PRACTICA',
                'detalles': [
                    {'rap': 'APLICAR EN LA RESOLUCIÓN DE PROBLEMAS REALES DEL SECTOR PRODUCTIVO'},
                ]
            }
        ]

        resultado = calcular_fechas_competencias_y_raps(ficha_prog, resumen_comps)
        self.assertEqual(len(resultado), 2)

        # Competencia Lectiva
        comp_lect = resultado[0]
        self.assertEqual(comp_lect['horas'], 384.0)
        self.assertEqual(comp_lect['horas_programa'], 384.0)
        self.assertFalse(comp_lect['es_productiva'])
        self.assertIsNotNone(comp_lect['fecha_inicio'])
        self.assertIsNotNone(comp_lect['fecha_fin'])
        # Las fechas lectivas no deben exceder el fin de etapa lectiva (abril 2027)
        self.assertLessEqual(comp_lect['fecha_fin'], '2027-04-23')

        # Distribución de RAPs con horas específicas
        raps_dist = comp_lect['raps_distribucion']
        self.assertEqual(len(raps_dist), 2)
        rap_ui = next(r for r in raps_dist if 'interfaz' in r['rap'])
        rap_be = next(r for r in raps_dist if 'backend' in r['rap'])
        self.assertEqual(rap_ui['horas'], 120.0)
        self.assertEqual(rap_be['horas'], 264.0)

        # Competencia Productiva
        comp_prod = resultado[1]
        self.assertTrue(comp_prod['es_productiva'])
        self.assertEqual(comp_prod['horas'], 864.0)
        self.assertEqual(comp_prod['horas_programa'], 864.0)
        self.assertEqual(comp_prod['fecha_inicio'], '2027-04-24')
        self.assertEqual(comp_prod['fecha_fin'], '2027-10-24')
        self.assertEqual(len(comp_prod['raps_distribucion']), 1)
        self.assertEqual(comp_prod['raps_distribucion'][0]['horas'], 864.0)

    def test_api_programar_competencia_retorna_horas(self):
        """Verifica que el endpoint de programar competencia retorne horas de programa y planeación."""
        self._autenticar(self.inst1)

        resp = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/programar',
            json={
                'competencia': '38362 - Diseñar la solución de software',
                'fecha_inicio': '2025-08-10',
                'fecha_fin': '2025-10-20',
            }
        )
        self.assertEqual(resp.status_code, 200)
        datos = resp.get_json()
        self.assertTrue(datos['success'])
        self.assertIn('horas', datos)
        self.assertIn('horas_programa', datos)
        self.assertIn('horas_planeadas', datos)


