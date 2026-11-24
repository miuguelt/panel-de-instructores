"""Equipos ejecutores: equipo de la ficha, regla de transversales entre equipos y vista del equipo.

Entre equipos ejecutores distintos solo se programan competencias transversales (inglés incluido),
para todos los perfiles. Cada instructor ve en solo lectura la programación de su equipo.
"""

import importlib.util
import os
import unittest
from datetime import date

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app import db
from app.models import AsignacionProgramacion, Aprendiz, EquipoEjecutor, Ficha, Instructor, JuicioEvaluativo
from app.services import programacion_instructores as pi
from tests.test_coordinacion_rutas import COMP, BaseRutas

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LUNES = date(2026, 11, 16)
SABADO = date(2026, 11, 21)
ETICA = 'Ética para la construcción de una cultura de paz'


class EquipoDeFichaTest(BaseRutas):
    def test_ficha_nueva_toma_el_equipo_de_su_responsable(self):
        self.assertEqual(self.ficha_sis.equipo_id, self.sistemas.id)
        self.assertEqual(self.ficha_agr.equipo.nombre, 'Agrícola')
        sin_equipo = Ficha(codigo='2900003', nombre_programa='Contabilidad', instructor_id=self.coord.id)
        explicita = Ficha(codigo='2900004', nombre_programa='Redes', instructor_id=self.beto.id,
                          equipo_id=self.sistemas.id)
        db.session.add_all([sin_equipo, explicita])
        db.session.commit()
        self.assertIsNone(sin_equipo.equipo_id)
        self.assertEqual(explicita.equipo_id, self.sistemas.id)


class TipoDeCompetenciaTest(BaseRutas):
    def _juicio(self, competencia, tipo):
        aprendiz = Aprendiz(documento=str(Aprendiz.query.count() + 1), nombre='A', apellidos='B',
                            ficha_id=self.ficha_sis.id)
        db.session.add(aprendiz)
        db.session.flush()
        db.session.add(JuicioEvaluativo(ficha_id=self.ficha_sis.id, aprendiz_id=aprendiz.id, competencia=competencia,
                                        tipo_competencia=tipo, resultado_aprendizaje='RAP', juicio='POR EVALUAR'))
        db.session.commit()

    def test_usa_el_tipo_registrado_y_si_falta_lo_clasifica(self):
        self._juicio('Promover la interacción idónea', 'transversal')
        self._juicio('Gestionar la etapa productiva', 'productiva')
        self.assertEqual(pi.tipo_de_competencia(self.ficha_sis.id, 'Promover la interacción idónea'), 'transversal')
        self.assertEqual(pi.tipo_de_competencia(self.ficha_sis.id, 'Gestionar la etapa productiva'), 'tecnica')
        self.assertEqual(pi.tipo_de_competencia(self.ficha_sis.id, ETICA), 'transversal')
        self.assertEqual(pi.tipo_de_competencia(self.ficha_sis.id, 'Inglés'), 'ingles')
        self.assertEqual(pi.tipo_de_competencia(self.ficha_sis.id, COMP), 'tecnica')
        # El tipo registrado en otra ficha no cambia la clasificación de esta.
        self.assertEqual(pi.tipo_de_competencia(self.ficha_agr.id, 'Promover la interacción idónea'), 'tecnica')

    def test_transversal_incluye_ingles(self):
        self.assertTrue(pi.es_transversal(self.ficha_sis.id, ETICA))
        self.assertTrue(pi.es_transversal(self.ficha_sis.id, 'Inglés'))
        self.assertFalse(pi.es_transversal(self.ficha_sis.id, COMP))


