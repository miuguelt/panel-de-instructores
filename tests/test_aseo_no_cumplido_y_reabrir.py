"""Pruebas para marcado como no cumplido, cumplimiento individual y reapertura de turnos de aseo."""

from datetime import date, timedelta
import unittest

from app import create_app, db
from app.models import (
    Aprendiz,
    ConfiguracionAlertas,
    ConfiguracionRanking,
    Ficha,
    Instructor,
    TurnoAseo,
)
from app.services.aseo import (
    completar_turno,
    generar_turnos,
    marcar_no_cumplido,
    reabrir_turno,
    recalcular_contadores,
)
from app.services.festivos import es_festivo_colombia
from tests.test_aseo_equidad import fechas_futuras


class TestAseoNoCumplidoYReabrir(unittest.TestCase):
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
            nombre='Instructor Aseo',
            correo='aseo_test@sena.edu.co',
            rol='admin',
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='2888888',
            nombre_programa='ADSO',
            instructor_id=self.instructor.id,
            fecha_inicio=date.today() - timedelta(days=30),
            fecha_fin=None,
        )
        db.session.add(self.ficha)
        db.session.flush()

        self.aprendices = []
        for i, nombre in enumerate(('Ana', 'Bruno', 'Carmen', 'Diego', 'Elena', 'Felipe'), start=1):
            aprendiz = Aprendiz(
                documento=f'200{i}',
                nombre=nombre,
                apellidos=f'Apellido {i}',
                estado='EN_FORMACION',
                ficha_id=self.ficha.id,
            )
            db.session.add(aprendiz)
            self.aprendices.append(aprendiz)

        db.session.add(ConfiguracionAlertas(ficha_id=self.ficha.id))
        db.session.add(ConfiguracionRanking(ficha_id=self.ficha.id))
        db.session.commit()

        self.fechas = fechas_futuras(5)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _cliente_instructor(self):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True
        return cliente

    def _cliente_aprendiz(self, aprendiz):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = aprendiz.documento
            sesion['aprendiz_ficha_id'] = self.ficha.id
        return cliente

    def test_marcar_no_cumplido_actualiza_estado_y_reprograma(self):
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=self.fechas[0],
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        marcar_no_cumplido(turno, observacion='El aula no fue aseada.')
        db.session.commit()

        self.assertEqual(turno.estado, 'no_cumplido')
        self.assertFalse(turno.completado_1)
        self.assertFalse(turno.completado_2)
        self.assertIsNotNone(turno.completado_en)
        self.assertIn('El aula no fue aseada.', turno.observacion)

        # Los contadores deben seguir en 0
        contadores = recalcular_contadores(self.ficha.id)
        self.assertEqual(contadores[self.aprendices[0].id].veces_aseo, 0)
        self.assertEqual(contadores[self.aprendices[1].id].veces_aseo, 0)

        # Se deben haber creado turnos de reposición para quienes no cumplieron
        reposiciones = TurnoAseo.query.filter(
            TurnoAseo.ficha_id == self.ficha.id,
            TurnoAseo.fecha > self.fechas[0],
            TurnoAseo.estado == 'programado',
        ).all()
        self.assertTrue(len(reposiciones) >= 1)
        aprendices_repuestos = {
            r.aprendiz_1_id for r in reposiciones
        } | {
            r.aprendiz_2_id for r in reposiciones
        }
        self.assertIn(self.aprendices[0].id, aprendices_repuestos)
        self.assertIn(self.aprendices[1].id, aprendices_repuestos)

    def test_reabrir_turno_restablece_a_programado_y_recalcula(self):
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=self.fechas[0],
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        # Completamos el turno
        completar_turno(turno, completado_1=True, completado_2=True)
        db.session.commit()
        contadores = recalcular_contadores(self.ficha.id)
        self.assertEqual(contadores[self.aprendices[0].id].veces_aseo, 1)

        # Reabrimos el turno
        reabrir_turno(turno)
        db.session.commit()

        self.assertEqual(turno.estado, 'programado')
        self.assertIsNone(turno.completado_1)
        self.assertIsNone(turno.completado_2)
        self.assertIsNone(turno.completado_en)

        # El contador vuelve a 0
        contadores = recalcular_contadores(self.ficha.id)
        self.assertEqual(contadores[self.aprendices[0].id].veces_aseo, 0)

    def test_completar_turno_individual_reprograma_solo_al_no_cumplido(self):
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=self.fechas[0],
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        # Aprendiz 1 cumplió, Aprendiz 2 no cumplió
        completar_turno(turno, completado_1=True, completado_2=False)
        db.session.commit()

        self.assertEqual(turno.estado, 'cumplido')
        self.assertTrue(turno.completado_1)
        self.assertFalse(turno.completado_2)

        contadores = recalcular_contadores(self.ficha.id)
        self.assertEqual(contadores[self.aprendices[0].id].veces_aseo, 1)
        self.assertEqual(contadores[self.aprendices[1].id].veces_aseo, 0)

        # Se debe haber programado reposición para el Aprendiz 2, pero no para el Aprendiz 1
        reposicion_ap2 = TurnoAseo.query.filter(
            TurnoAseo.ficha_id == self.ficha.id,
            TurnoAseo.fecha > self.fechas[0],
            TurnoAseo.estado == 'programado',
            db.or_(
                TurnoAseo.aprendiz_1_id == self.aprendices[1].id,
                TurnoAseo.aprendiz_2_id == self.aprendices[1].id,
            ),
        ).first()
        self.assertIsNotNone(reposicion_ap2)

    def test_completar_turno_ambos_falsos_marca_no_cumplido(self):
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=self.fechas[0],
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        completar_turno(turno, completado_1=False, completado_2=False)
        db.session.commit()

        self.assertEqual(turno.estado, 'no_cumplido')
        self.assertFalse(turno.completado_1)
        self.assertFalse(turno.completado_2)

    def test_generar_turnos_preserva_no_cumplido_historico(self):
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=self.fechas[0],
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='no_cumplido',
            generado_por='sistema',
            completado_1=False,
            completado_2=False,
        )
        db.session.add(turno)
        db.session.commit()

        # Al recalcular el mes, el turno no_cumplido no debe ser borrado ni sobreescrito
        resultado = generar_turnos(
            self.ficha.id,
            self.fechas[0],
            self.fechas[-1],
            recalcular_existentes=True,
        )
        db.session.commit()

        conservado = db.session.get(TurnoAseo, turno.id)
        self.assertEqual(conservado.estado, 'no_cumplido')
        self.assertEqual(conservado.aprendiz_1_id, self.aprendices[0].id)
        self.assertEqual(conservado.aprendiz_2_id, self.aprendices[1].id)

    def test_rutas_http_instructor_no_cumplir_y_reabrir(self):
        cliente = self._cliente_instructor()

        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=self.fechas[0],
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        # POST /no-cumplir
        resp_nc = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo/{turno.id}/no-cumplir',
            data={'observacion': 'Falta justificada'},
            follow_redirects=True,
        )
        self.assertEqual(resp_nc.status_code, 200)
        db.session.refresh(turno)
        self.assertEqual(turno.estado, 'no_cumplido')

        # POST /reabrir
        resp_re = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo/{turno.id}/reabrir',
            follow_redirects=True,
        )
        self.assertEqual(resp_re.status_code, 200)
        db.session.refresh(turno)
        self.assertEqual(turno.estado, 'programado')

        # POST /cumplir con casillas individuales
        resp_cu = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo/{turno.id}/cumplir',
            data={'completado_1': 'on'},  # aprendiz_2 queda desmarcado
            follow_redirects=True,
        )
        self.assertEqual(resp_cu.status_code, 200)
        db.session.refresh(turno)
        self.assertEqual(turno.estado, 'cumplido')
        self.assertTrue(turno.completado_1)
        self.assertFalse(turno.completado_2)

    def test_rutas_http_no_encontrado_redirecciona(self):
        cliente = self._cliente_instructor()

        resp_nc = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo/99999/no-cumplir',
            follow_redirects=True,
        )
        self.assertEqual(resp_nc.status_code, 200)

        resp_re = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo/99999/reabrir',
            follow_redirects=True,
        )
        self.assertEqual(resp_re.status_code, 200)

    def test_renderizado_vista_turnos_aseo_muestra_botones_y_totales(self):
        cliente = self._cliente_instructor()

        turno_prog = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=self.fechas[0],
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        turno_nocump = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=self.fechas[1],
            aprendiz_1_id=self.aprendices[2].id,
            aprendiz_2_id=self.aprendices[3].id,
            estado='no_cumplido',
            generado_por='sistema',
        )
        db.session.add_all([turno_prog, turno_nocump])
        db.session.commit()

        resp = cliente.get(f'/instructor/fichas/{self.ficha.id}/turnos-aseo?mes={self.fechas[0].strftime("%Y-%m")}')
        self.assertEqual(resp.status_code, 200)
        contenido = resp.get_data(as_text=True)
        self.assertIn('✓ Cumplir', contenido)
        self.assertIn('✗ No cumplió', contenido)
        self.assertIn('↺ Reabrir', contenido)
        self.assertIn('no cumplido', contenido)

    def test_rutas_http_aprendiz_admin_no_cumplir_y_reabrir(self):
        admin = self.aprendices[0]
        admin.rol_administrativo = True
        db.session.commit()

        cliente = self._cliente_aprendiz(admin)

        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=self.fechas[0],
            aprendiz_1_id=self.aprendices[1].id,
            aprendiz_2_id=self.aprendices[2].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        # POST no-cumplir como aprendiz
        resp_nc = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno.id}/no-cumplir',
            data={'origen': 'gestionar'},
            follow_redirects=True,
        )
        self.assertEqual(resp_nc.status_code, 200)
        db.session.refresh(turno)
        self.assertEqual(turno.estado, 'no_cumplido')

        # POST reabrir como aprendiz
        resp_re = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno.id}/reabrir',
            data={'origen': 'gestionar'},
            follow_redirects=True,
        )
        self.assertEqual(resp_re.status_code, 200)
        db.session.refresh(turno)
        self.assertEqual(turno.estado, 'programado')

    def test_rutas_http_aprendiz_sin_permiso_rechaza(self):
        otra_ficha = Ficha(
            codigo='9999999',
            nombre_programa='Otra',
            instructor_id=self.instructor.id,
        )
        db.session.add(otra_ficha)
        db.session.flush()
        otro_aprendiz = Aprendiz(
            documento='DOC-OTRA',
            nombre='Otro',
            apellidos='Otro',
            estado='EN_FORMACION',
            ficha_id=otra_ficha.id,
        )
        db.session.add(otro_aprendiz)
        db.session.commit()

        cliente = self._cliente_aprendiz(otro_aprendiz)

        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=self.fechas[0],
            aprendiz_1_id=self.aprendices[2].id,
            aprendiz_2_id=self.aprendices[3].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        # Intento de marcar no cumplir sin pertenecer a la ficha
        resp_nc = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno.id}/no-cumplir',
            follow_redirects=True,
        )
        self.assertEqual(resp_nc.status_code, 200)
        db.session.refresh(turno)
        self.assertEqual(turno.estado, 'programado')
