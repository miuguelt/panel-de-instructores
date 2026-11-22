"""Rutas de programación y equipos: permisos por perfil, calendario, asignaciones y gestión de equipos."""

import unittest
from datetime import date

from app import create_app, db
from app.models import AsignacionProgramacion, EquipoEjecutor, Ficha, FichaCompetenciaProgramacion, Instructor
from app.services import programacion_instructores as pi

COMP = 'Desarrollar la solución de software'


class BaseRutas(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()
        self.sistemas = EquipoEjecutor(nombre='Sistemas')
        self.agricola = EquipoEjecutor(nombre='Agrícola')
        db.session.add_all([self.sistemas, self.agricola])
        db.session.flush()
        self.coord = self._inst('Carla Coordinación', 'coord', None, 'coordinacion')
        self.admin = self._inst('Andrés Admin', 'admin', None, 'admin')
        self.lider = self._inst('Lina Líder', 'lider', self.sistemas)
        self.ana = self._inst('Ana Sistemas', 'ana', self.sistemas)
        self.beto = self._inst('Beto Agrícola', 'beto', self.agricola)
        self.sistemas.lider_id = self.lider.id
        self.ficha_sis = Ficha(codigo='2900001', nombre_programa='ADSO', instructor_id=self.ana.id)
        self.ficha_agr = Ficha(codigo='2900002', nombre_programa='Agropecuaria', instructor_id=self.beto.id)
        db.session.add_all([self.ficha_sis, self.ficha_agr])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _inst(self, nombre, usuario, equipo, rol='colaborador'):
        inst = Instructor(nombre=nombre, correo=f'{usuario}@sena.edu.co', rol=rol,
                          equipo_id=equipo.id if equipo else None)
        inst.set_password('Clave123!')
        db.session.add(inst)
        db.session.flush()
        return inst

    def entrar(self, instructor):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = f'{instructor.id}:1'
            sess['_fresh'] = True

    def form(self, **cambios):
        datos = {
            'instructor_id': self.ana.id, 'ficha_id': self.ficha_sis.id, 'competencia': COMP,
            'modo': 'semanas', 'fecha_inicio': '2026-11-16', 'fecha_fin': '2026-11-21',
            'dias_semana': ['0', '1', '2', '3', '4'], 'jornada': 'manana',
            'vista': 'semana', 'fecha': '2026-11-16', 'equipo': '',
        }
        datos.update(cambios)
        return datos

    def texto(self, respuesta):
        return respuesta.get_data(as_text=True)


class CalendarioTest(BaseRutas):
    def test_anonimo_va_al_login(self):
        respuesta = self.client.get('/programacion/')
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/login', respuesta.headers['Location'])

    def test_instructor_sin_equipo_liderado_ve_su_semana(self):
        self.entrar(self.ana)
        respuesta = self.client.get('/programacion/')
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/programacion/mia', respuesta.headers['Location'])
        pi.guardar_asignacion(self.form(), None)
        html = self.texto(self.client.get('/programacion/mia?fecha=2026-11-18'))
        self.assertIn('Semana del 16 al 21 de noviembre de 2026', html)
        self.assertIn(COMP, html)
        self.assertNotIn('data-prg-programar', html)  # solo lectura
        self.assertIn('Programado', html)

    def test_mi_semana_vacia(self):
        self.entrar(self.beto)
        html = self.texto(self.client.get('/programacion/mia?fecha=2026-11-18'))
        self.assertIn('No tienes asignaciones pendientes', html)
        self.assertIn('Sin programación', html)

    def test_coordinacion_ve_todos_los_equipos_alertas_y_barras(self):
        pi.guardar_asignacion(self.form(), None)
        self.entrar(self.coord)
        html = self.texto(self.client.get('/programacion/?fecha=2026-11-18'))
        for texto in ('Sistemas', 'Agrícola', 'Sin equipo asignado', 'Alertas de la semana',
                      'Beto Agrícola', 'Festivo', 'role="progressbar"', 'Programar instructor', 'Equipos'):
            self.assertIn(texto, html)
        self.assertIn('data-prg-editar', html)
        self.assertNotIn('De otro equipo', html)

    def test_filtro_por_equipo_y_vista_mensual(self):
        self.entrar(self.coord)
        html = self.texto(self.client.get(f'/programacion/?vista=mes&fecha=2026-11-18&equipo={self.agricola.id}'))
        self.assertIn('Noviembre de 2026', html)
        self.assertIn('Alertas del mes', html)
        self.assertIn('Beto Agrícola', html)
        self.assertNotIn('Ana Sistemas</span>', html)
        self.assertIn('prg-tabla--mes', html)

    def test_parametros_invalidos_usan_valores_por_defecto(self):
        self.entrar(self.coord)
        respuesta = self.client.get('/programacion/?vista=anio&fecha=ayer&equipo=x')
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('Semana del', self.texto(respuesta))

    def test_sin_alertas_muestra_estado_vacio(self):
        self.entrar(self.lider)
        for inst in (self.ana, self.lider):
            pi.guardar_asignacion(self.form(instructor_id=inst.id), None)
        html = self.texto(self.client.get('/programacion/?fecha=2026-11-18'))
        self.assertIn('Todos tienen programación', html)

    def test_lider_ve_su_equipo_y_externos_en_sus_fichas(self):
        pi.guardar_asignacion(self.form(instructor_id=self.beto.id, competencia='Ética'), None)
        pi.guardar_asignacion(self.form(instructor_id=self.beto.id, ficha_id=self.ficha_agr.id,
                                        competencia='Riego', jornada='tarde'), None)
        self.entrar(self.lider)
        html = self.texto(self.client.get('/programacion/?fecha=2026-11-18'))
        self.assertIn('Lina Líder', html)
        self.assertIn('De otro equipo', html)
        self.assertNotIn('Equipos</span>', html)  # solo coordinación gestiona equipos
        # Ética (ficha de Sistemas) se edita los 4 días hábiles; Riego (ficha agrícola) solo se ve.
        self.assertEqual(html.count('data-prg-editar'), 4)
        self.assertIn('Riego', html)

    def test_coordinacion_con_equipo_vacio_invita_a_ir_a_equipos(self):
        vacio = EquipoEjecutor(nombre='Contabilidad')
        db.session.add(vacio)
        db.session.commit()
        self.entrar(self.coord)
        html = self.texto(self.client.get(f'/programacion/?equipo={vacio.id}'))
        self.assertIn('Aún no hay instructores para mostrar', html)
        self.assertIn('Ir a equipos', html)
        self.assertNotIn('Alertas de la semana', html)

    def test_lider_de_equipo_vacio_ve_mensaje(self):
        vacio = EquipoEjecutor(nombre='Contabilidad', lider_id=self.beto.id)
        db.session.add(vacio)
        self.agricola.lider_id = None
        db.session.commit()
        self.beto.equipo_id = None
        db.session.commit()
        self.entrar(self.beto)
        html = self.texto(self.client.get('/programacion/'))
        self.assertIn('Tu equipo aún no tiene instructores', html)

    def test_contador_de_alertas_en_el_menu(self):
        self.entrar(self.coord)
        html = self.texto(self.client.get('/programacion/'))
        self.assertIn('instructores con días sin programar', html)
        self.entrar(self.ana)
        html = self.texto(self.client.get('/programacion/mia'))
        self.assertNotIn('instructores con días sin programar', html)

    def test_competencias_de_ficha_json(self):
        pi.guardar_asignacion(self.form(), None)
        self.entrar(self.coord)
        self.assertEqual(self.client.get(f'/programacion/fichas/{self.ficha_sis.id}/competencias').get_json(), [COMP])
        self.assertEqual(self.client.get('/programacion/fichas/999/competencias').status_code, 404)
        self.entrar(self.ana)
        self.assertEqual(self.client.get(f'/programacion/fichas/{self.ficha_sis.id}/competencias').status_code, 403)


class AsignacionesTest(BaseRutas):
    def test_coordinacion_crea_y_sincroniza(self):
        self.entrar(self.coord)
        respuesta = self.client.post('/programacion/asignaciones', data=self.form(), follow_redirects=True)
        self.assertIn('Programaste a Ana Sistemas en la ficha 2900001', self.texto(respuesta))
        asig = AsignacionProgramacion.query.one()
        self.assertEqual(asig.creado_por_id, self.coord.id)
        self.assertEqual(FichaCompetenciaProgramacion.query.one().fecha_fin, date(2026, 11, 21))

    def test_redireccion_conserva_vista_y_equipo(self):
        self.entrar(self.coord)
        respuesta = self.client.post('/programacion/asignaciones',
                                     data=self.form(vista='mes', equipo=str(self.sistemas.id)))
        self.assertIn('vista=mes', respuesta.headers['Location'])
        self.assertIn(f'equipo={self.sistemas.id}', respuesta.headers['Location'])

    def test_entrada_vacia_e_invalida_muestran_mensaje(self):
        self.entrar(self.coord)
        respuesta = self.client.post('/programacion/asignaciones', data=self.form(competencia=''), follow_redirects=True)
        self.assertIn('Escribe o elige la competencia', self.texto(respuesta))
        respuesta = self.client.post('/programacion/asignaciones', data=self.form(fecha_fin='2026-11-01'), follow_redirects=True)
        self.assertIn('anterior a la de inicio', self.texto(respuesta))
        self.assertEqual(AsignacionProgramacion.query.count(), 0)

    def test_choque_se_informa(self):
        self.entrar(self.coord)
        self.client.post('/programacion/asignaciones', data=self.form())
        respuesta = self.client.post('/programacion/asignaciones',
                                     data=self.form(ficha_id=self.ficha_agr.id, competencia='Ética'), follow_redirects=True)
        self.assertIn('ya está programado', self.texto(respuesta))

    def test_colaborador_no_programa(self):
        self.entrar(self.ana)
        self.assertEqual(self.client.post('/programacion/asignaciones', data=self.form()).status_code, 403)

    def test_lider_programa_su_equipo_en_otra_ficha_y_externo_en_su_ficha(self):
        self.entrar(self.lider)
        self.client.post('/programacion/asignaciones', data=self.form(ficha_id=self.ficha_agr.id, competencia='Ética'))
        self.client.post('/programacion/asignaciones', data=self.form(instructor_id=self.beto.id, jornada='noche'))
        self.assertEqual(AsignacionProgramacion.query.count(), 2)

    def test_lider_no_programa_externo_en_ficha_ajena(self):
        self.entrar(self.lider)
        respuesta = self.client.post('/programacion/asignaciones', follow_redirects=True,
                                     data=self.form(instructor_id=self.beto.id, ficha_id=self.ficha_agr.id))
        self.assertIn('Solo puedes programar a instructores de tu equipo', self.texto(respuesta))
        self.assertEqual(AsignacionProgramacion.query.count(), 0)

    def test_editar_y_eliminar(self):
        asig = pi.guardar_asignacion(self.form(), None)
        self.entrar(self.coord)
        respuesta = self.client.post(f'/programacion/asignaciones/{asig.id}', follow_redirects=True,
                                     data=self.form(jornada='tarde'))
        self.assertIn('Guardaste los cambios', self.texto(respuesta))
        self.assertEqual(db.session.get(AsignacionProgramacion, asig.id).jornada, 'tarde')
        respuesta = self.client.post(f'/programacion/asignaciones/{asig.id}', follow_redirects=True,
                                     data=self.form(jornada='mediodia'))
        self.assertIn('Elige la jornada', self.texto(respuesta))
        respuesta = self.client.post(f'/programacion/asignaciones/{asig.id}/eliminar', data=self.form(), follow_redirects=True)
        self.assertIn('Quitaste la asignación de Ana Sistemas', self.texto(respuesta))
        self.assertEqual(AsignacionProgramacion.query.count(), 0)

    def test_editar_inexistente_o_sin_permiso(self):
        asig = pi.guardar_asignacion(self.form(instructor_id=self.beto.id, ficha_id=self.ficha_agr.id), None)
        self.entrar(self.coord)
        self.assertEqual(self.client.post('/programacion/asignaciones/999', data=self.form()).status_code, 404)
        self.entrar(self.lider)
        self.assertEqual(self.client.post(f'/programacion/asignaciones/{asig.id}/eliminar').status_code, 403)
        self.entrar(self.ana)
        self.assertEqual(self.client.post(f'/programacion/asignaciones/{asig.id}', data=self.form()).status_code, 403)


class UtilidadesRutasTest(unittest.TestCase):
    def test_rangos_y_titulos(self):
        from app.routes.programacion import rango_de_vista, titulo_de_rango, _entero
        self.assertEqual(rango_de_vista('semana', date(2026, 11, 18)),
                         (date(2026, 11, 16), date(2026, 11, 21), date(2026, 11, 9), date(2026, 11, 23)))
        self.assertEqual(rango_de_vista('mes', date(2026, 12, 10)),
                         (date(2026, 12, 1), date(2026, 12, 31), date(2026, 11, 1), date(2027, 1, 1)))
        self.assertEqual(titulo_de_rango('semana', date(2026, 11, 30), date(2026, 12, 5)),
                         'Semana del 30 de noviembre al 5 de diciembre de 2026')
        self.assertEqual(titulo_de_rango('mes', date(2026, 12, 1), date(2026, 12, 31)), 'Diciembre de 2026')
        self.assertEqual((_entero('4'), _entero(''), _entero('x'), _entero(None)), (4, None, None, None))


class EquiposTest(BaseRutas):
    def test_solo_coordinacion_entra(self):
        self.entrar(self.lider)
        self.assertEqual(self.client.get('/programacion/equipos/').status_code, 403)
        self.client.get('/logout')
        with self.client.session_transaction() as sess:
            sess.clear()
        self.assertEqual(self.client.get('/programacion/equipos/').status_code, 302)

    def test_listar_y_crear_con_lider(self):
        self.entrar(self.coord)
        html = self.texto(self.client.get('/programacion/equipos/'))
        self.assertIn('Equipos ejecutores', html)
        self.assertIn('sin equipo', html)
        respuesta = self.client.post('/programacion/equipos/', follow_redirects=True,
                                     data={'nombre': '  Contabilidad  ', 'descripcion': 'Área contable', 'lider_id': self.beto.id})
        self.assertIn('Creaste el equipo Contabilidad', self.texto(respuesta))
        equipo = EquipoEjecutor.query.filter_by(nombre='Contabilidad').one()
        self.assertEqual(equipo.lider_id, self.beto.id)
        self.assertEqual(db.session.get(Instructor, self.beto.id).equipo_id, equipo.id)

    def test_crear_validaciones(self):
        self.entrar(self.coord)
        casos = [({'nombre': ''}, 'Escribe el nombre'), ({'nombre': 'sistemas'}, 'Ya existe'),
                 ({'nombre': 'Nuevo', 'lider_id': '999'}, 'no existe o está inactivo')]
        for datos, mensaje in casos:
            with self.subTest(datos=datos):
                self.assertIn(mensaje, self.texto(self.client.post('/programacion/equipos/', data=datos, follow_redirects=True)))
        self.assertEqual(EquipoEjecutor.query.count(), 2)

    def test_editar_validaciones_y_quitar_lider(self):
        self.entrar(self.coord)
        url = f'/programacion/equipos/{self.sistemas.id}'
        self.assertIn('no puede quedar vacío', self.texto(self.client.post(url, data={'nombre': ''}, follow_redirects=True)))
        self.assertIn('Ya existe', self.texto(self.client.post(url, data={'nombre': 'Agrícola'}, follow_redirects=True)))
        self.assertIn('no existe', self.texto(self.client.post(url, data={'nombre': 'Sistemas', 'lider_id': 'x'}, follow_redirects=True)))
        respuesta = self.client.post(url, data={'nombre': 'Sistemas y TIC', 'lider_id': ''}, follow_redirects=True)
        self.assertIn('Guardaste los cambios del equipo Sistemas y TIC', self.texto(respuesta))
        self.assertIsNone(db.session.get(EquipoEjecutor, self.sistemas.id).lider_id)
        self.assertEqual(self.client.post('/programacion/equipos/999', data={'nombre': 'X'}).status_code, 404)

    def test_archivar_y_reactivar(self):
        self.entrar(self.coord)
        url = f'/programacion/equipos/{self.agricola.id}/estado'
        self.assertIn('quedó archivado', self.texto(self.client.post(url, follow_redirects=True)))
        self.assertIn('Archivado', self.texto(self.client.get('/programacion/equipos/')))
        self.assertIn('quedó activo', self.texto(self.client.post(url, follow_redirects=True)))

    def test_asignar_miembro(self):
        self.entrar(self.coord)
        url = '/programacion/equipos/miembros'
        self.assertIn('Elige un instructor activo', self.texto(self.client.post(url, data={}, follow_redirects=True)))
        self.assertIn('Elige un equipo activo', self.texto(self.client.post(
            url, data={'instructor_id': self.ana.id, 'equipo_id': 'x'}, follow_redirects=True)))
        respuesta = self.client.post(url, data={'instructor_id': self.ana.id, 'equipo_id': self.agricola.id}, follow_redirects=True)
        self.assertIn('Ana Sistemas quedó al equipo Agrícola', self.texto(respuesta))
        # Quien lidera y se queda en su equipo conserva el liderazgo.
        self.client.post(url, data={'instructor_id': self.lider.id, 'equipo_id': self.sistemas.id})
        self.assertEqual(db.session.get(EquipoEjecutor, self.sistemas.id).lider_id, self.lider.id)
        # Quien lidera y sale del equipo deja de liderarlo.
        self.client.post(url, data={'instructor_id': self.lider.id, 'equipo_id': ''})
        self.assertIsNone(db.session.get(EquipoEjecutor, self.sistemas.id).lider_id)
        self.assertIsNone(db.session.get(Instructor, self.lider.id).equipo_id)


class AdminPerfilTest(BaseRutas):
    def test_admin_cambia_perfil(self):
        self.entrar(self.admin)
        html = self.texto(self.client.get('/admin/instructores'))
        self.assertIn('Coordinación', html)
        self.assertIn('Sistemas', html)
        url = f'/admin/instructores/{self.ana.id}/rol'
        self.assertIn('ahora tiene el perfil Coordinación',
                      self.texto(self.client.post(url, data={'rol': 'coordinacion'}, follow_redirects=True)))
        self.assertTrue(db.session.get(Instructor, self.ana.id).es_coordinacion)
        self.assertIn('Elige un perfil válido', self.texto(self.client.post(url, data={'rol': 'jefe'}, follow_redirects=True)))
        self.assertIn('No puedes quitarte', self.texto(self.client.post(
            f'/admin/instructores/{self.admin.id}/rol', data={'rol': 'colaborador'}, follow_redirects=True)))
        self.assertEqual(self.client.post('/admin/instructores/999/rol', data={'rol': 'admin'}).status_code, 404)

    def test_coordinacion_no_es_admin(self):
        self.entrar(self.coord)
        self.assertEqual(self.client.get('/admin/instructores').status_code, 403)
        html = self.texto(self.client.get('/programacion/'))
        self.assertIn('<small>Coordinación</small>', html)


if __name__ == '__main__':
    unittest.main()