class CruceDeEquipoTest(BaseRutas):
    def test_casos_de_cruce(self):
        ciro = self._inst('Ciro Sin Equipo', 'ciro', None)
        sin_equipo = Ficha(codigo='2900005', nombre_programa='Sin equipo', instructor_id=ciro.id)
        db.session.add(sin_equipo)
        db.session.commit()
        self.assertFalse(pi.es_cruce_de_equipo(self.ana, self.ficha_sis))
        self.assertTrue(pi.es_cruce_de_equipo(self.beto, self.ficha_sis))
        self.assertTrue(pi.es_cruce_de_equipo(ciro, self.ficha_sis))
        self.assertFalse(pi.es_cruce_de_equipo(self.beto, sin_equipo))

    def test_tecnica_entre_equipos_se_bloquea_y_transversal_se_permite(self):
        with self.assertRaises(pi.ErrorProgramacion) as error:
            pi.guardar_asignacion(self.form(instructor_id=self.beto.id), None)
        mensaje = str(error.exception)
        self.assertIn('Beto Agrícola no pertenece al equipo ejecutor Sistemas', mensaje)
        self.assertIn('solo se programan competencias transversales', mensaje)
        self.assertEqual(AsignacionProgramacion.query.count(), 0)
        pi.guardar_asignacion(self.form(instructor_id=self.beto.id, competencia=ETICA), None)
        pi.guardar_asignacion(self.form(instructor_id=self.beto.id, competencia='Inglés', jornada='tarde'), None)
        self.assertEqual(AsignacionProgramacion.query.count(), 2)

    def test_instructor_sin_equipo_solo_transversales_y_ficha_sin_equipo_libre(self):
        ciro = self._inst('Ciro Sin Equipo', 'ciro', None)
        db.session.commit()
        with self.assertRaises(pi.ErrorProgramacion):
            pi.guardar_asignacion(self.form(instructor_id=ciro.id), None)
        self.ficha_sis.equipo_id = None
        db.session.commit()
        pi.guardar_asignacion(self.form(instructor_id=ciro.id), None)
        self.assertEqual(AsignacionProgramacion.query.count(), 1)

    def test_editar_a_tecnica_de_otro_equipo_tambien_se_bloquea(self):
        asig = pi.guardar_asignacion(self.form(instructor_id=self.beto.id, competencia=ETICA), None)
        with self.assertRaises(pi.ErrorProgramacion):
            pi.guardar_asignacion(self.form(instructor_id=self.beto.id), None, asignacion=asig)

    def test_asignaciones_fuera_de_equipo_tras_un_traslado(self):
        tecnica = pi.guardar_asignacion(self.form(), None)
        pi.guardar_asignacion(self.form(competencia=ETICA, jornada='tarde'), None)
        pi.guardar_asignacion(self.form(fecha_inicio='2026-11-02', fecha_fin='2026-11-06', jornada='noche'), None)
        self.assertEqual(pi.asignaciones_fuera_de_equipo(self.ana, desde=LUNES), [])
        self.ana.equipo_id = self.agricola.id
        db.session.commit()
        self.assertEqual(pi.asignaciones_fuera_de_equipo(self.ana, desde=LUNES), [tecnica])
        self.assertEqual(pi.asignaciones_fuera_de_equipo(self.ana, desde=date(2026, 12, 1)), [])
        self.assertIsInstance(pi.asignaciones_fuera_de_equipo(self.ana), list)


class InstructoresDelEquipoTest(BaseRutas):
    def test_miembros_activos_y_externos_con_transversales(self):
        inactiva = self._inst('Dora Inactiva', 'dora', self.sistemas)
        inactiva.activo = False
        self._inst('Coordinadora Sistemas', 'coord2', self.sistemas, 'coordinacion')
        db.session.commit()
        pi.guardar_asignacion(self.form(instructor_id=self.beto.id, competencia=ETICA), None)
        nombres = [i.nombre for i in pi.instructores_del_equipo(self.sistemas.id, LUNES, SABADO)]
        self.assertEqual(nombres, ['Ana Sistemas', 'Beto Agrícola', 'Lina Líder'])
        # Fuera del periodo, el externo no aparece.
        otra = [i.nombre for i in pi.instructores_del_equipo(self.sistemas.id, date(2026, 12, 7), date(2026, 12, 12))]
        self.assertEqual(otra, ['Ana Sistemas', 'Lina Líder'])
        self.assertEqual([i.nombre for i in pi.instructores_del_equipo(self.agricola.id, LUNES, SABADO)],
                         ['Beto Agrícola'])


