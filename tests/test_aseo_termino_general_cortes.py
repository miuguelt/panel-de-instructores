"""Pruebas del cálculo de turnos de aseo en término general, cortes pedagógicos y periodos."""

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
    SesionAsistencia,
    TurnoAseo,
)
from app.models.corte import Corte
from app.services.aseo import (
    completar_turno,
    contar_cumplidos_en_periodo,
    datos_transparencia,
    generar_turnos,
    recalcular_contadores,
)
from app.services.cortes import cambiar_estado_corte
from tests.test_aseo_equidad import fechas_futuras


class AseoTerminoGeneralCortesTestCase(unittest.TestCase):
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
            nombre='Instructor Aseo General',
            correo='instructor.general@sena.edu.co',
            rol='admin',
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='3999999',
            nombre_programa='ADSO - Santander',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=None,
        )
        db.session.add(self.ficha)
        db.session.flush()

        self.aprendices = []
        for numero, (nombre, apellidos) in enumerate(
            (
                ('Carlos', 'Ardila'),
                ('Diana', 'Bermúdez'),
                ('Esteban', 'Camacho'),
                ('Fabiola', 'Duarte'),
            ),
            start=1,
        ):
            aprendiz = Aprendiz(
                documento=f'300{numero}',
                nombre=nombre,
                apellidos=apellidos,
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

    def _crear_sesion(self, fecha):
        sesion = SesionAsistencia(ficha_id=self.ficha.id, fecha=fecha)
        db.session.add(sesion)
        db.session.flush()
        return sesion

    def _cliente_instructor(self):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True
        return cliente

    def _cliente_aprendiz(self, aprendiz):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['aprendiz_id'] = aprendiz.id
            sesion['aprendiz_documento'] = aprendiz.documento
            sesion['aprendiz_ficha_id'] = self.ficha.id
        return cliente

    def test_contar_cumplidos_en_periodo_calcula_solo_rango_y_cumplidos(self):
        """Verifica que contar_cumplidos_en_periodo filtre por fechas y por estado completado."""
        dias = fechas_futuras(4)
        for d in dias:
            self._crear_sesion(d)

        # Turno 1 en dia 0: Carlos y Diana, ambos cumplidos
        t1 = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=dias[0],
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='cumplido',
            completado_1=True,
            completado_2=True,
        )
        # Turno 2 en dia 1: Esteban y Fabiola, solo Esteban cumplió (Fabiola ausente)
        t2 = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=dias[1],
            aprendiz_1_id=self.aprendices[2].id,
            aprendiz_2_id=self.aprendices[3].id,
            estado='cumplido',
            completado_1=True,
            completado_2=False,
        )
        # Turno 3 en dia 2: Carlos y Esteban, programado (no cumplido)
        t3 = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=dias[2],
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[2].id,
            estado='programado',
        )
        # Turno 4 en dia 3: Diana y Fabiola, cumplido pero en otra fecha
        t4 = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=dias[3],
            aprendiz_1_id=self.aprendices[1].id,
            aprendiz_2_id=self.aprendices[3].id,
            estado='cumplido',
            completado_1=True,
            completado_2=True,
        )
        db.session.add_all([t1, t2, t3, t4])
        db.session.commit()

        # Conteo para rango dias[0] a dias[1]: debe contar t1 y t2 (sin Fabiola ausente)
        conteos_periodo = contar_cumplidos_en_periodo(self.ficha.id, dias[0], dias[1])
        self.assertEqual(conteos_periodo.get(self.aprendices[0].id), 1)  # Carlos: 1
        self.assertEqual(conteos_periodo.get(self.aprendices[1].id), 1)  # Diana: 1
        self.assertEqual(conteos_periodo.get(self.aprendices[2].id), 1)  # Esteban: 1
        self.assertNotIn(self.aprendices[3].id, conteos_periodo)  # Fabiola ausente

        # Conteo para rango que incluye dia 3:
        conteos_total = contar_cumplidos_en_periodo(self.ficha.id, dias[0], dias[3])
        self.assertEqual(conteos_total.get(self.aprendices[1].id), 2)  # Diana: 2
        self.assertEqual(conteos_total.get(self.aprendices[3].id), 1)  # Fabiola: 1 en dia 3

    def test_corte_pedagogico_no_reinicia_contador_general(self):
        """Verifica que crear o cerrar un corte pedagógico conserve el término general acumulado."""
        dias = fechas_futuras(2)
        for d in dias:
            self._crear_sesion(d)

        # 1. Carlos y Diana cumplen turno en Corte 1
        corte_1 = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            nombre='Corte 1 - Introducción',
            estado=Corte.ESTADO_ACTIVO,
            fecha_inicio=dias[0] - timedelta(days=10),
        )
        db.session.add(corte_1)
        db.session.commit()

        t1 = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=dias[0],
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='cumplido',
            completado_1=True,
            completado_2=True,
        )
        db.session.add(t1)
        db.session.commit()

        contadores_iniciales = recalcular_contadores(self.ficha.id)
        self.assertEqual(contadores_iniciales[self.aprendices[0].id].veces_aseo, 1)
        self.assertEqual(contadores_iniciales[self.aprendices[1].id].veces_aseo, 1)
        self.assertEqual(contadores_iniciales[self.aprendices[2].id].veces_aseo, 0)
        self.assertEqual(contadores_iniciales[self.aprendices[3].id].veces_aseo, 0)

        # 2. Se cierra Corte 1 y se inicia Corte 2
        cambiar_estado_corte(corte_1, Corte.ESTADO_CERRADO)
        corte_2 = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            nombre='Corte 2 - Desarrollo',
            estado=Corte.ESTADO_ACTIVO,
            fecha_inicio=dias[1],
        )
        db.session.add(corte_2)
        db.session.commit()

        # 3. El contador general NO se reinicia: Carlos y Diana siguen teniendo 1 turno cumplido en total
        contadores_post_corte = recalcular_contadores(self.ficha.id)
        self.assertEqual(contadores_post_corte[self.aprendices[0].id].veces_aseo, 1)
        self.assertEqual(contadores_post_corte[self.aprendices[1].id].veces_aseo, 1)
        self.assertEqual(contadores_post_corte[self.aprendices[2].id].veces_aseo, 0)
        self.assertEqual(contadores_post_corte[self.aprendices[3].id].veces_aseo, 0)

        # 4. Al generar turnos en el nuevo corte, la cola justa prioriza a quienes tienen 0 turnos en total
        resultado = generar_turnos(
            self.ficha.id,
            dias[1],
            dias[1],
            rng=random.Random(42),
        )
        self.assertEqual(len(resultado['creados']), 1)
        turno_corte_2 = resultado['creados'][0]
        pareja_elegida = {turno_corte_2.aprendiz_1_id, turno_corte_2.aprendiz_2_id}
        # Deben ser elegidos estrictamente Esteban y Fabiola (los de 0 turnos en total)
        self.assertEqual(pareja_elegida, {self.aprendices[2].id, self.aprendices[3].id})

    def test_datos_transparencia_y_rutas_incluyen_veces_periodo_y_veces_total(self):
        """Verifica que la estructura de equidad exponga veces_periodo y veces_total y admita ordenamiento."""
        dias = fechas_futuras(2)
        mes_consultado = dias[0].replace(day=1)
        for d in dias:
            self._crear_sesion(d)

        # Carlos cumplió en un mes anterior
        fecha_mes_anterior = (mes_consultado - timedelta(days=15))
        self._crear_sesion(fecha_mes_anterior)
        t_ant = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_mes_anterior,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='cumplido',
            completado_1=True,
            completado_2=True,
        )
        # Diana cumplió en el mes actual
        t_act = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=dias[0],
            aprendiz_1_id=self.aprendices[1].id,
            aprendiz_2_id=self.aprendices[2].id,
            estado='cumplido',
            completado_1=True,
            completado_2=True,
        )
        db.session.add_all([t_ant, t_act])
        db.session.commit()

        datos = datos_transparencia(self.ficha.id, mes=mes_consultado)
        equidad_map = {fila['aprendiz'].id: fila for fila in datos['equidad']}

        # Carlos: 0 en este periodo/mes, 1 en total general
        self.assertEqual(equidad_map[self.aprendices[0].id]['veces_periodo'], 0)
        self.assertEqual(equidad_map[self.aprendices[0].id]['veces_total'], 1)

        # Diana: 1 en este periodo/mes, 2 en total general
        self.assertEqual(equidad_map[self.aprendices[1].id]['veces_periodo'], 1)
        self.assertEqual(equidad_map[self.aprendices[1].id]['veces_total'], 2)

        # Esteban: 1 en este periodo/mes, 1 en total general
        self.assertEqual(equidad_map[self.aprendices[2].id]['veces_periodo'], 1)
        self.assertEqual(equidad_map[self.aprendices[2].id]['veces_total'], 1)

        # Fabiola: 0 en este periodo/mes, 0 en total general
        self.assertEqual(equidad_map[self.aprendices[3].id]['veces_periodo'], 0)
        self.assertEqual(equidad_map[self.aprendices[3].id]['veces_total'], 0)

        # Prueba de respuesta HTTP en vista instructor
        cliente_inst = self._cliente_instructor()
        resp_inst = cliente_inst.get(
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo?mes={mes_consultado.strftime("%Y-%m")}&orden=periodo'
        )
        self.assertEqual(resp_inst.status_code, 200)
        self.assertIn('En periodo'.encode(), resp_inst.data)
        self.assertIn('Total'.encode(), resp_inst.data)

        # Prueba de respuesta HTTP en vista aprendiz gestión
        cliente_apr = self._cliente_aprendiz(self.aprendices[0])
        resp_gest = cliente_apr.get(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/gestionar?mes={mes_consultado.strftime("%Y-%m")}&orden=periodo'
        )
        self.assertEqual(resp_gest.status_code, 200)
        self.assertIn('En periodo'.encode(), resp_gest.data)
        self.assertIn('Total'.encode(), resp_gest.data)

        # Prueba de respuesta HTTP en vista transparencia
        resp_transp = cliente_apr.get(
            f'/aprendiz/{self.ficha.id}/turnos-aseo?mes={mes_consultado.strftime("%Y-%m")}&orden=periodo'
        )
        self.assertEqual(resp_transp.status_code, 200)
        self.assertIn('En periodo'.encode(), resp_transp.data)
        self.assertIn('Total'.encode(), resp_transp.data)

        # Probar orden=veces en las tres rutas
        resp_inst_veces = cliente_inst.get(
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo?mes={mes_consultado.strftime("%Y-%m")}&orden=veces'
        )
        self.assertEqual(resp_inst_veces.status_code, 200)

        resp_gest_veces = cliente_apr.get(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/gestionar?mes={mes_consultado.strftime("%Y-%m")}&orden=veces'
        )
        self.assertEqual(resp_gest_veces.status_code, 200)

        resp_transp_veces = cliente_apr.get(
            f'/aprendiz/{self.ficha.id}/turnos-aseo?mes={mes_consultado.strftime("%Y-%m")}&orden=veces'
        )
        self.assertEqual(resp_transp_veces.status_code, 200)

    def test_datos_transparencia_sin_mes_y_con_turno_futuro(self):
        """Verifica datos_transparencia cuando mes es None e incluye turnos pendientes futuros."""
        dias = fechas_futuras(3)
        self._crear_sesion(dias[0])
        turno_futuro = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=dias[0],
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
        )
        db.session.add(turno_futuro)
        db.session.commit()

        datos = datos_transparencia(self.ficha.id)
        self.assertIn('equidad', datos)
        equidad_map = {fila['aprendiz'].id: fila for fila in datos['equidad']}
        self.assertEqual(equidad_map[self.aprendices[0].id]['proxima'], dias[0])
        self.assertEqual(equidad_map[self.aprendices[1].id]['proxima'], dias[0])
        self.assertIsNone(equidad_map[self.aprendices[2].id]['proxima'])

