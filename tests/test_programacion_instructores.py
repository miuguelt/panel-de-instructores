"""Programación de instructores: fechas, choques, sincronización, ocupación y alertas.

Semana de referencia: lunes 16/11/2026 (festivo, Independencia de Cartagena) a sábado 21/11/2026,
así que tiene 4 días laborables (martes a viernes).
"""

import unittest
from datetime import date

from app import create_app, db
from app.models import (
    AsignacionProgramacion, EquipoEjecutor, Ficha, FichaCompetenciaProgramacion,
    Instructor, JuicioEvaluativo, Aprendiz,
)
from app.services import programacion_instructores as pi

LUNES = date(2026, 11, 16)
SABADO = date(2026, 11, 21)
COMP = 'Desarrollar la solución de software'


class BaseProgramacion(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.sistemas = EquipoEjecutor(nombre='Sistemas')
        self.agricola = EquipoEjecutor(nombre='Agrícola')
        db.session.add_all([self.sistemas, self.agricola])
        db.session.flush()
        self.ana = self._instructor('Ana Sistemas', 'ana', self.sistemas)
        self.beto = self._instructor('Beto Agrícola', 'beto', self.agricola)
        self.ciro = self._instructor('Ciro Sin Equipo', 'ciro', None)
        self.ficha_sis = Ficha(codigo='2900001', nombre_programa='ADSO', instructor_id=self.ana.id)
        self.ficha_agr = Ficha(codigo='2900002', nombre_programa='Agropecuaria', instructor_id=self.beto.id)
        db.session.add_all([self.ficha_sis, self.ficha_agr])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _instructor(self, nombre, usuario, equipo, rol='colaborador'):
        inst = Instructor(nombre=nombre, correo=f'{usuario}@sena.edu.co', rol=rol,
                          equipo_id=equipo.id if equipo else None)
        inst.set_password('Clave123!')
        db.session.add(inst)
        db.session.flush()
        return inst

    def datos(self, **cambios):
        base = {
            'instructor_id': self.ana.id, 'ficha_id': self.ficha_sis.id, 'competencia': COMP,
            'modo': 'semanas', 'fecha_inicio': '2026-11-16', 'fecha_fin': '2026-11-21',
            'dias_semana': ['0', '1', '2', '3', '4'], 'jornada': 'manana',
        }
        base.update(cambios)
        return base


class UtilidadesTest(unittest.TestCase):
    def test_lunes_de(self):
        self.assertEqual(pi.lunes_de(date(2026, 11, 22)), LUNES)
        self.assertEqual(pi.lunes_de(LUNES), LUNES)

    def test_parsear_fecha(self):
        from datetime import datetime
        self.assertEqual(pi.parsear_fecha('2026-11-16'), LUNES)
        self.assertEqual(pi.parsear_fecha(LUNES), LUNES)
        self.assertEqual(pi.parsear_fecha(datetime(2026, 11, 16, 8)), LUNES)
        self.assertIsNone(pi.parsear_fecha(''))
        self.assertIsNone(pi.parsear_fecha('16/11/2026'))
        self.assertIsNone(pi.parsear_fecha(None))
        self.assertIsNone(pi.parsear_fecha(42))

    def test_mascara_ignora_invalidos_y_domingo(self):
        self.assertEqual(pi.mascara_desde_dias(['0', 2, 'x', None, 6, -1, '5']), 0b100101)
        self.assertEqual(pi.mascara_desde_dias(None), 0)
        self.assertEqual(pi.dias_desde_mascara(0b100101), [0, 2, 5])

    def test_fechas_excluyen_festivo_domingo_y_dias_no_marcados(self):
        class R:
            fecha_inicio, fecha_fin, dias_semana = LUNES, date(2026, 11, 22), 0b111111
        fechas = pi.fechas_de_asignacion(R)
        self.assertEqual(fechas, [date(2026, 11, d) for d in (17, 18, 19, 20, 21)])
        R.dias_semana = 0b000010  # solo martes
        self.assertEqual(pi.fechas_de_asignacion(R), [date(2026, 11, 17)])
        self.assertEqual(pi.fechas_de_asignacion(R, desde=date(2026, 11, 18)), [])

    def test_dia_laborable(self):
        self.assertFalse(pi.es_dia_laborable(LUNES))  # festivo
        self.assertTrue(pi.es_dia_laborable(date(2026, 11, 17)))
        self.assertFalse(pi.es_dia_laborable(SABADO))

    def test_nivel_y_porcentaje(self):
        self.assertEqual(pi.nivel_ocupacion(0, 0), pi.NIVEL_SIN_DIAS_HABILES)
        self.assertEqual(pi.nivel_ocupacion(4, 0), pi.NIVEL_SIN_PROGRAMACION)
        self.assertEqual(pi.nivel_ocupacion(4, 2), pi.NIVEL_PARCIAL)
        self.assertEqual(pi.nivel_ocupacion(4, 4), pi.NIVEL_COMPLETO)
        self.assertIsNone(pi.porcentaje(0, 0))
        self.assertEqual(pi.porcentaje(1, 4), 25)
        self.assertEqual(pi.porcentaje(9, 4), 100)

    def test_dias_del_rango_marca_festivos(self):
        dias = pi.dias_del_rango(LUNES, date(2026, 11, 22))
        self.assertEqual(len(dias), 6)  # sin domingo
        self.assertEqual(dias[0]['festivo'], 'Independencia de Cartagena')
        self.assertFalse(dias[0]['laborable'])
        self.assertEqual(dias[5]['nombre'], 'Sábado')
        self.assertEqual(len(pi.dias_del_rango(LUNES, SABADO, incluir_sabado=False)), 5)


class ValidacionTest(BaseProgramacion):
    def test_entrada_valida_por_semanas(self):
        limpio = pi.validar_datos(self.datos(competencia='  Desarrollar   la solución de software '))
        self.assertEqual(limpio['competencia'], COMP)
        self.assertEqual(limpio['dias_semana'], 0b011111)
        self.assertEqual(limpio['fecha_fin'], SABADO)

    def test_un_dia_usa_la_fecha_de_inicio(self):
        limpio = pi.validar_datos(self.datos(modo='dia', fecha_inicio='2026-11-18', fecha_fin='', dias_semana=None))
        self.assertEqual((limpio['fecha_inicio'], limpio['fecha_fin']), (date(2026, 11, 18),) * 2)
        self.assertEqual(limpio['dias_semana'], 1 << 2)

    def test_dia_suelto_como_texto(self):
        self.assertEqual(pi.validar_datos(self.datos(dias_semana='3'))['dias_semana'], 1 << 3)

    def test_entradas_vacias_e_invalidas(self):
        casos = [
            ({'instructor_id': ''}, 'instructor'),
            ({'instructor_id': 'abc'}, 'instructor'),
            ({'instructor_id': 999}, 'instructor'),
            ({'ficha_id': 999}, 'ficha'),
            ({'competencia': '   '}, 'competencia'),
            ({'competencia': 'x' * 301}, '300'),
            ({'fecha_inicio': ''}, 'inicio'),
            ({'fecha_fin': 'mañana'}, 'finalización'),
            ({'fecha_fin': '2026-11-10'}, 'anterior'),
            ({'fecha_fin': '2028-01-01'}, 'un año'),
            ({'jornada': 'madrugada'}, 'jornada'),
            ({'dias_semana': []}, 'día'),
            ({'modo': 'dia', 'fecha_inicio': '2026-11-22'}, 'domingo'),
        ]
        for cambio, texto in casos:
            with self.subTest(cambio=cambio):
                with self.assertRaises(pi.ErrorProgramacion) as error:
                    pi.validar_datos(self.datos(**cambio))
                self.assertIn(texto, str(error.exception))


class PersistenciaTest(BaseProgramacion):
    def test_guardar_crea_y_sincroniza_planeacion(self):
        asig = pi.guardar_asignacion(self.datos(observacion='  Ambiente 3  '), creado_por_id=self.ana.id)
        self.assertEqual(asig.observacion, 'Ambiente 3')
        self.assertEqual(asig.creado_por_id, self.ana.id)
        prog = FichaCompetenciaProgramacion.query.filter_by(ficha_id=self.ficha_sis.id, competencia=COMP).one()
        self.assertEqual((prog.fecha_inicio, prog.fecha_fin, prog.instructor_id), (LUNES, SABADO, self.ana.id))

    def test_sincroniza_rango_completo_de_varias_asignaciones(self):
        pi.guardar_asignacion(self.datos(fecha_inicio='2026-11-23', fecha_fin='2026-11-27'), None)
        pi.guardar_asignacion(self.datos(instructor_id=self.beto.id), None)
        prog = FichaCompetenciaProgramacion.query.filter_by(competencia=COMP).one()
        self.assertEqual((prog.fecha_inicio, prog.fecha_fin), (LUNES, date(2026, 11, 27)))
        self.assertEqual(prog.instructor_id, self.beto.id)

    def test_choque_misma_jornada_bloquea_y_otra_jornada_no(self):
        pi.guardar_asignacion(self.datos(), None)
        with self.assertRaises(pi.ErrorProgramacion) as error:
            pi.guardar_asignacion(self.datos(ficha_id=self.ficha_agr.id, competencia='Transversal ética',
                                             dias_semana=['2', '3']), None)
        mensaje = str(error.exception)
        self.assertIn('18/11/2026', mensaje)
        self.assertIn('2900001', mensaje)
        self.assertIn('1 día(s) más', mensaje)
        otra = pi.guardar_asignacion(self.datos(ficha_id=self.ficha_agr.id, competencia='Transversal ética',
                                                jornada='tarde'), None)
        self.assertEqual(otra.jornada_etiqueta, 'Tarde')

    def test_choque_de_un_solo_dia_sin_sufijo(self):
        pi.guardar_asignacion(self.datos(modo='dia', fecha_inicio='2026-11-18'), None)
        choques = pi.detectar_choques(pi.validar_datos(self.datos()))
        self.assertEqual(len(choques), 1)
        self.assertNotIn('más', pi.mensaje_choque(choques))

    def test_rango_sin_dias_habiles_se_rechaza(self):
        with self.assertRaises(pi.ErrorProgramacion) as error:
            pi.guardar_asignacion(self.datos(fecha_inicio='2026-11-16', fecha_fin='2026-11-16',
                                             dias_semana=['0']), None)
        self.assertIn('ningún día hábil', str(error.exception))

    def test_editar_no_choca_consigo_y_resincroniza_competencia_anterior(self):
        asig = pi.guardar_asignacion(self.datos(), None)
        pi.guardar_asignacion(self.datos(competencia='Otra competencia'), None, asignacion=asig)
        self.assertEqual(AsignacionProgramacion.query.count(), 1)
        nueva = FichaCompetenciaProgramacion.query.filter_by(competencia='Otra competencia').one()
        self.assertEqual(nueva.fecha_fin, SABADO)
        # La anterior conserva su programación (ya no hay asignaciones que la modifiquen).
        self.assertIsNotNone(FichaCompetenciaProgramacion.query.filter_by(competencia=COMP).first())

    def test_eliminar_conserva_programacion_manual(self):
        asig = pi.guardar_asignacion(self.datos(), None)
        pi.eliminar_asignacion(asig)
        self.assertEqual(AsignacionProgramacion.query.count(), 0)
        self.assertIsNone(pi.sincronizar_competencia(self.ficha_sis.id, COMP))
        self.assertEqual(FichaCompetenciaProgramacion.query.count(), 1)

    def test_competencias_de_ficha_une_fuentes(self):
        aprendiz = Aprendiz(documento='1', nombre='A', apellidos='B', ficha_id=self.ficha_sis.id)
        db.session.add(aprendiz)
        db.session.flush()
        db.session.add(JuicioEvaluativo(ficha_id=self.ficha_sis.id, aprendiz_id=aprendiz.id,
                                        competencia='Inglés', resultado_aprendizaje='RAP 1', juicio='POR EVALUAR'))
        db.session.commit()
        pi.guardar_asignacion(self.datos(), None)
        self.assertEqual(pi.competencias_de_ficha(self.ficha_sis.id), [COMP, 'Inglés'])
        self.assertEqual(pi.competencias_de_ficha(self.ficha_agr.id), [])


class OcupacionTest(BaseProgramacion):
    def test_niveles_por_instructor_y_resumen(self):
        pi.guardar_asignacion(self.datos(), None)  # Ana: martes a viernes
        pi.guardar_asignacion(self.datos(instructor_id=self.beto.id, ficha_id=self.ficha_agr.id,
                                         dias_semana=['1', '5']), None)  # Beto: martes y sábado
        filas = pi.ocupacion([self.ana, self.beto, self.ciro], LUNES, SABADO)
        por_nombre = {f['instructor'].nombre: f for f in filas}
        ana, beto, ciro = por_nombre['Ana Sistemas'], por_nombre['Beto Agrícola'], por_nombre['Ciro Sin Equipo']
        self.assertEqual((ana['dias_laborables'], ana['dias_programados'], ana['porcentaje']), (4, 4, 100))
        self.assertEqual(ana['nivel'], pi.NIVEL_COMPLETO)
        self.assertEqual(beto['porcentaje'], 25)
        self.assertIn(SABADO, beto['celdas'])  # el sábado se muestra aunque no cuente
        self.assertEqual(len(beto['dias_libres']), 3)
        self.assertEqual(ciro['etiqueta_nivel'], 'Sin programación')

        self.assertEqual([f['instructor'].nombre for f in pi.alertas(filas)], ['Ciro Sin Equipo', 'Beto Agrícola'])
        self.assertEqual(pi.resumen(filas), {
            'instructores': 3, 'sin_programacion': 1, 'con_dias_libres': 1, 'completos': 1,
            'porcentaje': round(100 * 5 / 12),
        })

    def test_celdas_ordenadas_por_jornada(self):
        pi.guardar_asignacion(self.datos(jornada='noche'), None)
        pi.guardar_asignacion(self.datos(jornada='manana', competencia='Inglés'), None)
        fila = pi.ocupacion([self.ana], LUNES, SABADO)[0]
        self.assertEqual([a.jornada for a in fila['celdas'][date(2026, 11, 17)]], ['manana', 'noche'])

    def test_sin_instructores_no_consulta(self):
        self.assertEqual(pi.asignaciones_en_rango([], LUNES, SABADO), [])
        self.assertEqual(pi.ocupacion([], LUNES, SABADO), [])
        self.assertIsNone(pi.resumen([])['porcentaje'])

    def test_agrupar_por_equipo_con_externos(self):
        pi.guardar_asignacion(self.datos(), None)  # Ana completa su semana
        filas = pi.ocupacion([self.ana, self.beto, self.ciro], LUNES, SABADO)
        grupos = pi.agrupar_por_equipo(filas, equipos_visibles={self.sistemas.id})
        self.assertEqual([g['nombre'] for g in grupos], ['Agrícola', 'Sistemas', 'Sin equipo asignado'])
        self.assertTrue(grupos[0]['filas'][0]['externo'])
        self.assertFalse(grupos[1]['filas'][0]['externo'])
        self.assertEqual((grupos[1]['alertas'], grupos[1]['porcentaje']), (0, 100))
        self.assertEqual((grupos[0]['alertas'], grupos[0]['porcentaje']), (1, 0))
        sin_externos = pi.agrupar_por_equipo(filas)
        self.assertFalse(any(f['externo'] for g in sin_externos for f in g['filas']))


class VisibilidadTest(BaseProgramacion):
    def test_coordinacion_ve_a_todos_y_filtra_por_equipo(self):
        coord = self._instructor('Coordinadora', 'coord', None, rol='coordinacion')
        db.session.commit()
        todos, propios = pi.instructores_visibles(coord, LUNES, SABADO)
        self.assertIsNone(propios)
        self.assertEqual(len(todos), 3)  # coordinación no figura como instructor por programar
        solo, _ = pi.instructores_visibles(coord, LUNES, SABADO, equipo_id=self.agricola.id)
        self.assertEqual([i.nombre for i in solo], ['Beto Agrícola'])

    def test_lider_ve_su_equipo_y_externos_en_sus_fichas(self):
        self.sistemas.lider_id = self.ana.id
        inactivo = self._instructor('Dora Inactiva', 'dora', self.agricola)
        inactivo.activo = False
        db.session.commit()
        pi.guardar_asignacion(self.datos(instructor_id=self.beto.id, competencia='Transversal'), None)
        pi.guardar_asignacion(self.datos(instructor_id=inactivo.id, competencia='Otra'), None)
        visibles, propios = pi.instructores_visibles(self.ana, LUNES, SABADO)
        self.assertEqual([i.nombre for i in visibles], ['Ana Sistemas', 'Beto Agrícola'])
        self.assertEqual(propios, {self.sistemas.id})
        # Filtrar por un equipo que no lidera vuelve a sus equipos.
        otra_vista, _ = pi.instructores_visibles(self.ana, LUNES, SABADO, equipo_id=self.agricola.id)
        self.assertEqual(len(otra_vista), 2)
        filtrado, _ = pi.instructores_visibles(self.ana, LUNES, SABADO, equipo_id=self.sistemas.id)
        self.assertEqual(len(filtrado), 2)

    def test_sin_equipos_liderados_no_ve_a_nadie(self):
        visibles, propios = pi.instructores_visibles(self.ciro, LUNES, SABADO)
        self.assertEqual((visibles, propios), ([], set()))


class PermisosTest(BaseProgramacion):
    def test_anonimo_y_casos_limite(self):
        from flask_login import AnonymousUserMixin
        from app.services import permisos
        anonimo = AnonymousUserMixin()
        self.assertEqual(permisos.ids_equipos_liderados(anonimo), set())
        self.assertFalse(permisos.puede_entrar_a_coordinacion(anonimo))
        self.assertFalse(permisos.puede_programar(self.ana, self.ficha_sis, anonimo))
        self.assertFalse(permisos.puede_programar(None, self.ficha_sis, self.ana))
        # Sin contexto de petición no hay caché, pero el resultado es el mismo.
        self.sistemas.lider_id = self.ana.id
        db.session.commit()
        self.assertEqual(permisos.ids_equipos_liderados(self.ana), {self.sistemas.id})
        self.assertTrue(permisos.puede_entrar_a_coordinacion(self.ana))
        self.assertTrue(permisos.puede_programar(self.beto, self.ficha_sis, self.ana))
        self.assertFalse(permisos.puede_programar(self.beto, self.ficha_agr, self.ana))
        self.assertFalse(permisos.puede_programar(self.ana, self.ficha_sis, self.beto))
        huerfana = Ficha(codigo='2900003', nombre_programa='Sin responsable', instructor_id=999)
        self.assertFalse(permisos.puede_programar(self.beto, huerfana, self.ana))

    def test_contar_alertas_semana(self):
        coord = self._instructor('Coordinadora', 'coord2', None, rol='coordinacion')
        db.session.commit()
        pi.guardar_asignacion(self.datos(), None)
        self.assertEqual(pi.contar_alertas_semana(coord, hoy=date(2026, 11, 18)), 2)  # Beto y Ciro


class ModeloTest(BaseProgramacion):
    def test_propiedades_de_asignacion_e_instructor(self):
        asig = pi.guardar_asignacion(self.datos(dias_semana=['0', '2', '5']), None)
        self.assertEqual(asig.dias_etiqueta, 'L X S')
        self.assertTrue(asig.incluye_dia(5))
        self.assertFalse(asig.incluye_dia(1))
        self.assertFalse(asig.incluye_dia(6))
        transitoria = AsignacionProgramacion(jornada='otra')
        self.assertEqual(transitoria.jornada_etiqueta, 'otra')
        self.assertFalse(self.ana.es_lider)
        self.sistemas.lider_id = self.ana.id
        db.session.commit()
        self.assertTrue(self.ana.es_lider)
        self.assertFalse(self.ana.es_coordinacion)
        self.assertIn('Sistemas', repr(self.sistemas))
        self.assertEqual([m.nombre for m in self.sistemas.miembros], ['Ana Sistemas'])


if __name__ == '__main__':
    unittest.main()