class ReglaEnRutasTest(BaseRutas):
    def test_coordinacion_y_admin_tambien_respetan_la_regla(self):
        for usuario in (self.coord, self.admin):
            with self.subTest(usuario=usuario.nombre):
                self.entrar(usuario)
                respuesta = self.client.post('/programacion/asignaciones', follow_redirects=True,
                                             data=self.form(instructor_id=self.beto.id))
                self.assertIn('solo se programan competencias transversales', self.texto(respuesta))
        self.assertEqual(AsignacionProgramacion.query.count(), 0)
        respuesta = self.client.post('/programacion/asignaciones', follow_redirects=True,
                                     data=self.form(instructor_id=self.beto.id, competencia=ETICA))
        self.assertIn('Programaste a Beto Agrícola', self.texto(respuesta))

    def test_lider_programa_transversal_a_externo_en_ficha_de_su_equipo(self):
        self.entrar(self.lider)
        self.client.post('/programacion/asignaciones', data=self.form(instructor_id=self.beto.id, competencia=ETICA))
        self.assertEqual(AsignacionProgramacion.query.count(), 1)
        respuesta = self.client.post('/programacion/asignaciones', follow_redirects=True,
                                     data=self.form(instructor_id=self.beto.id, jornada='tarde'))
        self.assertIn('solo se programan competencias transversales', self.texto(respuesta))
        self.assertEqual(AsignacionProgramacion.query.count(), 1)

    def test_formulario_muestra_el_equipo_de_cada_ficha(self):
        self.entrar(self.coord)
        html = self.texto(self.client.get('/programacion/?fecha=2026-11-18'))
        self.assertIn('2900001 · ADSO · Sistemas', html)
        self.assertIn('solo se le programan transversales', html)


class FichasPorEquipoTest(BaseRutas):
    URL = '/programacion/equipos/fichas'

    def test_listado_muestra_fichas_por_equipo_y_sin_equipo(self):
        self.ficha_agr.equipo_id = None
        db.session.commit()
        self.entrar(self.coord)
        html = self.texto(self.client.get('/programacion/equipos/'))
        self.assertIn('Cambiar el equipo de una ficha', html)
        self.assertIn('Fichas: 2900001', html)
        self.assertIn('1 ficha sin equipo: 2900002', html)
        self.assertIn('Sin fichas asignadas.', html)

    def test_asignar_ficha_valida_vacia_y_errores(self):
        self.entrar(self.coord)
        respuesta = self.client.post(self.URL, follow_redirects=True,
                                     data={'ficha_id': self.ficha_agr.id, 'equipo_id': self.sistemas.id})
        self.assertIn('La ficha 2900002 quedó en el equipo Sistemas', self.texto(respuesta))
        self.assertEqual(db.session.get(Ficha, self.ficha_agr.id).equipo_id, self.sistemas.id)
        respuesta = self.client.post(self.URL, follow_redirects=True, data={'ficha_id': self.ficha_agr.id, 'equipo_id': ''})
        self.assertIn('La ficha 2900002 quedó sin equipo', self.texto(respuesta))
        self.assertIsNone(db.session.get(Ficha, self.ficha_agr.id).equipo_id)
        for datos in ({}, {'ficha_id': 'x'}, {'ficha_id': '999'}):
            with self.subTest(datos=datos):
                self.assertIn('Elige una ficha', self.texto(self.client.post(self.URL, data=datos, follow_redirects=True)))
        self.agricola.activo = False
        db.session.commit()
        for valor in (str(self.agricola.id), 'x', '999'):
            with self.subTest(equipo=valor):
                respuesta = self.client.post(self.URL, follow_redirects=True,
                                             data={'ficha_id': self.ficha_sis.id, 'equipo_id': valor})
                self.assertIn('Elige un equipo activo', self.texto(respuesta))
        self.assertEqual(db.session.get(Ficha, self.ficha_sis.id).equipo_id, self.sistemas.id)

    def test_solo_coordinacion_asigna_fichas(self):
        self.entrar(self.lider)
        respuesta = self.client.post(self.URL, data={'ficha_id': self.ficha_agr.id, 'equipo_id': self.sistemas.id})
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(db.session.get(Ficha, self.ficha_agr.id).equipo_id, self.agricola.id)

    def test_traslado_avisa_asignaciones_tecnicas_que_quedan_fuera(self):
        pi.guardar_asignacion(self.form(fecha_inicio='2027-02-01', fecha_fin='2027-02-05'), None)
        self.entrar(self.coord)
        respuesta = self.client.post('/programacion/equipos/miembros', follow_redirects=True,
                                     data={'instructor_id': self.ana.id, 'equipo_id': self.agricola.id})
        html = self.texto(respuesta)
        self.assertIn('Ana Sistemas quedó al equipo Agrícola', html)
        self.assertIn('tiene 1 asignación(es) vigente(s) de competencias técnicas en fichas de otro equipo (2900001)', html)
        self.assertEqual(AsignacionProgramacion.query.count(), 1)  # no se borra
        respuesta = self.client.post('/programacion/equipos/miembros', follow_redirects=True,
                                     data={'instructor_id': self.ana.id, 'equipo_id': self.sistemas.id})
        self.assertNotIn('vigente(s)', self.texto(respuesta))


