import random
import unittest
from datetime import date, timedelta

from app import create_app, db
from app.models import (
    Aprendiz,
    ConfiguracionAlertas,
    ConfiguracionRanking,
    ContadorAseo,
    Ficha,
    Instructor,
    IntercambioAseo,
    RegistroAsistencia,
    SesionAsistencia,
    TurnoAseo,
)
from app.services.aseo import (
    aceptar_intercambio,
    completar_turno,
    generar_turnos,
    reemplazar_aprendices,
)


class TurnosAseoTestCase(unittest.TestCase):
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
            correo='aseo@sena.edu.co',
            rol='admin',
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()
        self.ficha = Ficha(
            codigo='2888888',
            nombre_programa='Análisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
            fecha_inicio=date.today(),
            fecha_fin=None,
        )
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendices = []
        for numero, nombre in enumerate(
            ('Ana', 'Bruno', 'Carmen', 'Diego', 'Elena', 'Felipe'), start=1
        ):
            aprendiz = Aprendiz(
                documento=f'200{numero}',
                nombre=nombre,
                apellidos=f'Apellido {numero}',
                estado='EN_FORMACION',
                ficha_id=self.ficha.id,
            )
            db.session.add(aprendiz)
            self.aprendices.append(aprendiz)
        db.session.add(ConfiguracionAlertas(ficha_id=self.ficha.id))
        db.session.add(ConfiguracionRanking(ficha_id=self.ficha.id))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _crear_sesion(self, fecha, ausentes=()):
        sesion = SesionAsistencia(ficha_id=self.ficha.id, fecha=fecha)
        db.session.add(sesion)
        db.session.flush()
        for aprendiz in self.aprendices:
            db.session.add(RegistroAsistencia(
                sesion_id=sesion.id,
                aprendiz_id=aprendiz.id,
                estado='FALTA' if aprendiz.id in ausentes else 'ASISTE',
            ))
        return sesion

    def _cliente_instructor(self):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True
        return cliente

    def test_generacion_por_rango_es_pareja_y_auditable(self):
        fechas = [date.today() + timedelta(days=numero) for numero in range(3)]
        for fecha in fechas:
            self._crear_sesion(fecha)
        db.session.commit()

        resultado = generar_turnos(
            self.ficha.id,
            fechas[0],
            fechas[-1],
            rng=random.Random(7),
        )
        db.session.commit()

        self.assertEqual(len(resultado['creados']), 3)
        asignaciones = {aprendiz.id: 0 for aprendiz in self.aprendices}
        for turno in TurnoAseo.query.all():
            asignaciones[turno.aprendiz_1_id] += 1
            asignaciones[turno.aprendiz_2_id] += 1
            self.assertIn('cola justa', turno.auditoria_1)
            self.assertIn('promedio', turno.auditoria_2)
        self.assertEqual(set(asignaciones.values()), {1})
        self.assertEqual(ContadorAseo.query.count(), 6)
        self.assertTrue(
            all(contador.veces_aseo == 0 for contador in ContadorAseo.query.all())
        )

    def test_ausentes_y_excluidos_no_entran_en_la_asignacion(self):
        fecha = date.today()
        ausente = self.aprendices[0]
        excluido = self.aprendices[1]
        self._crear_sesion(fecha, ausentes={ausente.id})
        from app.services.aseo import asegurar_contadores
        contadores = asegurar_contadores(self.ficha.id)
        contadores[excluido.id].excluido_hasta = fecha + timedelta(days=2)
        db.session.flush()
        resultado = generar_turnos(
            self.ficha.id,
            fecha,
            fecha,
            rng=random.Random(3),
        )
        turno = resultado['creados'][0]
        self.assertFalse(turno.incluye(ausente.id))
        self.assertFalse(turno.incluye(excluido.id))

    def test_cumplimiento_y_override_recalculan_contadores(self):
        fecha = date.today()
        self._crear_sesion(fecha)
        turno = generar_turnos(
            self.ficha.id, fecha, fecha, rng=random.Random(5)
        )['creados'][0]
        completar_turno(turno)
        db.session.commit()

        ids_originales = {turno.aprendiz_1_id, turno.aprendiz_2_id}
        for aprendiz_id in ids_originales:
            contador = ContadorAseo.query.filter_by(
                aprendiz_id=aprendiz_id
            ).first()
            self.assertEqual(contador.veces_aseo, 1)
        self.assertTrue(turno.completado_1)
        self.assertTrue(turno.completado_2)

        reemplazo = next(
            aprendiz for aprendiz in self.aprendices
            if aprendiz.id not in ids_originales
        )
        reemplazar_aprendices(turno, reemplazo, turno.aprendiz_2, 'Cambio acordado')
        db.session.commit()

        self.assertEqual(
            ContadorAseo.query.filter_by(
                aprendiz_id=reemplazo.id
            ).first().veces_aseo,
            1,
        )
        self.assertEqual(turno.generado_por, 'instructor')

    def test_ausente_no_suma_en_contador_y_conserva_puesto(self):
        fecha = date.today()
        ausente = self.aprendices[0]
        self._crear_sesion(fecha, ausentes={ausente.id})
        db.session.commit()

        turno = generar_turnos(
            self.ficha.id, fecha, fecha, rng=random.Random(9)
        )['creados'][0]
        if not turno.incluye(ausente.id):
            turno.aprendiz_1_id = ausente.id
            turno.aprendiz_2_id = self.aprendices[1].id
            db.session.flush()

        completar_turno(turno)
        db.session.commit()

        contador_ausente = ContadorAseo.query.filter_by(
            aprendiz_id=ausente.id
        ).first()
        self.assertEqual(contador_ausente.veces_aseo, 0)
        self.assertFalse(turno.incluye(ausente.id))
        self.assertTrue(turno.completado_1)
        self.assertTrue(turno.completado_2)
        reposicion = TurnoAseo.query.filter(
            TurnoAseo.ficha_id == self.ficha.id,
            TurnoAseo.fecha > fecha,
            db.or_(
                TurnoAseo.aprendiz_1_id == ausente.id,
                TurnoAseo.aprendiz_2_id == ausente.id,
            ),
        ).first()
        self.assertIsNotNone(reposicion)

    def test_intercambio_exige_doble_confirmacion_y_actualiza_turno(self):
        fecha = date.today() + timedelta(days=1)
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
        )
        db.session.add(turno)
        db.session.flush()
        intercambio = IntercambioAseo(
            turno_id=turno.id,
            aprendiz_solicita_id=self.aprendices[0].id,
            aprendiz_recibe_id=self.aprendices[2].id,
            confirma_solicita=True,
        )
        db.session.add(intercambio)
        db.session.flush()

        aceptar_intercambio(intercambio)
        db.session.commit()

        self.assertEqual(intercambio.estado, 'aceptado')
        self.assertTrue(intercambio.confirma_solicita)
        self.assertTrue(intercambio.confirma_recibe)
        self.assertTrue(turno.incluye(self.aprendices[2].id))
        self.assertFalse(turno.incluye(self.aprendices[0].id))
        self.assertEqual(turno.estado, 'intercambiado')

    def test_calendario_panel_y_generacion_http_responden(self):
        fecha = date.today() + timedelta(days=1)
        self._crear_sesion(fecha)
        db.session.commit()
        cliente = self._cliente_instructor()

        respuesta = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo/generar',
            data={
                'fecha_inicio': fecha.isoformat(),
                'fecha_fin': fecha.isoformat(),
            },
            follow_redirects=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('Turnos de aseo'.encode(), respuesta.data)
        self.assertEqual(TurnoAseo.query.count(), 1)

        panel = cliente.get(
            f'/aprendiz/{self.ficha.id}/panel'
            f'?documento={self.aprendices[0].documento}'
        )
        self.assertEqual(panel.status_code, 200)
        self.assertIn('Turno de aseo'.encode(), panel.data)

    def test_guardar_asistencia_crea_turno_del_dia_automaticamente(self):
        fecha = date.today()
        cliente = self._cliente_instructor()
        datos = {'fecha': fecha.isoformat()}
        for aprendiz in self.aprendices:
            datos[f'asistencia_{aprendiz.id}'] = 'ASISTE'

        respuesta = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/asistencia',
            data=datos,
            follow_redirects=True,
        )

        self.assertEqual(respuesta.status_code, 200)
        turno = TurnoAseo.query.filter_by(
            ficha_id=self.ficha.id, fecha=fecha
        ).first()
        self.assertIsNotNone(turno)
        self.assertEqual(turno.generado_por, 'sistema')

    def test_asistencia_reemplaza_ausente_y_reserva_reposicion(self):
        fecha = date.today()
        self._crear_sesion(fecha)
        turno_original = generar_turnos(
            self.ficha.id, fecha, fecha, rng=random.Random(11)
        )['creados'][0]
        db.session.commit()
        ausente_id = turno_original.aprendiz_1_id
        presente_id = turno_original.aprendiz_2_id

        cliente = self._cliente_instructor()
        datos = {'fecha': fecha.isoformat()}
        for aprendiz in self.aprendices:
            datos[f'asistencia_{aprendiz.id}'] = (
                'FALTA' if aprendiz.id == ausente_id else 'ASISTE'
            )

        cliente.post(
            f'/instructor/fichas/{self.ficha.id}/asistencia',
            data=datos,
            follow_redirects=True,
        )

        turno_despues = TurnoAseo.query.filter_by(
            ficha_id=self.ficha.id, fecha=fecha
        ).first()
        self.assertEqual(turno_despues.id, turno_original.id)
        self.assertFalse(turno_despues.incluye(ausente_id))
        self.assertTrue(turno_despues.incluye(presente_id))
        self.assertIn('Suplencia', turno_despues.auditoria_1 + (turno_despues.auditoria_2 or ''))

        reposicion = TurnoAseo.query.filter(
            TurnoAseo.ficha_id == self.ficha.id,
            TurnoAseo.fecha > fecha,
            TurnoAseo.estado.in_(('programado', 'intercambiado')),
            db.or_(
                TurnoAseo.aprendiz_1_id == ausente_id,
                TurnoAseo.aprendiz_2_id == ausente_id,
            ),
        ).first()
        self.assertIsNotNone(reposicion)
        self.assertIn('Reposición', (reposicion.auditoria_1 or '') + (reposicion.auditoria_2 or '') + (reposicion.observacion or ''))

    def test_transparencia_publica_responde(self):
        fecha = date.today() + timedelta(days=1)
        self._crear_sesion(fecha)
        db.session.commit()
        cliente = self.app.test_client()

        respuesta = cliente.get(
            f'/aprendiz/{self.ficha.id}/turnos-aseo'
            f'?documento={self.aprendices[0].documento}'
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('Turnos de aseo'.encode(), respuesta.data)
        self.assertIn('Tabla de equidad'.encode(), respuesta.data)

    def test_modificacion_asistencia_actualiza_contadores(self):
        fecha = date.today()
        self._crear_sesion(fecha)
        turno = generar_turnos(
            self.ficha.id, fecha, fecha, rng=random.Random(13)
        )['creados'][0]
        db.session.commit()

        completar_turno(turno)
        db.session.commit()

        contador_1 = ContadorAseo.query.filter_by(
            aprendiz_id=turno.aprendiz_1_id
        ).first()
        self.assertEqual(contador_1.veces_aseo, 1)
        self.assertTrue(turno.completado_1)

        sesion = SesionAsistencia.query.filter_by(
            ficha_id=self.ficha.id, fecha=fecha
        ).first()
        registro = RegistroAsistencia.query.filter_by(
            sesion_id=sesion.id, aprendiz_id=turno.aprendiz_1_id
        ).first()
        registro.estado = 'FALTA'
        db.session.flush()

        from app.services.aseo import ajustar_turno_por_asistencia
        ajustar_turno_por_asistencia(self.ficha.id, fecha)
        db.session.commit()

        db.session.refresh(turno)
        db.session.refresh(contador_1)
        self.assertFalse(turno.completado_1)
        self.assertEqual(contador_1.veces_aseo, 0)


if __name__ == '__main__':
    unittest.main()
