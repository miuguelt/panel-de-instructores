import unittest
from datetime import date, timedelta

from app import create_app, db
from app.models import (
    Aprendiz,
    ConfiguracionRanking,
    Ficha,
    Grupo,
    GrupoAprendiz,
    Instructor,
    IntercambioAseo,
    TurnoAseo,
)
from app.models.aseo import ContadorAseo
from app.services.aseo import (
    aprendices_activos,
    asignar_o_actualizar_turno,
    datos_transparencia,
    desvincular_aprendiz_de_turnos_futuros,
    generar_turnos,
    reemplazar_aprendices,
)
from app.services.grupo_service import (
    crear_grupo_manual,
    crear_grupos_aleatorios,
    desvincular_aprendiz_de_grupos,
    editar_grupo,
)
from app.services.permisos import (
    cambiar_estado_activo_aprendiz,
    configurar_rol_aprendiz,
)
from app.services.ranking import calcular_ranking


class DeshabilitarAprendicesTestCase(unittest.TestCase):
    """Pruebas completas de deshabilitación de aprendices para ranking y aseo."""

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

        self.instructor = Instructor(
            nombre='Instructor Titular',
            correo='titular@sena.edu.co',
            rol='instructor',
            auth_version=1,
        )
        self.instructor.set_password('clave-segura')

        self.otro_instructor = Instructor(
            nombre='Otro Instructor',
            correo='otro@sena.edu.co',
            rol='instructor',
            auth_version=1,
        )
        self.otro_instructor.set_password('clave-segura')

        db.session.add_all([self.instructor, self.otro_instructor])
        db.session.flush()

        self.ficha = Ficha(
            codigo='2888999',
            nombre_programa='ADSO',
            instructor_id=self.instructor.id,
        )
        self.otra_ficha = Ficha(
            codigo='2888000',
            nombre_programa='ADSO Otra',
            instructor_id=self.otro_instructor.id,
        )
        db.session.add_all([self.ficha, self.otra_ficha])
        db.session.flush()

        self.ap1 = Aprendiz(
            documento='101',
            nombre='Camilo',
            apellidos='Alvarez',
            estado='EN_FORMACION',
            ficha_id=self.ficha.id,
        )
        self.ap2 = Aprendiz(
            documento='102',
            nombre='Beatriz',
            apellidos='Bernal',
            estado='EN_FORMACION',
            ficha_id=self.ficha.id,
        )
        self.ap3 = Aprendiz(
            documento='103',
            nombre='Carlos',
            apellidos='Castro',
            estado='EN_FORMACION',
            ficha_id=self.ficha.id,
        )
        self.ap_ajeno = Aprendiz(
            documento='999',
            nombre='Zulma',
            apellidos='Zapata',
            estado='EN_FORMACION',
            ficha_id=self.otra_ficha.id,
        )
        db.session.add_all([self.ap1, self.ap2, self.ap3, self.ap_ajeno])
        db.session.add(ConfiguracionRanking(ficha_id=self.ficha.id))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _cliente_autenticado(self, instructor=None):
        from flask import g
        g.pop('_login_user', None)
        inst = instructor or self.instructor
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = inst.get_id()
            sesion['_fresh'] = True
        return cliente

    def test_modelo_aprendiz_activo_por_defecto_y_metodos(self):
        self.assertTrue(self.ap1.activo)
        self.assertFalse(self.ap1.deshabilitado)
        self.assertTrue(self.ap1.en_formacion)

        self.ap1.deshabilitar()
        self.assertFalse(self.ap1.activo)
        self.assertTrue(self.ap1.deshabilitado)
        self.assertFalse(self.ap1.en_formacion)

        self.ap1.habilitar()
        self.assertTrue(self.ap1.activo)
        self.assertFalse(self.ap1.deshabilitado)
        self.assertTrue(self.ap1.en_formacion)

    def test_query_en_formacion_filtra_solo_activos_por_defecto(self):
        aprendices = Aprendiz.query_en_formacion(self.ficha.id).all()
        self.assertEqual(len(aprendices), 3)

        self.ap2.deshabilitar()
        db.session.commit()

        activos = Aprendiz.query_en_formacion(self.ficha.id).all()
        self.assertEqual([a.id for a in activos], [self.ap1.id, self.ap3.id])

        todos = Aprendiz.query_en_formacion(self.ficha.id, solo_activos=False).all()
        self.assertEqual(len(todos), 3)

    def test_aprendiz_deshabilitado_no_aparece_en_ranking(self):
        filas, _ = calcular_ranking(self.ficha.id)
        ids_en_ranking = [fila['aprendiz'].id for fila in filas]
        self.assertIn(self.ap2.id, ids_en_ranking)

        # Deshabilitar ap2
        cambiar_estado_activo_aprendiz(self.ficha.id, self.ap2.id, activo=False)
        db.session.commit()

        filas_desp, _ = calcular_ranking(self.ficha.id)
        ids_desp = [fila['aprendiz'].id for fila in filas_desp]
        self.assertNotIn(self.ap2.id, ids_desp)
        self.assertIn(self.ap1.id, ids_desp)
        self.assertIn(self.ap3.id, ids_desp)

        # Habilitar ap2 nuevamente
        cambiar_estado_activo_aprendiz(self.ficha.id, self.ap2.id, activo=True)
        db.session.commit()

        filas_react, _ = calcular_ranking(self.ficha.id)
        ids_react = [fila['aprendiz'].id for fila in filas_react]
        self.assertIn(self.ap2.id, ids_react)

    def test_aprendiz_deshabilitado_no_aparece_en_aseo_ni_en_generacion(self):
        activos_inicio = aprendices_activos(self.ficha.id)
        self.assertEqual(len(activos_inicio), 3)

        cambiar_estado_activo_aprendiz(self.ficha.id, self.ap3.id, activo=False)
        db.session.commit()

        activos_desp = aprendices_activos(self.ficha.id)
        self.assertEqual([a.id for a in activos_desp], [self.ap1.id, self.ap2.id])

        # Transparencia tampoco incluye al deshabilitado en la tabla de equidad
        datos = datos_transparencia(self.ficha.id)
        ids_equidad = [fila['aprendiz'].id for fila in datos['equidad']]
        self.assertNotIn(self.ap3.id, ids_equidad)
        self.assertIn(self.ap1.id, ids_equidad)
        self.assertIn(self.ap2.id, ids_equidad)

    def test_deshabilitar_aprendiz_reemplaza_turnos_futuros_pendientes(self):
        hoy = date.today()
        fecha_turno = hoy + timedelta(days=2)
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_turno,
            aprendiz_1_id=self.ap1.id,
            aprendiz_2_id=self.ap2.id,
            estado='programado',
        )
        db.session.add(turno)
        db.session.commit()

        # Deshabilitar al aprendiz 1: debe ser reemplazado automáticamente por el aprendiz 3
        cambiar_estado_activo_aprendiz(self.ficha.id, self.ap1.id, activo=False)
        db.session.commit()

        db.session.refresh(turno)
        self.assertNotEqual(turno.aprendiz_1_id, self.ap1.id)
        self.assertEqual(turno.aprendiz_1_id, self.ap3.id)
        self.assertEqual(turno.aprendiz_2_id, self.ap2.id)

    def test_desvincular_turnos_futuros_cancela_si_no_hay_candidatos(self):
        # Deshabilitar a dos de tres aprendices
        self.ap2.deshabilitar()
        self.ap3.deshabilitar()
        db.session.commit()

        hoy = date.today()
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=hoy + timedelta(days=1),
            aprendiz_1_id=self.ap1.id,
            aprendiz_2_id=self.ap2.id,
            estado='programado',
        )
        db.session.add(turno)
        db.session.commit()

        # Ahora deshabilitamos a ap1; no queda nadie disponible, el turno debe eliminarse
        desvincular_aprendiz_de_turnos_futuros(self.ficha.id, self.ap1.id)
        db.session.commit()

        turno_db = TurnoAseo.query.filter_by(id=turno.id).first()
        self.assertIsNone(turno_db)

    def test_no_se_puede_asignar_manualmente_aprendiz_deshabilitado_a_turno(self):
        self.ap1.deshabilitar()
        db.session.commit()

        with self.assertRaises(ValueError):
            asignar_o_actualizar_turno(
                self.ficha.id,
                date.today() + timedelta(days=5),
                self.ap1.id,
                self.ap2.id,
            )

        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=date.today() + timedelta(days=6),
            aprendiz_1_id=self.ap2.id,
            aprendiz_2_id=self.ap3.id,
            estado='programado',
        )
        db.session.add(turno)
        db.session.commit()

        with self.assertRaises(ValueError):
            reemplazar_aprendices(turno, self.ap1, self.ap2)

    def test_deshabilitar_aprendiz_retira_rol_administrativo(self):
        configurar_rol_aprendiz(self.ficha.id, self.ap1.id, habilitar=True)
        db.session.commit()
        self.assertTrue(self.ap1.rol_administrativo)

        cambiar_estado_activo_aprendiz(self.ficha.id, self.ap1.id, activo=False)
        db.session.commit()

        self.assertFalse(self.ap1.activo)
        self.assertFalse(self.ap1.rol_administrativo)

        # No se puede asignar rol administrativo a un aprendiz deshabilitado
        with self.assertRaises(ValueError):
            configurar_rol_aprendiz(self.ficha.id, self.ap1.id, habilitar=True)

    def test_ruta_alternar_estado_activo_http(self):
        cliente = self._cliente_autenticado()

        # 1. Deshabilitar vía POST
        resp = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/aprendices/{self.ap1.id}/estado-activo',
            data={'accion': 'deshabilitar'},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        cuerpo = resp.get_data(as_text=True)
        self.assertIn('ha sido deshabilitado', cuerpo)

        db.session.refresh(self.ap1)
        self.assertFalse(self.ap1.activo)

        # 2. Habilitar vía POST
        resp2 = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/aprendices/{self.ap1.id}/estado-activo',
            data={'accion': 'habilitar'},
            follow_redirects=True,
        )
        self.assertEqual(resp2.status_code, 200)
        cuerpo2 = resp2.get_data(as_text=True)
        self.assertIn('ha sido habilitado', cuerpo2)

        db.session.refresh(self.ap1)
        self.assertTrue(self.ap1.activo)

    def test_ruta_rechaza_instructor_no_autorizado(self):
        cliente_ajeno = self._cliente_autenticado(self.otro_instructor)

        resp = cliente_ajeno.post(
            f'/instructor/fichas/{self.ficha.id}/aprendices/{self.ap1.id}/estado-activo',
            data={'accion': 'deshabilitar'},
            follow_redirects=True,
        )
        self.assertIn('Ficha no encontrada', resp.get_data(as_text=True))

    def test_ruta_rechaza_aprendiz_ajeno(self):
        cliente_dueno = self._cliente_autenticado(self.instructor)
        resp = cliente_dueno.post(
            f'/instructor/fichas/{self.ficha.id}/aprendices/{self.ap_ajeno.id}/estado-activo',
            data={'accion': 'deshabilitar'},
            follow_redirects=True,
        )
        self.assertIn('no pertenece a esta ficha', resp.get_data(as_text=True))

    def test_vistas_aprendices_y_configuracion_renderizan_botones_y_estado(self):
        self.ap2.deshabilitar()
        db.session.commit()

        cliente = self._cliente_autenticado()

        # Vista directorio de aprendices
        resp_dir = cliente.get(f'/instructor/fichas/{self.ficha.id}/aprendices')
        self.assertEqual(resp_dir.status_code, 200)
        cuerpo_dir = resp_dir.get_data(as_text=True)
        self.assertIn('Deshabilitado', cuerpo_dir)
        self.assertIn('Habilitar', cuerpo_dir)

        # Vista configuración de aprendices
        resp_cfg = cliente.get(f'/instructor/fichas/{self.ficha.id}/aprendices/configuracion')
        self.assertEqual(resp_cfg.status_code, 200)
        cuerpo_cfg = resp_cfg.get_data(as_text=True)
        self.assertIn('Participación en ranking', cuerpo_cfg)
        self.assertIn('Deshabilitado', cuerpo_cfg)

    def test_aprendiz_admin_autorizado_en_rutas_aseo(self):
        from flask import session
        from app.routes.aseo import _aprendiz_admin_autorizado

        with self.app.test_request_context():
            self.assertIsNone(_aprendiz_admin_autorizado(self.ficha.id))

        configurar_rol_aprendiz(self.ficha.id, self.ap1.id, habilitar=True)
        db.session.commit()

        with self.app.test_request_context():
            session['aprendiz_documento'] = self.ap1.documento
            session['aprendiz_ficha_id'] = self.ficha.id
            actor = _aprendiz_admin_autorizado(self.ficha.id)
            self.assertIsNotNone(actor)
            self.assertEqual(actor.id, self.ap1.id)

        self.ap1.deshabilitar()
        db.session.commit()

        with self.app.test_request_context():
            session['aprendiz_documento'] = self.ap1.documento
            session['aprendiz_ficha_id'] = self.ficha.id
            self.assertIsNone(_aprendiz_admin_autorizado(self.ficha.id))

    def test_query_llamado_lista_excluye_deshabilitados_por_defecto(self):
        llamado_inicio = Aprendiz.query_llamado_lista(self.ficha.id).all()
        self.assertEqual(len(llamado_inicio), 3)

        cambiar_estado_activo_aprendiz(self.ficha.id, self.ap2.id, activo=False)
        db.session.commit()

        llamado_desp = Aprendiz.query_llamado_lista(self.ficha.id).all()
        self.assertEqual([a.id for a in llamado_desp], [self.ap1.id, self.ap3.id])

        llamado_todos = Aprendiz.query_llamado_lista(self.ficha.id, solo_activos=False).all()
        self.assertEqual(len(llamado_todos), 3)

    def test_llamado_a_lista_http_excluye_aprendiz_deshabilitado(self):
        cliente = self._cliente_autenticado()

        cambiar_estado_activo_aprendiz(self.ficha.id, self.ap2.id, activo=False)
        db.session.commit()

        resp_get = cliente.get(f'/instructor/fichas/{self.ficha.id}/asistencia')
        self.assertEqual(resp_get.status_code, 200)
        cuerpo_get = resp_get.get_data(as_text=True)
        self.assertIn(self.ap1.nombre, cuerpo_get)
        self.assertIn(self.ap3.nombre, cuerpo_get)
        self.assertNotIn(f'name="asistencia_{self.ap2.id}"', cuerpo_get)

        resp_post = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/asistencia',
            data={
                'fecha': date.today().isoformat(),
                f'asistencia_{self.ap1.id}': 'ASISTE',
                f'asistencia_{self.ap3.id}': 'ASISTE',
            },
            follow_redirects=True,
        )
        self.assertEqual(resp_post.status_code, 200)
        cuerpo_post = resp_post.get_data(as_text=True)
        self.assertIn('Asistencia guardada correctamente', cuerpo_post)

    def test_deshabilitar_aprendiz_desvincula_de_grupos(self):
        grupo = Grupo(ficha_id=self.ficha.id, nombre='Equipo 1', activo=True)
        db.session.add(grupo)
        db.session.flush()
        db.session.add(GrupoAprendiz(grupo_id=grupo.id, aprendiz_id=self.ap1.id))
        db.session.add(GrupoAprendiz(grupo_id=grupo.id, aprendiz_id=self.ap2.id))
        db.session.commit()

        self.assertEqual(len(grupo.aprendices), 2)
        self.assertIn(self.ap2, grupo.aprendices)

        cambiar_estado_activo_aprendiz(self.ficha.id, self.ap2.id, activo=False)
        db.session.commit()

        db.session.refresh(grupo)
        self.assertEqual(len(grupo.aprendices), 1)
        self.assertNotIn(self.ap2, grupo.aprendices)
        self.assertIn(self.ap1, grupo.aprendices)

    def test_no_se_puede_asignar_aprendiz_deshabilitado_a_grupos(self):
        self.ap2.deshabilitar()
        db.session.commit()

        with self.assertRaisesRegex(ValueError, 'deshabilitados'):
            crear_grupos_aleatorios(self.ficha.id, [self.ap1.id, self.ap2.id], tamano_grupo=2)

        with self.assertRaisesRegex(ValueError, 'deshabilitados'):
            crear_grupo_manual(self.ficha.id, 'Equipo Beta', [self.ap1.id, self.ap2.id])

        grupo = Grupo(ficha_id=self.ficha.id, nombre='Equipo Gamma', activo=True)
        db.session.add(grupo)
        db.session.flush()
        db.session.add(GrupoAprendiz(grupo_id=grupo.id, aprendiz_id=self.ap1.id))
        db.session.commit()

        with self.assertRaisesRegex(ValueError, 'deshabilitados'):
            editar_grupo(grupo.id, 'Equipo Gamma', [self.ap1.id, self.ap2.id])

    def test_rutas_grupos_excluyen_y_rechazan_aprendices_deshabilitados(self):
        cliente = self._cliente_autenticado()
        self.ap3.deshabilitar()
        db.session.commit()

        resp = cliente.get(f'/instructor/fichas/{self.ficha.id}/grupos')
        self.assertEqual(resp.status_code, 200)
        cuerpo = resp.get_data(as_text=True)
        self.assertIn(self.ap1.nombre, cuerpo)
        self.assertNotIn(self.ap3.nombre, cuerpo)
        self.assertNotIn(f'name="aprendices_ids[]" value="{self.ap3.id}"', cuerpo)

        resp_post = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/grupos/generar',
            data={
                'tamano_grupo': '2',
                'aprendices_ids[]': [self.ap1.id, self.ap3.id],
            },
            follow_redirects=True,
        )
        self.assertIn('No se pueden asignar aprendices deshabilitados', resp_post.get_data(as_text=True))

    def test_deshabilitar_aprendiz_cancela_intercambios_pendientes_aseo(self):
        hoy = date.today()
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=hoy + timedelta(days=3),
            aprendiz_1_id=self.ap1.id,
            aprendiz_2_id=self.ap2.id,
            estado='programado',
        )
        db.session.add(turno)
        db.session.flush()

        intercambio = IntercambioAseo(
            turno_id=turno.id,
            aprendiz_solicita_id=self.ap1.id,
            aprendiz_recibe_id=self.ap3.id,
            estado='pendiente',
        )
        db.session.add(intercambio)
        db.session.commit()

        cambiar_estado_activo_aprendiz(self.ficha.id, self.ap1.id, activo=False)
        db.session.commit()

        db.session.refresh(intercambio)
        self.assertEqual(intercambio.estado, 'rechazado')


if __name__ == '__main__':
    unittest.main()