class MiEquipoTest(BaseRutas):
    URL = '/programacion/equipo?fecha=2026-11-18'

    def test_anonimo_va_al_login(self):
        respuesta = self.client.get('/programacion/equipo')
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/login', respuesta.headers['Location'])

    def test_colaborador_ve_a_sus_companeros_externos_y_pendientes(self):
        pi.guardar_asignacion(self.form(), None)
        pi.guardar_asignacion(self.form(instructor_id=self.beto.id, competencia=ETICA, jornada='tarde'), None)
        self.entrar(self.ana)
        html = self.texto(self.client.get(self.URL))
        self.assertIn('Equipo Sistemas', html)
        self.assertIn('Lina Líder', html)
        self.assertIn('Beto Agrícola', html)
        self.assertIn('De otro equipo', html)
        self.assertIn(ETICA, html)
        self.assertIn(COMP, html)
        self.assertIn('Falta por programar en la semana', html)
        self.assertIn('No tiene asignaciones en 4 días hábiles', html)  # Lina
        # Solo lectura: sin botones de programar ni formulario.
        self.assertNotIn('data-prg-programar', html)
        self.assertNotIn('data-prg-editar', html)
        self.assertNotIn('form-asignacion', html)
        self.assertNotIn('Todos los equipos', html)
        self.assertIn('aria-current="page"', html)
        self.assertEqual(html.count('class="seguimiento-pestana '), 1)  # Mi equipo activa
        self.assertEqual(html.count('class="seguimiento-pestana"'), 1)  # Mi semana; sin «Calendario»

    def test_vista_mensual_y_navegacion_quedan_en_mi_equipo(self):
        self.entrar(self.ana)
        html = self.texto(self.client.get('/programacion/equipo?vista=mes&fecha=2026-11-18'))
        self.assertIn('Noviembre de 2026', html)
        self.assertIn('/programacion/equipo?vista=mes', html)
        self.assertNotIn('/programacion/?vista', html)

    def test_lider_ve_la_pestana_de_calendario(self):
        self.entrar(self.lider)
        html = self.texto(self.client.get(self.URL))
        self.assertEqual(html.count('class="seguimiento-pestana"'), 2)  # Calendario y Mi semana
        self.assertIn('Calendario', html)

    def test_todos_programados_muestra_estado_vacio(self):
        for instructor, jornada in ((self.ana, 'manana'), (self.lider, 'manana')):
            pi.guardar_asignacion(self.form(instructor_id=instructor.id, jornada=jornada), None)
        self.entrar(self.ana)
        html = self.texto(self.client.get(self.URL))
        self.assertIn('Todos tienen programación', html)

    def test_sin_equipo_o_equipo_archivado_muestra_mensaje(self):
        self.entrar(self.coord)
        html = self.texto(self.client.get(self.URL))
        self.assertIn('Aún no perteneces a un equipo ejecutor', html)
        self.agricola.activo = False
        db.session.commit()
        self.entrar(self.beto)
        self.assertIn('Aún no perteneces a un equipo ejecutor', self.texto(self.client.get(self.URL)))

    def test_equipo_sin_instructores_activos(self):
        vacio = EquipoEjecutor(nombre='Contabilidad')
        db.session.add(vacio)
        db.session.flush()
        solo = self._inst('Sara Sola', 'sara', vacio)
        solo.rol = 'coordinacion'
        db.session.commit()
        self.entrar(solo)
        html = self.texto(self.client.get(self.URL))
        self.assertIn('Tu equipo aún no tiene instructores activos', html)

    def test_mi_semana_tiene_pestanas(self):
        self.entrar(self.beto)
        html = self.texto(self.client.get('/programacion/mia?fecha=2026-11-18'))
        self.assertIn('Mi equipo', html)
        self.assertIn('/programacion/equipo', html)


