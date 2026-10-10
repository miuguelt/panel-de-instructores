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

