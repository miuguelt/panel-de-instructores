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
            f'?documento={self.aprendices[0].documento}',
            follow_redirects=True
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

    def test_recalcular_dias_faltantes_equilibra_cargas_segun_pesos_y_cumplidos(self):
        # Ana (0) y Bruno (1) ya cumplieron turno en el pasado
        fecha_pasada = date.today() - timedelta(days=2)
        self._crear_sesion(fecha_pasada)
        turno_pasado = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_pasada,
            aprendiz_1_id=self.aprendices[0].id, # Ana
            aprendiz_2_id=self.aprendices[1].id, # Bruno
            estado='cumplido',
            completado_1=True,
            completado_2=True,
        )
        db.session.add(turno_pasado)
        db.session.commit()

        # Creamos 2 fechas futuras (4 cupos)
        fecha_futura_1 = date.today() + timedelta(days=1)
        fecha_futura_2 = date.today() + timedelta(days=2)
        self._crear_sesion(fecha_futura_1)
        self._crear_sesion(fecha_futura_2)
        db.session.commit()

        resultado = generar_turnos(
            self.ficha.id,
            fecha_futura_1,
            fecha_futura_2,
            rng=random.Random(42),
        )
        db.session.commit()

        self.assertEqual(len(resultado['creados']), 2)
        asignados_futuros = set()
        for turno in resultado['creados']:
            asignados_futuros.add(turno.aprendiz_1_id)
            asignados_futuros.add(turno.aprendiz_2_id)

        # Los 4 aprendices restantes (Carmen, Diego, Elena, Felipe) deben recibir los 4 cupos
        ids_restantes = {a.id for a in self.aprendices[2:]}
        self.assertEqual(asignados_futuros, ids_restantes)
        # Ana y Bruno NO deben haber sido asignados en estos 2 días
        self.assertNotIn(self.aprendices[0].id, asignados_futuros)
        self.assertNotIn(self.aprendices[1].id, asignados_futuros)

    def test_recalcular_actualiza_turnos_programados_existentes(self):
        fecha_futura = date.today() + timedelta(days=3)
        self._crear_sesion(fecha_futura)
        # Turno programado inicialmente con Ana y Bruno
        turno_existente = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_futura,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno_existente)

        # Pero Ana y Bruno ya tienen 1 turno cumplido antes
        fecha_pasada = date.today() - timedelta(days=1)
        self._crear_sesion(fecha_pasada)
        turno_cumplido = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_pasada,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='cumplido',
            completado_1=True,
            completado_2=True,
        )
        db.session.add(turno_cumplido)
        db.session.commit()

        # Recalcular debe actualizar el turno existente programado
        resultado = generar_turnos(
            self.ficha.id,
            fecha_futura,
            fecha_futura,
            recalcular_existentes=True,
            rng=random.Random(15),
        )
        db.session.commit()

        self.assertEqual(len(resultado['recalculados']), 1)
        turno_actualizado = resultado['recalculados'][0]
        self.assertEqual(turno_actualizado.id, turno_existente.id)
        # Deben haber salido Ana y Bruno y entrado aprendices con carga 0
        self.assertFalse(turno_actualizado.incluye(self.aprendices[0].id))
        self.assertFalse(turno_actualizado.incluye(self.aprendices[1].id))

    def test_turnos_cumplidos_no_se_modifican_al_recalcular(self):
        fecha = date.today()
        self._crear_sesion(fecha)
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='cumplido',
            completado_1=True,
            completado_2=True,
        )
        db.session.add(turno)
        db.session.commit()

        resultado = generar_turnos(
            self.ficha.id,
            fecha,
            fecha,
            recalcular_existentes=True,
        )
        db.session.commit()

        self.assertEqual(len(resultado['creados']), 0)
        self.assertEqual(len(resultado['recalculados']), 0)
        self.assertEqual(resultado['cumplidos_conservados'], 1)
        turno_bd = db.session.get(TurnoAseo, turno.id)
        self.assertEqual(turno_bd.aprendiz_1_id, self.aprendices[0].id)
        self.assertEqual(turno_bd.aprendiz_2_id, self.aprendices[1].id)
        self.assertEqual(turno_bd.estado, 'cumplido')

    def test_respetar_ajustes_manuales_al_recalcular(self):
        fecha_futura = date.today() + timedelta(days=2)
        self._crear_sesion(fecha_futura)
        turno_manual = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_futura,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='instructor',
        )
        db.session.add(turno_manual)
        db.session.commit()

        resultado = generar_turnos(
            self.ficha.id,
            fecha_futura,
            fecha_futura,
            recalcular_existentes=True,
            respetar_manuales=True,
        )
        db.session.commit()

        self.assertEqual(len(resultado['creados']), 0)
        self.assertEqual(len(resultado['recalculados']), 0)
        self.assertEqual(resultado['omitidos_manuales'], 1)
        turno_bd = db.session.get(TurnoAseo, turno_manual.id)
        self.assertEqual(turno_bd.aprendiz_1_id, self.aprendices[0].id)
        self.assertEqual(turno_bd.aprendiz_2_id, self.aprendices[1].id)

    def test_recalcular_contadores_preserva_turnos_con_completado_nulo(self):
        # Simula turnos históricos donde completado_1 y completado_2 son None
        fecha_pasada = date.today() - timedelta(days=5)
        self._crear_sesion(fecha_pasada)
        turno_historico = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_pasada,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='cumplido',
            completado_1=None,
            completado_2=None,
        )
        db.session.add(turno_historico)
        db.session.commit()

        from app.services.aseo import recalcular_contadores
        contadores = recalcular_contadores(self.ficha.id)
        db.session.commit()

        self.assertEqual(contadores[self.aprendices[0].id].veces_aseo, 1)
        self.assertEqual(contadores[self.aprendices[1].id].veces_aseo, 1)
        self.assertEqual(contadores[self.aprendices[0].id].ultima_vez_aseo, fecha_pasada)
        self.assertEqual(contadores[self.aprendices[1].id].ultima_vez_aseo, fecha_pasada)

    def test_evita_repeticion_consecutiva(self):
        # 3 días seguidos con 6 aprendices
        fechas = [date.today() + timedelta(days=i) for i in range(1, 4)]
        for f in fechas:
            self._crear_sesion(f)
        db.session.commit()

        resultado = generar_turnos(
            self.ficha.id,
            fechas[0],
            fechas[-1],
            rng=random.Random(42),
        )
        db.session.commit()

        turnos = TurnoAseo.query.filter(
            TurnoAseo.ficha_id == self.ficha.id,
            TurnoAseo.fecha.between(fechas[0], fechas[-1]),
        ).order_by(TurnoAseo.fecha).all()

        for i in range(len(turnos) - 1):
            t1 = turnos[i]
            t2 = turnos[i + 1]
            interseccion = {t1.aprendiz_1_id, t1.aprendiz_2_id}.intersection(
                {t2.aprendiz_1_id, t2.aprendiz_2_id}
            )
            self.assertEqual(
                len(interseccion),
                0,
                f"El aprendiz {interseccion} repitió en días consecutivos: {t1.fecha} y {t2.fecha}"
            )

    def test_diversidad_parejas_evita_repetir_mismo_companero(self):
        # 6 sesiones = 2 ciclos completos para 6 aprendices
        fechas = [date.today() + timedelta(days=i) for i in range(1, 7)]
        for f in fechas:
            self._crear_sesion(f)
        db.session.commit()

        generar_turnos(
            self.ficha.id,
            fechas[0],
            fechas[-1],
            rng=random.Random(42),
        )
        db.session.commit()

        turnos = TurnoAseo.query.filter(
            TurnoAseo.ficha_id == self.ficha.id,
            TurnoAseo.fecha.between(fechas[0], fechas[-1]),
        ).order_by(TurnoAseo.fecha).all()

        parejas = set()
        for t in turnos:
            p = tuple(sorted((t.aprendiz_1_id, t.aprendiz_2_id)))
            parejas.add(p)

        # En 6 sesiones (2 rotaciones de 3 turnos), las 6 parejas deben ser todas distintas (máxima diversidad)
        self.assertEqual(len(parejas), 6, "No se diversificaron las parejas en los dos ciclos de rotación")

    def test_proteger_fechas_pasadas_al_recalcular_mes(self):
        fecha_pasada = date.today() - timedelta(days=3)
        self._crear_sesion(fecha_pasada)
        turno_pasado = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_pasada,
            aprendiz_1_id=self.aprendices[4].id,
            aprendiz_2_id=self.aprendices[5].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno_pasado)

        fecha_futura = date.today() + timedelta(days=2)
        self._crear_sesion(fecha_futura)
        db.session.commit()

        resultado = generar_turnos(
            self.ficha.id,
            fecha_pasada,
            fecha_futura,
            recalcular_existentes=True,
            proteger_pasados=True,
            rng=random.Random(99),
        )
        db.session.commit()

        turno_pasado_bd = db.session.get(TurnoAseo, turno_pasado.id)
        # El turno de la fecha pasada no debe haber sido sobreescrito
        self.assertEqual(turno_pasado_bd.aprendiz_1_id, self.aprendices[4].id)
        self.assertEqual(turno_pasado_bd.aprendiz_2_id, self.aprendices[5].id)

    def test_marcar_cumplido_persiste_y_afecta_recalculo_futuro(self):
        # 1. Creamos turno hoy con Ana (0) y Bruno (1)
        fecha_hoy = date.today()
        self._crear_sesion(fecha_hoy)
        turno_hoy = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_hoy,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno_hoy)
        db.session.commit()

        # 2. Marcamos cumplido vía cliente HTTP
        cliente = self._cliente_instructor()
        resp = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo/{turno_hoy.id}/cumplir',
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        # 3. Verificamos que se guardaron y persistieron los contadores
        c_ana = ContadorAseo.query.filter_by(aprendiz_id=self.aprendices[0].id).first()
        c_bruno = ContadorAseo.query.filter_by(aprendiz_id=self.aprendices[1].id).first()
        self.assertEqual(c_ana.veces_aseo, 1)
        self.assertEqual(c_bruno.veces_aseo, 1)
        self.assertEqual(c_ana.ultima_vez_aseo, fecha_hoy)
        self.assertEqual(c_bruno.ultima_vez_aseo, fecha_hoy)

        # 4. Creamos 2 sesiones futuras y recalculamos todo el rango (incluyendo hoy)
        f1 = fecha_hoy + timedelta(days=1)
        f2 = fecha_hoy + timedelta(days=2)
        self._crear_sesion(f1)
        self._crear_sesion(f2)
        db.session.commit()

        resultado = generar_turnos(
            self.ficha.id,
            fecha_hoy,
            f2,
            recalcular_existentes=True,
            rng=random.Random(10),
        )
        db.session.commit()

        # El turno cumplido de hoy se conservó intacto
        self.assertEqual(resultado['cumplidos_conservados'], 1)
        turno_hoy_bd = db.session.get(TurnoAseo, turno_hoy.id)
        self.assertEqual(turno_hoy_bd.estado, 'cumplido')
        self.assertEqual(turno_hoy_bd.aprendiz_1_id, self.aprendices[0].id)
        self.assertEqual(turno_hoy_bd.aprendiz_2_id, self.aprendices[1].id)

        # Y en los nuevos turnos futuros (4 cupos), Ana y Bruno NO deben estar porque ya tienen 1 cumplido
        asignados_futuros = set()
        for t in resultado['creados']:
            asignados_futuros.add(t.aprendiz_1_id)
            asignados_futuros.add(t.aprendiz_2_id)

        self.assertNotIn(self.aprendices[0].id, asignados_futuros)
        self.assertNotIn(self.aprendices[1].id, asignados_futuros)
        # Los 4 restantes (Carmen, Diego, Elena, Felipe) ocupan exactamente los 4 cupos
        self.assertEqual(asignados_futuros, {a.id for a in self.aprendices[2:]})


if __name__ == '__main__':
    unittest.main()
