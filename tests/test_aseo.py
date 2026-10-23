import random
import unittest
from datetime import date, timedelta

from app import create_app, db
from app.models import (
    Aprendiz,
    ConfiguracionAlertas,
    ConfiguracionAseo,
    ConfiguracionRanking,
    ContadorAseo,
    Ficha,
    Instructor,
    IntercambioAseo,
    RegistroAsistencia,
    SesionAsistencia,
    TurnoAseo,
)
from app.models.corte import Corte
from app.services.aseo import (
    aceptar_intercambio,
    asignar_o_actualizar_turno,
    completar_turno,
    generar_turnos,
    reemplazar_aprendices,
)
from app.services.festivos import (
    es_festivo_colombia,
    obtener_festivos_colombia,
)
from app.services.permisos import cambiar_estado_activo_aprendiz, configurar_rol_aprendiz
from tests.test_aseo_equidad import fechas_futuras


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
        fechas = fechas_futuras(3)
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
        fecha = fechas_futuras(1)[0]
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
        fecha = fechas_futuras(1)[0]
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
        fecha = fechas_futuras(1)[0]
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

    def test_intercambio_vencido_no_se_puede_aceptar(self):
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=date.today() - timedelta(days=1),
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

        with self.assertRaisesRegex(ValueError, 'turno ya pasó'):
            aceptar_intercambio(intercambio)

        self.assertEqual(intercambio.estado, 'pendiente')
        self.assertTrue(turno.incluye(self.aprendices[0].id))
        self.assertFalse(turno.incluye(self.aprendices[2].id))

    def test_calendario_panel_y_generacion_http_responden(self):
        fecha = fechas_futuras(1)[0]
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
        self.assertIn('name="dias_semana_present"'.encode(), respuesta.data)
        self.assertIn('Sábado'.encode(), respuesta.data)
        self.assertIn('Domingo'.encode(), respuesta.data)
        self.assertEqual(TurnoAseo.query.count(), 1)

        sabado = date.today() + timedelta(days=1)
        while sabado.weekday() != 5 or es_festivo_colombia(sabado) or es_festivo_colombia(
            sabado + timedelta(days=1)
        ):
            sabado += timedelta(days=1)
        domingo = sabado + timedelta(days=1)
        self._crear_sesion(sabado)
        self._crear_sesion(domingo)
        db.session.commit()

        cliente.post(
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo/generar',
            data={'fecha_inicio': sabado.isoformat(), 'fecha_fin': domingo.isoformat()},
            follow_redirects=True,
        )
        self.assertIsNone(TurnoAseo.query.filter_by(
            ficha_id=self.ficha.id, fecha=sabado,
        ).first())
        self.assertIsNone(TurnoAseo.query.filter_by(
            ficha_id=self.ficha.id, fecha=domingo,
        ).first())

        respuesta_fin_de_semana = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo/generar',
            data={
                'fecha_inicio': sabado.isoformat(),
                'fecha_fin': domingo.isoformat(),
                'dias_semana_present': '1',
                'dias_semana': ['5', '6'],
            },
            follow_redirects=True,
        )
        self.assertEqual(respuesta_fin_de_semana.status_code, 200)
        self.assertEqual(TurnoAseo.query.filter(
            TurnoAseo.ficha_id == self.ficha.id,
            TurnoAseo.fecha.between(sabado, domingo),
        ).count(), 2)

        self.aprendices[0].rol_administrativo = True
        db.session.commit()
        cliente_aprendiz = self.app.test_client()
        with cliente_aprendiz.session_transaction() as datos_sesion:
            datos_sesion['aprendiz_documento'] = self.aprendices[0].documento
            datos_sesion['aprendiz_ficha_id'] = self.ficha.id
        respuesta_configuracion_dias = cliente_aprendiz.get(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/gestionar',
        )
        self.assertEqual(respuesta_configuracion_dias.status_code, 200)
        self.assertIn('name="dias_semana_present"'.encode(), respuesta_configuracion_dias.data)
        self.assertIn('Sábado'.encode(), respuesta_configuracion_dias.data)
        self.assertIn('Domingo'.encode(), respuesta_configuracion_dias.data)

        panel = cliente.get(
            f'/aprendiz/{self.ficha.id}/panel'
            f'?documento={self.aprendices[0].documento}',
            follow_redirects=True
        )
        self.assertEqual(panel.status_code, 200)
        self.assertIn('Turno de aseo'.encode(), panel.data)

    def test_guardar_asistencia_crea_turno_del_dia_automaticamente(self):
        fecha = fechas_futuras(1)[0]
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
        fecha = fechas_futuras(1)[0]
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
        fecha = fechas_futuras(1)[0]
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
        fechas = fechas_futuras(2)
        fecha_futura_1 = fechas[0]
        fecha_futura_2 = fechas[1]
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
        # La sesión debe caer en un día habilitado, incluso si la prueba corre un fin de semana.
        fecha_futura = fechas_futuras(1)[0]
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
        fecha = fechas_futuras(1)[0]
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
        fecha_futura = fechas_futuras(1)[0]
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
        fechas = fechas_futuras(3)
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
        # Seis días hábiles permiten dos ciclos completos para seis aprendices.
        fechas = fechas_futuras(6)
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

        self.assertEqual([turno.fecha for turno in turnos], fechas)
        parejas = {tuple(sorted((t.aprendiz_1_id, t.aprendiz_2_id))) for t in turnos}
        self.assertEqual(len(parejas), 6, "No se diversificaron las parejas en los dos ciclos de rotación")

    def test_proteger_fechas_pasadas_al_recalcular_mes(self):
        fecha_pasada = date.today() - timedelta(days=3)
        while fecha_pasada.weekday() >= 5 or es_festivo_colombia(fecha_pasada):
            fecha_pasada -= timedelta(days=1)
        self.ficha.fecha_inicio = fecha_pasada
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

        fecha_futura = fechas_futuras(1)[0]
        self._crear_sesion(fecha_futura)
        db.session.commit()
        anteriores = {c.name: getattr(turno_pasado, c.name) for c in TurnoAseo.__table__.columns}

        resultado = generar_turnos(
            self.ficha.id,
            fecha_pasada,
            fecha_futura,
            recalcular_existentes=True,
            proteger_pasados=True,
            rng=random.Random(99),
        )
        db.session.commit()

        conservado = db.session.get(TurnoAseo, anteriores['id'])
        self.assertIsNotNone(conservado)
        self.assertEqual({c.name: getattr(conservado, c.name) for c in TurnoAseo.__table__.columns}, anteriores)
        self.assertEqual(resultado['eliminados'], 0)
        self.assertNotIn(conservado.id, [turno.id for turno in resultado['recalculados']])
        self.assertIn(fecha_futura, [turno.fecha for turno in resultado['creados']])

    def test_marcar_cumplido_persiste_y_afecta_recalculo_futuro(self):
        # 1. Creamos turno hoy con Ana (0) y Bruno (1)
        fechas = fechas_futuras(3)
        fecha_hoy = fechas[0]
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
        f1 = fechas[1]
        f2 = fechas[2]
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

    def test_evita_programar_turnos_en_dias_festivos_colombia(self):
        festivos_2026 = obtener_festivos_colombia(2026)
        fecha_festivo = date(2026, 7, 20)  # Día de la Independencia
        fecha_habil = date(2026, 7, 21)    # Martes hábil

        self.assertIn(fecha_festivo, festivos_2026)
        self.assertTrue(es_festivo_colombia(fecha_festivo))
        self.assertFalse(es_festivo_colombia(fecha_habil))

        self._crear_sesion(fecha_festivo)
        self._crear_sesion(fecha_habil)
        db.session.commit()

        resultado = generar_turnos(
            self.ficha.id,
            fecha_festivo,
            fecha_habil,
            rng=random.Random(1),
        )
        db.session.commit()

        # Solo debe haberse creado el turno para el día hábil
        fechas_creadas = [t.fecha for t in resultado['creados']]
        self.assertNotIn(fecha_festivo, fechas_creadas)
        self.assertIn(fecha_habil, fechas_creadas)

        turno_festivo = TurnoAseo.query.filter_by(
            ficha_id=self.ficha.id, fecha=fecha_festivo
        ).first()
        self.assertIsNone(turno_festivo)

        # Intentar asignación manual en día festivo debe ser rechazada con ValueError
        with self.assertRaises(ValueError) as ctx:
            asignar_o_actualizar_turno(
                ficha_id=self.ficha.id,
                fecha=fecha_festivo,
                aprendiz_1_id=self.aprendices[0].id,
                aprendiz_2_id=self.aprendices[1].id,
            )
        self.assertIn('días festivos', str(ctx.exception))

    def test_inasistencia_con_corte_activo_reemplaza_y_reprograma_automaticamente(self):
        # 1. Crear corte activo para la ficha y el instructor
        corte = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            nombre='Corte 1 - Activo',
            estado=Corte.ESTADO_ACTIVO,
            fecha_inicio=date.today(),
        )
        db.session.add(corte)
        db.session.commit()

        fecha_hoy = date.today()
        # Creamos turno hoy con Ana (0) y Bruno (1)
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

        # 2. El instructor registra asistencia: Ana FALTA, los demás ASISTE
        cliente = self._cliente_instructor()
        datos_form = {
            'fecha': fecha_hoy.isoformat(),
            'corte_id': str(corte.id),
        }
        for ap in self.aprendices:
            if ap.id == self.aprendices[0].id:
                datos_form[f'asistencia_{ap.id}'] = 'FALTA'
            else:
                datos_form[f'asistencia_{ap.id}'] = 'ASISTE'

        resp = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/asistencia',
            data=datos_form,
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        # 3. Verificar que Ana fue sustituida automáticamente por un compañero presente
        turno_actualizado = db.session.get(TurnoAseo, turno_hoy.id)
        self.assertFalse(turno_actualizado.incluye(self.aprendices[0].id))
        self.assertTrue(turno_actualizado.incluye(self.aprendices[1].id))
        # El reemplazo debe ser uno de los que asistieron (Carmen, Diego, Elena o Felipe)
        suplente_id = (
            turno_actualizado.aprendiz_1_id
            if turno_actualizado.aprendiz_2_id == self.aprendices[1].id
            else turno_actualizado.aprendiz_2_id
        )
        self.assertIn(suplente_id, [a.id for a in self.aprendices[2:]])

        # 4. Verificar que se le programó reposición a Ana para una fecha futura
        reposicion = TurnoAseo.query.filter(
            TurnoAseo.ficha_id == self.ficha.id,
            TurnoAseo.fecha > fecha_hoy,
            TurnoAseo.estado.in_(['programado', 'pendiente']),
            db.or_(
                TurnoAseo.aprendiz_1_id == self.aprendices[0].id,
                TurnoAseo.aprendiz_2_id == self.aprendices[0].id,
            ),
        ).first()
        self.assertIsNotNone(reposicion)
        self.assertTrue(reposicion.incluye(self.aprendices[0].id))

    def test_aprendiz_administrador_marcar_cumplido_desde_panel_y_asignar_manual(self):
        admin = self.aprendices[0]
        no_admin = self.aprendices[1]
        admin.rol_administrativo = True
        db.session.commit()

        fecha_hoy = date.today()
        self._crear_sesion(fecha_hoy)
        turno_hoy = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_hoy,
            aprendiz_1_id=admin.id,
            aprendiz_2_id=no_admin.id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno_hoy)
        db.session.commit()

        # 1. Aprendiz administrador marca turno cumplido desde el panel (con origen=panel)
        cliente = self.app.test_client()
        with cliente.session_transaction() as s:
            s['aprendiz_documento'] = admin.documento
            s['aprendiz_ficha_id'] = self.ficha.id

        resp_panel = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(resp_panel.status_code, 200)
        self.assertIn('Marcar aseo de hoy hecho'.encode(), resp_panel.data)

        resp_cumplir = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno_hoy.id}/cumplir',
            data={'origen': 'panel'},
            follow_redirects=False,
        )
        self.assertEqual(resp_cumplir.status_code, 302)
        self.assertIn(f'/aprendiz/{self.ficha.id}/panel', resp_cumplir.headers['Location'])

        turno_bd = db.session.get(TurnoAseo, turno_hoy.id)
        self.assertEqual(turno_bd.estado, 'cumplido')

        # 2. Aprendiz administrador asigna un turno manual en fecha futura
        fecha_manual = fecha_hoy + timedelta(days=5)
        while es_festivo_colombia(fecha_manual):
            fecha_manual += timedelta(days=1)

        resp_asignar = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/asignar',
            data={
                'fecha': fecha_manual.isoformat(),
                'aprendiz_1_id': self.aprendices[2].id,
                'aprendiz_2_id': self.aprendices[3].id,
                'observacion': 'Asignado por aprendiz administrador para evento',
            },
            follow_redirects=True,
        )
        self.assertEqual(resp_asignar.status_code, 200)

        turno_manual = TurnoAseo.query.filter_by(
            ficha_id=self.ficha.id, fecha=fecha_manual
        ).first()
        self.assertIsNotNone(turno_manual)
        self.assertEqual(turno_manual.generado_por, 'aprendiz_admin')
        self.assertTrue(turno_manual.incluye(self.aprendices[2].id))
        self.assertTrue(turno_manual.incluye(self.aprendices[3].id))

        resp_editar = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno_manual.id}/editar',
            data={
                'aprendiz_1_id': self.aprendices[4].id,
                'aprendiz_2_id': self.aprendices[5].id,
                'observacion': 'Cambio autorizado por el aprendiz administrador',
            },
            follow_redirects=False,
        )
        self.assertEqual(resp_editar.status_code, 302)
        db.session.refresh(turno_manual)
        self.assertEqual(turno_manual.aprendiz_1_id, self.aprendices[4].id)
        self.assertEqual(turno_manual.aprendiz_2_id, self.aprendices[5].id)
        self.assertEqual(turno_manual.generado_por, 'aprendiz_admin')

        # 3. Un aprendiz regular conserva la consulta, pero no modifica el calendario.
        cliente_no_admin = self.app.test_client()
        with cliente_no_admin.session_transaction() as s:
            s['aprendiz_documento'] = no_admin.documento
            s['aprendiz_ficha_id'] = self.ficha.id

        resp_permitido = cliente_no_admin.get(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/gestionar',
            follow_redirects=True,
        )
        self.assertEqual(resp_permitido.status_code, 200)
        self.assertIn('Calendario de turnos de aseo'.encode(), resp_permitido.data)
        self.assertIn('calendario-turnos'.encode(), resp_permitido.data)
        self.assertNotIn('form-generar-turnos'.encode(), resp_permitido.data)
        self.assertNotIn('form-asignar-turno'.encode(), resp_permitido.data)
        contenido_consulta = resp_permitido.get_data(as_text=True)
        for ruta_modificacion in (
            'editar_como_aprendiz',
            'cumplir_como_aprendiz',
            'no_cumplir_como_aprendiz',
            'reabrir_como_aprendiz',
            'excluir_como_aprendiz',
        ):
            self.assertNotIn(ruta_modificacion, contenido_consulta)

        resp_transparencia_regular = cliente_no_admin.get(
            f'/aprendiz/{self.ficha.id}/turnos-aseo'
        )
        self.assertEqual(resp_transparencia_regular.status_code, 200)
        self.assertIn('calendar-card'.encode(), resp_transparencia_regular.data)
        self.assertNotIn('cumplir_como_aprendiz'.encode(), resp_transparencia_regular.data)

        # No puede cambiar estados, aunque presente el documento del administrador.
        resp_cumplir_regular = cliente_no_admin.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno_manual.id}/cumplir',
            data={'origen': 'panel', 'documento': admin.documento},
            follow_redirects=False,
        )
        self.assertEqual(resp_cumplir_regular.status_code, 302)
        turno_manual_bd = db.session.get(TurnoAseo, turno_manual.id)
        self.assertEqual(turno_manual_bd.estado, 'programado')

        resp_panel_regular = cliente_no_admin.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(resp_panel_regular.status_code, 200)
        self.assertNotIn('cumplir_como_aprendiz'.encode(), resp_panel_regular.data)
        self.assertNotIn('generar_como_aprendiz'.encode(), resp_panel_regular.data)

        # 4. Usuario no autenticado o de otra ficha no puede gestionar
        cliente_ajeno = self.app.test_client()
        with cliente_ajeno.session_transaction() as s:
            s['aprendiz_documento'] = '9999999999'
            s['aprendiz_ficha_id'] = self.ficha.id

        resp_ajeno = cliente_ajeno.get(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/gestionar',
            follow_redirects=True,
        )
        self.assertIn('Debes pertenecer a esta ficha para gestionar los turnos de aseo'.encode(), resp_ajeno.data)

        # Un documento en la URL tampoco establece una sesión de aprendiz.
        cliente_sin_sesion = self.app.test_client()
        resp_documento_url = cliente_sin_sesion.get(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/gestionar?documento={admin.documento}',
            follow_redirects=True,
        )
        self.assertIn('Debes pertenecer a esta ficha para gestionar los turnos de aseo'.encode(), resp_documento_url.data)

        cliente_sin_sesion.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/config',
            data={'documento': admin.documento, 'aviso_horas': '1'},
            follow_redirects=False,
        )
        db.session.expire_all()
        config = ConfiguracionAseo.query.filter_by(ficha_id=self.ficha.id).first()
        self.assertEqual(config.aviso_horas, 24)

    def test_tabla_aprendiz_admin_muestra_estado_no_cumplido_correcto(self):
        administrador = self.aprendices[0]
        administrador.rol_administrativo = True
        fecha = date.today() + timedelta(days=2)
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=self.aprendices[1].id,
            aprendiz_2_id=self.aprendices[2].id,
            estado='no_cumplido',
        )
        db.session.add(turno)
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = administrador.documento
            sesion['aprendiz_ficha_id'] = self.ficha.id
        respuesta = cliente.get(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/gestionar?mes={fecha.strftime("%Y-%m")}'
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(b'<span class="badge badge-danger">No cumplido</span>', respuesta.data)

    def test_aprendiz_no_admin_no_modifica_turnos_aunque_envie_documento_admin(self):
        administrador, actor, aprendiz_1, aprendiz_2, otro_1, otro_2 = self.aprendices
        administrador.rol_administrativo = True
        fecha = fechas_futuras(2)[0]
        self._crear_sesion(fecha)
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=aprendiz_1.id,
            aprendiz_2_id=aprendiz_2.id,
            estado='no_cumplido',
            observacion='Estado original',
        )
        config = ConfiguracionAseo(
            ficha_id=self.ficha.id,
            aviso_horas=24,
            excluir_ausentes=False,
        )
        db.session.add_all([turno, config])
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = actor.documento
            sesion['aprendiz_ficha_id'] = self.ficha.id

        intentos = (
            (
                f'/aprendiz/{self.ficha.id}/turnos-aseo/generar',
                {'fecha_inicio': fecha.isoformat(), 'fecha_fin': fecha.isoformat()},
            ),
            (
                f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno.id}/cumplir',
                {},
            ),
            (
                f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno.id}/no-cumplir',
                {'observacion': 'No autorizado'},
            ),
            (
                f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno.id}/reabrir',
                {},
            ),
            (
                f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno.id}/editar',
                {'aprendiz_1_id': otro_1.id, 'aprendiz_2_id': otro_2.id},
            ),
            (
                f'/aprendiz/{self.ficha.id}/turnos-aseo/asignar',
                {
                    'fecha': fecha.isoformat(),
                    'aprendiz_1_id': otro_1.id,
                    'aprendiz_2_id': otro_2.id,
                },
            ),
            (
                f'/aprendiz/{self.ficha.id}/turnos-aseo/config',
                {'aviso_horas': '72', 'excluir_ausentes': 'on'},
            ),
            (
                f'/aprendiz/{self.ficha.id}/turnos-aseo/exclusion/{actor.id}',
                {'excluido_hasta': fecha.isoformat(), 'motivo': 'No autorizado'},
            ),
        )
        conteo_turnos = TurnoAseo.query.filter_by(ficha_id=self.ficha.id).count()

        for ruta, datos in intentos:
            with self.subTest(ruta=ruta):
                respuesta = cliente.post(
                    ruta,
                    data={**datos, 'documento': administrador.documento},
                    follow_redirects=False,
                )
                self.assertEqual(respuesta.status_code, 302)
                self.assertEqual(
                    TurnoAseo.query.filter_by(ficha_id=self.ficha.id).count(),
                    conteo_turnos,
                )
                db.session.refresh(turno)
                self.assertEqual(turno.estado, 'no_cumplido')
                self.assertEqual(turno.observacion, 'Estado original')
                db.session.refresh(config)
                self.assertEqual(config.aviso_horas, 24)
                self.assertFalse(config.excluir_ausentes)
                self.assertIsNone(
                    ContadorAseo.query.filter_by(
                        ficha_id=self.ficha.id, aprendiz_id=actor.id
                    ).first()
                )

    def test_intercambio_de_aseo_sigue_limitado_a_solicitante_y_destinatario(self):
        solicitante, coasignado, destinatario, suplantador = self.aprendices[:4]
        fecha = fechas_futuras(2)[0]
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=solicitante.id,
            aprendiz_2_id=coasignado.id,
            estado='programado',
        )
        db.session.add(turno)
        db.session.commit()

        cliente_solicitante = self.app.test_client()
        with cliente_solicitante.session_transaction() as sesion:
            sesion['aprendiz_documento'] = solicitante.documento
            sesion['aprendiz_ficha_id'] = self.ficha.id
        respuesta_solicitud = cliente_solicitante.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno.id}/intercambiar',
            data={
                'aprendiz_recibe_id': destinatario.id,
                'documento': suplantador.documento,
            },
            follow_redirects=False,
        )
        self.assertEqual(respuesta_solicitud.status_code, 302)
        intercambio = IntercambioAseo.query.filter_by(turno_id=turno.id).one()
        self.assertEqual(intercambio.aprendiz_solicita_id, solicitante.id)
        self.assertEqual(intercambio.aprendiz_recibe_id, destinatario.id)

        cliente_suplantador = self.app.test_client()
        with cliente_suplantador.session_transaction() as sesion:
            sesion['aprendiz_documento'] = suplantador.documento
            sesion['aprendiz_ficha_id'] = self.ficha.id
        cliente_suplantador.post(
            f'/aprendiz/{self.ficha.id}/intercambios/{intercambio.id}/responder',
            data={'accion': 'rechazar', 'documento': destinatario.documento},
            follow_redirects=False,
        )
        db.session.refresh(intercambio)
        self.assertEqual(intercambio.estado, 'pendiente')

        cliente_destinatario = self.app.test_client()
        with cliente_destinatario.session_transaction() as sesion:
            sesion['aprendiz_documento'] = destinatario.documento
            sesion['aprendiz_ficha_id'] = self.ficha.id
        respuesta_destinatario = cliente_destinatario.post(
            f'/aprendiz/{self.ficha.id}/intercambios/{intercambio.id}/responder',
            data={'accion': 'rechazar'},
            follow_redirects=False,
        )
        self.assertEqual(respuesta_destinatario.status_code, 302)
        db.session.refresh(intercambio)
        self.assertEqual(intercambio.estado, 'rechazado')

    def test_reasignar_rol_y_deshabilitar_aprendiz_actualiza_autorizacion(self):
        anterior, nuevo = self.aprendices[:2]
        configurar_rol_aprendiz(self.ficha.id, anterior.id)
        db.session.commit()

        cliente_anterior = self.app.test_client()
        with cliente_anterior.session_transaction() as sesion:
            sesion['aprendiz_documento'] = anterior.documento
            sesion['aprendiz_ficha_id'] = self.ficha.id
        cliente_nuevo = self.app.test_client()
        with cliente_nuevo.session_transaction() as sesion:
            sesion['aprendiz_documento'] = nuevo.documento
            sesion['aprendiz_ficha_id'] = self.ficha.id

        cliente_anterior.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/config',
            data={'aviso_horas': '48'},
            follow_redirects=False,
        )
        config = ConfiguracionAseo.query.filter_by(ficha_id=self.ficha.id).first()
        self.assertEqual(config.aviso_horas, 48)

        configurar_rol_aprendiz(self.ficha.id, nuevo.id)
        db.session.commit()
        cliente_anterior.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/config',
            data={'aviso_horas': '72', 'documento': nuevo.documento},
            follow_redirects=False,
        )
        db.session.refresh(config)
        self.assertEqual(config.aviso_horas, 48)

        cliente_nuevo.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/config',
            data={'aviso_horas': '36'},
            follow_redirects=False,
        )
        db.session.refresh(config)
        self.assertEqual(config.aviso_horas, 36)

        cambiar_estado_activo_aprendiz(self.ficha.id, nuevo.id, activo=False)
        db.session.commit()
        cliente_nuevo.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/config',
            data={'aviso_horas': '12'},
            follow_redirects=False,
        )
        db.session.refresh(config)
        self.assertEqual(config.aviso_horas, 36)

    def test_exclusion_rechaza_aprendiz_deshabilitado_sin_contador(self):
        administrador, deshabilitado = self.aprendices[:2]
        administrador.rol_administrativo = True
        deshabilitado.activo = False
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = administrador.documento
            sesion['aprendiz_ficha_id'] = self.ficha.id

        respuesta = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/exclusion/{deshabilitado.id}',
            data={
                'excluido_hasta': (date.today() + timedelta(days=5)).isoformat(),
                'motivo': 'Incapacidad',
            },
            follow_redirects=False,
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertIsNone(
            ContadorAseo.query.filter_by(
                ficha_id=self.ficha.id,
                aprendiz_id=deshabilitado.id,
            ).first()
        )

    def test_aprendiz_configurar_reglas_aseo(self):
        aprendiz = self.aprendices[1]
        aprendiz.rol_administrativo = True
        db.session.commit()
        cliente = self.app.test_client()
        with cliente.session_transaction() as s:
            s['aprendiz_documento'] = aprendiz.documento
            s['aprendiz_ficha_id'] = self.ficha.id

        # 1. Configurar saltar ausentes y 48 horas de aviso
        resp = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/config',
            data={
                'excluir_ausentes': 'on',
                'aviso_horas': '48',
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Configuración de turnos de aseo actualizada'.encode(), resp.data)

        from app.models.aseo import ConfiguracionAseo
        config = ConfiguracionAseo.query.filter_by(ficha_id=self.ficha.id).first()
        self.assertIsNotNone(config)
        self.assertTrue(config.excluir_ausentes)
        self.assertEqual(config.aviso_horas, 48)

        # 2. Validación de valor no entero en aviso_horas
        resp_invalido = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/config',
            data={
                'aviso_horas': 'texto_invalido',
            },
            follow_redirects=True,
        )
        self.assertEqual(resp_invalido.status_code, 200)
        self.assertIn('Las horas de aviso deben ser un número entero'.encode(), resp_invalido.data)
        db.session.refresh(config)
        self.assertTrue(config.excluir_ausentes)
        self.assertEqual(config.aviso_horas, 48)

        # 3. Usuario ajeno no puede configurar
        cliente_ajeno = self.app.test_client()
        with cliente_ajeno.session_transaction() as s:
            s['aprendiz_documento'] = '00000000'
            s['aprendiz_ficha_id'] = self.ficha.id

        resp_bloqueado = cliente_ajeno.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/config',
            data={'aviso_horas': '24'},
            follow_redirects=True,
        )
        self.assertIn('Debes pertenecer a esta ficha'.encode(), resp_bloqueado.data)

    def test_configuracion_instructor_invalida_no_aplica_cambios_parciales(self):
        config = ConfiguracionAseo(
            ficha_id=self.ficha.id,
            aviso_horas=24,
            excluir_ausentes=False,
        )
        db.session.add(config)
        db.session.commit()
        cliente = self._cliente_instructor()

        respuesta = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo/config',
            data={'aviso_horas': 'inválido', 'excluir_ausentes': 'on'},
            follow_redirects=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        db.session.refresh(config)
        self.assertEqual(config.aviso_horas, 24)
        self.assertFalse(config.excluir_ausentes)

    def test_aprendiz_excluir_y_reactivar_aprendiz(self):
        actor = self.aprendices[0]
        companero = self.aprendices[2]
        actor.rol_administrativo = True
        db.session.commit()
        cliente = self.app.test_client()
        with cliente.session_transaction() as s:
            s['aprendiz_documento'] = actor.documento
            s['aprendiz_ficha_id'] = self.ficha.id

        # 1. Excluir temporalmente al compañero por motivo de salud
        fecha_hasta = date.today() + timedelta(days=10)
        resp_excluir = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/exclusion/{companero.id}',
            data={
                'excluido_hasta': fecha_hasta.isoformat(),
                'motivo': 'Incapacidad médica',
            },
            follow_redirects=True,
        )
        self.assertEqual(resp_excluir.status_code, 200)
        self.assertIn('quedó excluido temporalmente'.encode(), resp_excluir.data)

        contador = ContadorAseo.query.filter_by(
            ficha_id=self.ficha.id, aprendiz_id=companero.id
        ).first()
        self.assertIsNotNone(contador)
        self.assertEqual(contador.excluido_hasta, fecha_hasta)
        self.assertEqual(contador.motivo_exclusion, 'Incapacidad médica')

        # 2. Reactivar al compañero borrando la fecha de exclusión
        resp_reactivar = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/exclusion/{companero.id}',
            data={
                'excluido_hasta': '',
                'motivo': '',
            },
            follow_redirects=True,
        )
        self.assertEqual(resp_reactivar.status_code, 200)
        self.assertIn('volvió a la cola justa'.encode(), resp_reactivar.data)

        db.session.refresh(contador)
        self.assertIsNone(contador.excluido_hasta)
        self.assertIsNone(contador.motivo_exclusion)

        # 3. Intentar excluir un ID inexistente
        resp_inexistente = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/exclusion/99999',
            data={'excluido_hasta': fecha_hasta.isoformat()},
            follow_redirects=True,
        )
        self.assertIn('Aprendiz no encontrado'.encode(), resp_inexistente.data)

    def test_aprendiz_generar_turnos_con_respetar_manuales(self):
        actor = self.aprendices[0]
        actor.rol_administrativo = True
        db.session.commit()
        cliente = self.app.test_client()
        with cliente.session_transaction() as s:
            s['aprendiz_documento'] = actor.documento
            s['aprendiz_ficha_id'] = self.ficha.id

        fecha_1, fecha_2 = fechas_futuras(2)

        self._crear_sesion(fecha_1)
        self._crear_sesion(fecha_2)
        db.session.commit()

        # Crear una asignación manual para fecha_1 con aprendices 4 y 5
        asignar_o_actualizar_turno(
            ficha_id=self.ficha.id,
            fecha=fecha_1,
            aprendiz_1_id=self.aprendices[4].id,
            aprendiz_2_id=self.aprendices[5].id,
            observacion='Turno manual acordado',
            origen='aprendiz',
        )
        db.session.commit()

        # Generar turnos para el rango con respetar_manuales='on'
        resp = cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/generar',
            data={
                'fecha_inicio': fecha_1.isoformat(),
                'fecha_fin': fecha_2.isoformat(),
                'recalcular': 'on',
                'respetar_manuales': 'on',
                'dias_semana_present': '1',
                'dias_semana': ['0', '1', '2', '3', '4'],
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('name="dias_semana"'.encode(), resp.data)

        # El turno de fecha_1 debe conservarse con la pareja manual
        t1 = TurnoAseo.query.filter_by(ficha_id=self.ficha.id, fecha=fecha_1).first()
        self.assertIsNotNone(t1)
        self.assertEqual(t1.aprendiz_1_id, self.aprendices[4].id)
        self.assertEqual(t1.aprendiz_2_id, self.aprendices[5].id)

    def test_panel_aprendiz_muestra_opcion_programar_aseo_en_ambos_estados(self):
        aprendiz = self.aprendices[0]
        cliente = self.app.test_client()
        with cliente.session_transaction() as s:
            s['aprendiz_documento'] = aprendiz.documento
            s['aprendiz_ficha_id'] = self.ficha.id

        # Estado A: Sin turno propio asignado
        resp_sin_turno = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(resp_sin_turno.status_code, 200)
        self.assertIn('Ver turnos de aseo'.encode(), resp_sin_turno.data)
        self.assertIn(f'/aprendiz/{self.ficha.id}/turnos-aseo/gestionar'.encode(), resp_sin_turno.data)

        # Estado B: Con turno propio asignado
        fecha_turno = date.today() + timedelta(days=3)
        while es_festivo_colombia(fecha_turno):
            fecha_turno += timedelta(days=1)

        self._crear_sesion(fecha_turno)
        db.session.add(TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_turno,
            aprendiz_1_id=aprendiz.id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        ))
        db.session.commit()

        resp_con_turno = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(resp_con_turno.status_code, 200)
        # Debe mostrar el turno propio y el enlace de consulta para cualquier aprendiz.
        self.assertIn('Tu próximo turno'.encode(), resp_con_turno.data)
        self.assertIn('Ver turnos de aseo'.encode(), resp_con_turno.data)
        self.assertIn(f'/aprendiz/{self.ficha.id}/turnos-aseo/gestionar'.encode(), resp_con_turno.data)

    def test_algoritmo_equitativo_prioriza_menor_veces_aseo(self):
        """Verifica que el algoritmo asigne primero a quienes menos aseo han hecho y no repita a quienes tienen más turnos."""
        # Creamos historial real de turnos cumplidos (SSoT):
        # Ana (0) y Bruno (1) cumplieron 2 turnos en el pasado
        # Carmen (2) y Diego (3) cumplieron 1 turno en el pasado
        # Elena (4) y Felipe (5) tienen 0 turnos cumplidos
        fecha_h1 = date.today() - timedelta(days=12)
        fecha_h2 = date.today() - timedelta(days=11)
        fecha_h3 = date.today() - timedelta(days=10)

        for f, (a1, a2) in (
            (fecha_h1, (self.aprendices[0], self.aprendices[1])),
            (fecha_h2, (self.aprendices[0], self.aprendices[1])),
            (fecha_h3, (self.aprendices[2], self.aprendices[3])),
        ):
            self._crear_sesion(f)
            t = TurnoAseo(
                ficha_id=self.ficha.id,
                fecha=f,
                aprendiz_1_id=a1.id,
                aprendiz_2_id=a2.id,
                estado='cumplido',
                completado_1=True,
                completado_2=True,
                generado_por='sistema',
            )
            db.session.add(t)
        db.session.commit()

        # Creamos 2 sesiones hábiles a futuro
        dias = fechas_futuras(2)

        for d in dias:
            self._crear_sesion(d)
        db.session.commit()

        resultado = generar_turnos(
            self.ficha.id,
            fecha_inicio=dias[0],
            fecha_fin=dias[1],
            recalcular_existentes=True,
        )
        self.assertEqual(len(resultado['creados']), 2)

        turno_1 = TurnoAseo.query.filter_by(ficha_id=self.ficha.id, fecha=dias[0]).first()
        turno_2 = TurnoAseo.query.filter_by(ficha_id=self.ficha.id, fecha=dias[1]).first()

        # En la primera sesión deben asignarse estrictamente quienes tenían 0 turnos (Elena y Felipe)
        pareja_1 = {turno_1.aprendiz_1_id, turno_1.aprendiz_2_id}
        self.assertEqual(pareja_1, {self.aprendices[4].id, self.aprendices[5].id})

        # En la segunda sesión deben asignarse quienes tenían 1 turno (Carmen y Diego)
        pareja_2 = {turno_2.aprendiz_1_id, turno_2.aprendiz_2_id}
        self.assertEqual(pareja_2, {self.aprendices[2].id, self.aprendices[3].id})

        # Quienes ya tenían 2 turnos (Ana y Bruno) NO deben ser asignados en ninguna sesión
        todos_asignados = pareja_1.union(pareja_2)
        self.assertNotIn(self.aprendices[0].id, todos_asignados)
        self.assertNotIn(self.aprendices[1].id, todos_asignados)

    def test_turno_futuro_fuera_de_rango_no_bloquea_a_aprendiz_sin_aseo(self):
        """Verifica que un turno pendiente futuro fuera de fecha_fin no infle la carga en el periodo actual."""
        # Programar un turno futuro lejano (a 40 días) para el aprendiz 4 (Elena)
        fecha_futura = date.today() + timedelta(days=40)
        self._crear_sesion(fecha_futura)
        db.session.add(TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_futura,
            aprendiz_1_id=self.aprendices[4].id,
            aprendiz_2_id=self.aprendices[5].id,
            estado='programado',
            generado_por='sistema',
        ))
        db.session.commit()

        # Generar turnos para el próximo día hábil (solo 1 sesión)
        fecha_manana = fechas_futuras(1)[0]
        self._crear_sesion(fecha_manana)
        db.session.commit()

        resultado = generar_turnos(
            self.ficha.id,
            fecha_inicio=fecha_manana,
            fecha_fin=fecha_manana,
            recalcular_existentes=True,
        )
        self.assertEqual(len(resultado['creados']), 1)
        turno = resultado['creados'][0]
        # El turno se generó correctamente sin que Elena quede bloqueada artificialmente
        self.assertIn(turno.estado, ('programado',))

    def test_suplencia_por_ausencia_prioriza_menor_veces_aseo(self):
        """Verifica que al suplir a un ausente se elija a quien menos veces de aseo haya cumplido."""
        from app.services.aseo import _reemplazar_ausentes_del_dia, recalcular_contadores

        # Creamos turnos cumplidos previos para reflejar historial real (SSoT):
        # Ana (0) y Bruno (1) ya cumplieron turno histórico
        fecha_h = date.today() - timedelta(days=5)
        self._crear_sesion(fecha_h)
        db.session.add(TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_h,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='cumplido',
            completado_1=True,
            completado_2=True,
            generado_por='sistema',
        ))
        db.session.commit()
        recalcular_contadores(self.ficha.id)

        fecha_hoy = date.today()
        sesion = self._crear_sesion(fecha_hoy)
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_hoy,
            aprendiz_1_id=self.aprendices[3].id,  # Diego
            aprendiz_2_id=self.aprendices[4].id,  # Elena (va a faltar)
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        # Presentes en el aula: Diego (3), Ana (0 - 1 turno), Bruno (1 - 1 turno), Carmen (2 - 0 turnos)
        # Falta Elena (4)
        presentes = {self.aprendices[3].id, self.aprendices[0].id, self.aprendices[1].id, self.aprendices[2].id}

        repuestos = _reemplazar_ausentes_del_dia(turno, presentes)
        self.assertEqual(len(repuestos), 1)
        # El suplente elegido DEBE ser Carmen (2) porque tiene 0 turnos cumplidos vs Ana y Bruno que tienen 1
        self.assertEqual(turno.aprendiz_2_id, self.aprendices[2].id)

    def test_guardar_asistencia_servicio_sustituye_inmediatamente_ausente_por_cola_justa(self):
        """guardar_asistencia sustituye inmediatamente al ausente en turno de la fecha por el de menor carga."""
        from app.services.asistencia import guardar_asistencia
        from app.services.aseo import recalcular_contadores

        # Histórico: Bruno (1), Elena (4) y Felipe (5) tienen 1 turno previo, Carmen (2) tiene 0
        fecha_pasada = date.today() - timedelta(days=5)
        self._crear_sesion(fecha_pasada)
        db.session.add(TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_pasada,
            aprendiz_1_id=self.aprendices[1].id,
            aprendiz_2_id=self.aprendices[5].id,
            estado='cumplido',
            completado_1=True,
            completado_2=True,
            generado_por='sistema',
        ))
        db.session.add(TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_pasada - timedelta(days=1),
            aprendiz_1_id=self.aprendices[4].id,
            aprendiz_2_id=self.aprendices[5].id,
            estado='cumplido',
            completado_1=True,
            completado_2=True,
            generado_por='sistema',
        ))
        db.session.commit()
        recalcular_contadores(self.ficha.id)

        fecha_hoy = date.today()
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_hoy,
            aprendiz_1_id=self.aprendices[0].id,  # Ana (va a faltar)
            aprendiz_2_id=self.aprendices[3].id,  # Diego (presente)
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        # Guardar asistencia marcando falta a Ana
        registros = {
            self.aprendices[0].id: ('FALTA', None),
            self.aprendices[1].id: ('ASISTE', None),  # Bruno (carga 1)
            self.aprendices[2].id: ('ASISTE', None),  # Carmen (carga 0)
            self.aprendices[3].id: ('ASISTE', None),  # Diego (en turno)
            self.aprendices[4].id: ('ASISTE', None),  # Elena (carga 1)
            self.aprendices[5].id: ('ASISTE', None),  # Felipe (carga 2)
        }
        guardar_asistencia(self.ficha.id, fecha_hoy, registros)

        # El turno debe haberse actualizado inmediatamente
        db.session.refresh(turno)
        self.assertFalse(turno.incluye(self.aprendices[0].id))
        self.assertTrue(turno.incluye(self.aprendices[3].id))
        # Carmen (2) entra como suplente por tener menor carga (0) vs los demás asistentes
        self.assertEqual(turno.aprendiz_1_id, self.aprendices[2].id)
        self.assertIn('Suplencia por inasistencia', turno.auditoria_1)
        self.assertIn('Suplente por ausencia de', turno.observacion)

        # Ana conserva 0 aseos cumplidos
        contadores = recalcular_contadores(self.ficha.id)
        self.assertEqual(contadores[self.aprendices[0].id].veces_aseo, 0)

    def test_acceso_turnos_aseo_sustituye_proactivamente_ausente_confirmado(self):
        """Acceder a turnos-aseo para una fecha con inasistencia confirmada actualiza los asignados."""
        fecha = fechas_futuras(1)[0]
        # Crear sesión con Ana ausente
        self._crear_sesion(fecha, ausentes=(self.aprendices[0].id,))
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=self.aprendices[0].id,  # Ana (ausente confirmada)
            aprendiz_2_id=self.aprendices[1].id,  # Bruno (presente)
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        # El turno aún tiene a Ana asignada antes de la petición GET
        self.assertEqual(turno.aprendiz_1_id, self.aprendices[0].id)

        cliente = self._cliente_instructor()
        mes_param = fecha.strftime('%Y-%m')
        respuesta = cliente.get(f'/instructor/fichas/{self.ficha.id}/turnos-aseo?mes={mes_param}')
        self.assertEqual(respuesta.status_code, 200)

        # Tras consultar el calendario, el turno se actualizó proactivamente
        db.session.refresh(turno)
        self.assertFalse(turno.incluye(self.aprendices[0].id))
        self.assertTrue(turno.incluye(self.aprendices[1].id))
        suplente_id = turno.aprendiz_1_id
        self.assertIn(suplente_id, [a.id for a in self.aprendices[2:]])
        # La tarjeta en el HTML muestra limpiamente el nombre del suplente
        suplente = db.session.get(Aprendiz, suplente_id)
        self.assertIn(suplente.nombre.encode(), respuesta.data)
        # La explicación detallada está registrada en la auditoría
        self.assertIn('Suplencia por inasistencia', turno.auditoria_1)

    def test_ausente_no_desaloja_turnos_futuros_de_otros_aprendices(self):
        """Un ausente no desaloja turnos futuros ya asignados a otros aprendices."""
        fechas = fechas_futuras(2)
        fecha_1 = fechas[0]
        fecha_2 = fechas[1]

        # Turno 1 en fecha_1: Ana (0) y Bruno (1)
        turno_1 = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_1,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        # Turno 2 en fecha_2: Carmen (2) y Diego (3)
        turno_2 = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_2,
            aprendiz_1_id=self.aprendices[2].id,
            aprendiz_2_id=self.aprendices[3].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add_all([turno_1, turno_2])
        db.session.commit()

        # Ana falta en fecha_1
        from app.services.asistencia import guardar_asistencia
        registros = {a.id: ('FALTA' if a.id == self.aprendices[0].id else 'ASISTE', None)
                     for a in self.aprendices}
        guardar_asistencia(self.ficha.id, fecha_1, registros)

        # Turno 1 sustituyó a Ana
        db.session.refresh(turno_1)
        self.assertFalse(turno_1.incluye(self.aprendices[0].id))

        # Turno 2 en fecha_2 CONSERVA intactos a Carmen (2) y Diego (3); ninguno fue desalojado
        db.session.refresh(turno_2)
        self.assertEqual(turno_2.aprendiz_1_id, self.aprendices[2].id)
        self.assertEqual(turno_2.aprendiz_2_id, self.aprendices[3].id)

    def test_verificar_ausencias_en_turnos_respeta_configuracion_excluir_ausentes(self):
        """verificar_ausencias_en_turnos no modifica turnos si excluir_ausentes está inactivo."""
        from app.services.aseo import verificar_ausencias_en_turnos, obtener_configuracion

        fecha = fechas_futuras(1)[0]
        self._crear_sesion(fecha, ausentes=(self.aprendices[0].id,))
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        config = obtener_configuracion(self.ficha.id)
        config.excluir_ausentes = False
        db.session.commit()

        resultado = verificar_ausencias_en_turnos(self.ficha.id, fecha, fecha)
        self.assertEqual(resultado, [])
        db.session.refresh(turno)
        self.assertEqual(turno.aprendiz_1_id, self.aprendices[0].id)

        # Si activamos excluir_ausentes, sustituye y retorna el turno
        config.excluir_ausentes = True
        db.session.commit()
        resultado_activo = verificar_ausencias_en_turnos(self.ficha.id, fecha, fecha)
        self.assertEqual(len(resultado_activo), 1)
        db.session.refresh(turno)
        self.assertNotEqual(turno.aprendiz_1_id, self.aprendices[0].id)


    def test_guardar_asistencia_100_por_ciento_ausentes_no_falla(self):
        """Si todos los aprendices faltan, no falla y el turno permanece pendiente."""
        from app.services.asistencia import guardar_asistencia
        fecha = date.today()
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        registros = {a.id: ('FALTA', None) for a in self.aprendices}
        sesion = guardar_asistencia(self.ficha.id, fecha, registros)
        self.assertIsNotNone(sesion)
        db.session.refresh(turno)
        self.assertEqual(turno.estado, 'programado')
        self.assertEqual(turno.aprendiz_1_id, self.aprendices[0].id)
        self.assertEqual(turno.aprendiz_2_id, self.aprendices[1].id)

    def test_guardar_asistencia_reiterada_mantiene_idempotencia_auditoria(self):
        """Guardar asistencia consecutivamente con la misma inasistencia no duplica auditoría."""
        from app.services.asistencia import guardar_asistencia
        fecha = date.today()
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        registros = {a.id: ('FALTA' if a.id == self.aprendices[0].id else 'ASISTE', None)
                     for a in self.aprendices}
        guardar_asistencia(self.ficha.id, fecha, registros)
        db.session.refresh(turno)
        suplente_1 = turno.aprendiz_1_id
        obs_1 = turno.observacion

        # Guardar exactamente la misma asistencia de nuevo
        guardar_asistencia(self.ficha.id, fecha, registros)
        db.session.refresh(turno)
        self.assertEqual(turno.aprendiz_1_id, suplente_1)
        self.assertEqual(turno.observacion, obs_1)

    def test_guardar_asistencia_con_un_solo_presente_evita_duplicidad(self):
        """Si solo hay un aprendiz presente disponible, no se duplica en ambos cupos."""
        from app.services.asistencia import guardar_asistencia
        fecha = date.today()
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        # Solo Carmen (2) asiste; todos los demás faltan
        registros = {a.id: ('ASISTE' if a.id == self.aprendices[2].id else 'FALTA', None)
                     for a in self.aprendices}
        guardar_asistencia(self.ficha.id, fecha, registros)
        db.session.refresh(turno)
        # Carmen entró en el cupo 1
        self.assertEqual(turno.aprendiz_1_id, self.aprendices[2].id)
        # El cupo 2 no puede tener a Carmen dos veces
        self.assertNotEqual(turno.aprendiz_2_id, self.aprendices[2].id)

    def test_reemplazar_ausentes_con_slot_nulo_es_seguro(self):
        """_reemplazar_ausentes_del_dia no falla si un cupo no tiene aprendiz asignado."""
        from types import SimpleNamespace
        from app.services.aseo import _reemplazar_ausentes_del_dia
        fecha = date.today()
        # Objeto simulado con slot 1 nulo (sin violar constraint de DB)
        turno_mock = SimpleNamespace(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=None,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            observacion=None,
            auditoria_1=None,
            auditoria_2=None,
            generado_por='sistema',
        )

        presentes = {self.aprendices[2].id, self.aprendices[3].id}
        resultado = _reemplazar_ausentes_del_dia(turno_mock, presentes)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0].id, self.aprendices[1].id)
        self.assertIsNone(turno_mock.aprendiz_1_id)
        self.assertIn(turno_mock.aprendiz_2_id, presentes)

    def test_programar_reposicion_ramas_de_guarda(self):
        """Verifica todas las ramas de guarda de _programar_reposicion y _proxima_fecha_disponible."""
        from app.services.aseo import _programar_reposicion, _proxima_fecha_disponible
        fecha = date.today()

        # 1. Aprendiz inactivo
        inactivo = self.aprendices[0]
        inactivo.activo = False
        self.assertIsNone(_programar_reposicion(self.ficha.id, inactivo, fecha))
        inactivo.activo = True

        # 2. Aprendiz con turno pendiente futuro ya programado
        turno_futuro = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha + timedelta(days=2),
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno_futuro)
        db.session.commit()
        self.assertIsNone(_programar_reposicion(self.ficha.id, self.aprendices[0], fecha))
        db.session.delete(turno_futuro)
        db.session.commit()

        # 3. Ficha con fecha_fin en el pasado: _proxima_fecha_disponible retorna None
        fecha_fin_orig = self.ficha.fecha_fin
        self.ficha.fecha_fin = fecha - timedelta(days=1)
        db.session.commit()
        self.assertIsNone(_proxima_fecha_disponible(self.ficha.id, fecha))
        self.assertIsNone(_programar_reposicion(self.ficha.id, self.aprendices[0], fecha))
        self.ficha.fecha_fin = fecha_fin_orig
        db.session.commit()

        # 4. Cuando no hay compañeros activos disponibles para emparejar
        for a in self.aprendices[1:]:
            a.activo = False
        db.session.commit()
        self.assertIsNone(_programar_reposicion(self.ficha.id, self.aprendices[0], fecha))
        for a in self.aprendices[1:]:
            a.activo = True
        db.session.commit()

    def test_verificar_ausencias_en_turnos_con_100_por_ciento_ausentes_retorna_lista_vacia(self):
        """Si todos los aprendices faltan, verificar_ausencias_en_turnos retorna lista vacía sin marcar falsos reemplazos."""
        from app.services.aseo import verificar_ausencias_en_turnos
        fecha = fechas_futuras(1)[0]
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        self._crear_sesion(fecha, ausentes=tuple(a.id for a in self.aprendices))
        resultado = verificar_ausencias_en_turnos(self.ficha.id, fecha, fecha)
        self.assertEqual(resultado, [])
        db.session.refresh(turno)
        self.assertEqual(turno.aprendiz_1_id, self.aprendices[0].id)
        self.assertEqual(turno.aprendiz_2_id, self.aprendices[1].id)

    def test_reemplazar_ausentes_con_aprendiz_inexistente_es_seguro(self):
        """_reemplazar_ausentes_del_dia es inmune a IDs de aprendices huérfanos sin causar AttributeError."""
        from types import SimpleNamespace
        from app.services.aseo import _reemplazar_ausentes_del_dia
        fecha = date.today()
        turno_mock = SimpleNamespace(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=999999,  # ID que no existe en DB
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            observacion=None,
            auditoria_1=None,
            auditoria_2=None,
            generado_por='sistema',
        )
        presentes = {self.aprendices[2].id, self.aprendices[3].id}
        resultado = _reemplazar_ausentes_del_dia(turno_mock, presentes)
        # El slot 1 con aprendiz inexistente se omite con seguridad; el slot 2 (aprendices[1] ausente) se sustituye
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0].id, self.aprendices[1].id)
        self.assertEqual(turno_mock.aprendiz_1_id, 999999)
        self.assertIn(turno_mock.aprendiz_2_id, presentes)

    def test_verificar_ausencias_en_turnos_rango_con_multiples_turnos_distingue_sustituidos(self):
        """En un rango con varios turnos, verificar_ausencias_en_turnos sólo devuelve los que efectivamente fueron sustituidos."""
        from app.services.aseo import verificar_ausencias_en_turnos
        fechas = fechas_futuras(3)
        # Día 1: con ausencia y suplentes disponibles -> debe sustituirse
        t1 = TurnoAseo(
            ficha_id=self.ficha.id, fecha=fechas[0],
            aprendiz_1_id=self.aprendices[0].id, aprendiz_2_id=self.aprendices[1].id,
            estado='programado', generado_por='sistema',
        )
        # Día 2: todos presentes -> no se sustituye
        t2 = TurnoAseo(
            ficha_id=self.ficha.id, fecha=fechas[1],
            aprendiz_1_id=self.aprendices[2].id, aprendiz_2_id=self.aprendices[3].id,
            estado='programado', generado_por='sistema',
        )
        # Día 3: 100% ausentes -> no se puede sustituir
        t3 = TurnoAseo(
            ficha_id=self.ficha.id, fecha=fechas[2],
            aprendiz_1_id=self.aprendices[4].id, aprendiz_2_id=self.aprendices[5].id,
            estado='programado', generado_por='sistema',
        )
        db.session.add_all([t1, t2, t3])
        db.session.commit()

        self._crear_sesion(fechas[0], ausentes=(self.aprendices[0].id,))
        self._crear_sesion(fechas[1], ausentes=())
        self._crear_sesion(fechas[2], ausentes=tuple(a.id for a in self.aprendices))

        resultado = verificar_ausencias_en_turnos(self.ficha.id, fechas[0], fechas[2])
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0].id, t1.id)
        db.session.refresh(t1)
        self.assertNotEqual(t1.aprendiz_1_id, self.aprendices[0].id)
        db.session.refresh(t2)
        self.assertEqual(t2.aprendiz_1_id, self.aprendices[2].id)
        db.session.refresh(t3)
        self.assertEqual(t3.aprendiz_1_id, self.aprendices[4].id)

    def test_desvincular_aprendiz_de_turnos_futuros_servicio_cobertura(self):
        """desvincular_aprendiz_de_turnos_futuros cubre ramas con y sin turnos futuros y cuando no hay candidatos."""
        from app.services.aseo import desvincular_aprendiz_de_turnos_futuros
        hoy = date.today()

        # Rama 1: Sin turnos futuros asignados
        desvincular_aprendiz_de_turnos_futuros(self.ficha.id, self.aprendices[0].id)

        # Rama 2: Con turno futuro donde hay compañeros activos para reemplazar
        fecha_futura = fechas_futuras(1)[0]
        turno_futuro = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_futura,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno_futuro)
        db.session.commit()

        desvincular_aprendiz_de_turnos_futuros(self.ficha.id, self.aprendices[0].id)
        db.session.commit()
        db.session.refresh(turno_futuro)
        self.assertNotEqual(turno_futuro.aprendiz_1_id, self.aprendices[0].id)
        self.assertEqual(turno_futuro.aprendiz_2_id, self.aprendices[1].id)

        # Rama 3: Cuando no quedan candidatos activos disponibles (elimina el turno)
        for ap in self.aprendices:
            if ap.id != self.aprendices[1].id:
                ap.activo = False
        db.session.commit()

        desvincular_aprendiz_de_turnos_futuros(self.ficha.id, self.aprendices[1].id)
        db.session.commit()
        turno_eliminado = db.session.get(TurnoAseo, turno_futuro.id)
        self.assertIsNone(turno_eliminado)

        # Restaurar estado de aprendices
        for ap in self.aprendices:
            ap.activo = True
        db.session.commit()

    def test_ausente_sustituido_no_incrementa_veces_aseo_al_completar_turno(self):
        """R3: Al completar un turno con sustitución, el ausente no suma veces_aseo y el suplente sí."""
        from app.services.asistencia import guardar_asistencia
        from app.services.aseo import completar_turno
        fecha = fechas_futuras(1)[0]
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        # Ana (0) falta, Bruno (1) y los demás asisten
        registros = {a.id: ('FALTA' if a.id == self.aprendices[0].id else 'ASISTE', None)
                     for a in self.aprendices}
        guardar_asistencia(self.ficha.id, fecha, registros)
        db.session.refresh(turno)

        suplente_id = turno.aprendiz_1_id
        self.assertNotEqual(suplente_id, self.aprendices[0].id)

        # Marcar turno como cumplido
        completar_turno(turno)
        db.session.commit()

        # Ana (ausente original) no debe tener turnos cumplidos
        cnt_ana = ContadorAseo.query.filter_by(aprendiz_id=self.aprendices[0].id).first()
        self.assertEqual(cnt_ana.veces_aseo, 0)

        # El suplente debe tener 1 turno cumplido
        cnt_suplente = ContadorAseo.query.filter_by(aprendiz_id=suplente_id).first()
        self.assertEqual(cnt_suplente.veces_aseo, 1)

        # Bruno (asistió) debe tener 1 turno cumplido
        cnt_bruno = ContadorAseo.query.filter_by(aprendiz_id=self.aprendices[1].id).first()
        self.assertEqual(cnt_bruno.veces_aseo, 1)

    def test_sustitucion_de_ambos_cupos_por_ausencia_doble_asigna_suplentes_distintos(self):
        """Si ambos asignados faltan, se sustituyen ambos cupos por suplentes presentes distintos."""
        from app.services.asistencia import guardar_asistencia
        fecha = fechas_futuras(1)[0]
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        # Ana (0) y Bruno (1) faltan; los demás asisten
        registros = {
            a.id: ('FALTA' if a.id in (self.aprendices[0].id, self.aprendices[1].id) else 'ASISTE', None)
            for a in self.aprendices
        }
        guardar_asistencia(self.ficha.id, fecha, registros)
        db.session.refresh(turno)

        # Ambos cupos cambiaron
        self.assertNotIn(turno.aprendiz_1_id, (self.aprendices[0].id, self.aprendices[1].id))
        self.assertNotIn(turno.aprendiz_2_id, (self.aprendices[0].id, self.aprendices[1].id))
        # Y no son el mismo suplente
        self.assertNotEqual(turno.aprendiz_1_id, turno.aprendiz_2_id)
        # Auditoría debe reflejar ambas suplencias
        self.assertIn('Suplencia por inasistencia', turno.auditoria_1 or '')
        self.assertIn('Suplencia por inasistencia', turno.auditoria_2 or '')

    def test_datos_transparencia_sincroniza_ausencias_proactivamente(self):
        """datos_transparencia detecta ausencias en el mes y devuelve el turno actualizado con el suplente."""
        from app.services.aseo import datos_transparencia
        fecha = fechas_futuras(1)[0]
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno)
        db.session.commit()

        # Creamos sesión con Ana ausente
        self._crear_sesion(fecha, ausentes=(self.aprendices[0].id,))

        datos = datos_transparencia(self.ficha.id, mes=fecha.replace(day=1))
        turno_en_datos = datos['turnos_por_fecha'].get(fecha)
        self.assertIsNotNone(turno_en_datos)
        self.assertNotEqual(turno_en_datos.aprendiz_1_id, self.aprendices[0].id)
        self.assertEqual(turno_en_datos.aprendiz_2_id, self.aprendices[1].id)


if __name__ == '__main__':
    unittest.main()