class MigracionFichaEquipoTest(unittest.TestCase):
    def test_upgrade_llena_el_equipo_desde_el_responsable_y_downgrade_lo_quita(self):
        ruta = os.path.join(RAIZ, 'migrations', 'versions', 'z51_ficha_equipo.py')
        spec = importlib.util.spec_from_file_location('revision_z51', ruta)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)

        motor = create_engine('sqlite:///:memory:')
        conexion = motor.connect()
        try:
            conexion.execute(text('CREATE TABLE equipos_ejecutores (id INTEGER PRIMARY KEY, nombre TEXT)'))
            conexion.execute(text('CREATE TABLE instructores (id INTEGER PRIMARY KEY, equipo_id INTEGER)'))
            conexion.execute(text('CREATE TABLE fichas (id INTEGER PRIMARY KEY, codigo TEXT, instructor_id INTEGER)'))
            conexion.execute(text("INSERT INTO equipos_ejecutores VALUES (7, 'Sistemas')"))
            conexion.execute(text('INSERT INTO instructores VALUES (1, 7), (2, NULL)'))
            conexion.execute(text("INSERT INTO fichas VALUES (10, 'A', 1), (11, 'B', 2)"))
            conexion.commit()

            with Operations.context(MigrationContext.configure(conexion)):
                revision.upgrade()
            filas = conexion.execute(text('SELECT id, codigo, equipo_id FROM fichas ORDER BY id')).fetchall()
            self.assertEqual(filas, [(10, 'A', 7), (11, 'B', None)])

            with Operations.context(MigrationContext.configure(conexion)):
                revision.downgrade()
            columnas = {c['name'] for c in inspect(conexion).get_columns('fichas')}
            self.assertEqual(columnas, {'id', 'codigo', 'instructor_id'})
            self.assertEqual(conexion.execute(text('SELECT COUNT(*) FROM fichas')).scalar(), 2)
        finally:
            conexion.close()
            motor.dispose()


class CoordinacionRequiredTest(BaseRutas):
    def test_decorador_redirige_bloquea_o_deja_pasar(self):
        from flask_login import login_user, logout_user
        from werkzeug.exceptions import Forbidden

        from app.services.permisos import coordinacion_required

        protegida = coordinacion_required(lambda: 'adentro')
        with self.app.test_request_context('/privada'):
            respuesta = protegida()
            self.assertEqual(respuesta.status_code, 302)
            self.assertIn('/login', respuesta.headers['Location'])
            login_user(self.ana)
            with self.assertRaises(Forbidden):
                protegida()
            logout_user()
            login_user(self.admin)
            self.assertEqual(protegida(), 'adentro')


class ModeloRelacionesTest(BaseRutas):
    def test_instructor_conserva_su_equipo(self):
        self.assertEqual(db.session.get(Instructor, self.ana.id).equipo.nombre, 'Sistemas')


if __name__ == '__main__':
    unittest.main()
