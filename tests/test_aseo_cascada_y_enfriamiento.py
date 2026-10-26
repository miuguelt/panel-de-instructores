"""Pruebas automatizadas para el recálculo en cascada tras ajustes manuales

y la ventana de enfriamiento dinámico (70 % de una ronda de aseo).
"""

from datetime import date, timedelta
import random
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
    asignar_o_actualizar_turno,
    generar_turnos,
    reemplazar_aprendices,
)
from app.services.aseo_motor_puro import calcular_turnos_token_bucket
from tests.test_aseo_equidad import fechas_futuras


class TestAseoCascadaYEnfriamiento(unittest.TestCase):
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
            nombre='Instructor Cascada',
            correo='instructor_cascada@sena.edu.co',
            rol='admin',
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='2999999',
            nombre_programa='ADSO Cascada',
            instructor_id=self.instructor.id,
            fecha_inicio=date.today() - timedelta(days=10),
            fecha_fin=None,
        )
        db.session.add(self.ficha)
        db.session.flush()

        # Crear 10 aprendices para pruebas de cascada y enfriamiento
        self.aprendices = []
        for i in range(1, 11):
            aprendiz = Aprendiz(
                documento=f'300{i:02d}',
                nombre=f'Aprendiz{i}',
                apellidos=f'Apellido{i}',
                estado='EN_FORMACION',
                ficha_id=self.ficha.id,
            )
            db.session.add(aprendiz)
            self.aprendices.append(aprendiz)

        db.session.add(ConfiguracionAlertas(ficha_id=self.ficha.id))
        db.session.add(ConfiguracionRanking(ficha_id=self.ficha.id))
        db.session.commit()

        self.fechas = fechas_futuras(10)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def test_recalculo_en_cascada_libera_aprendiz_adelantado_manualmente(self):
        """Al adelantar manualmente a un aprendiz programado a futuro, la cascada recalcula

        las fechas posteriores sin duplicar al aprendiz ni dejarlo en días consecutivos.
        """
        # Generar turnos automáticos para los primeros 5 días
        generar_turnos(
            self.ficha.id,
            self.fechas[0],
            self.fechas[4],
            rng=random.Random(42),
        )
        db.session.commit()

        turnos_iniciales = (
            TurnoAseo.query.filter(
                TurnoAseo.ficha_id == self.ficha.id,
                TurnoAseo.fecha.between(self.fechas[0], self.fechas[4]),
            )
            .order_by(TurnoAseo.fecha)
            .all()
        )
        self.assertEqual(len(turnos_iniciales), 5)

        # Tomar los aprendices que estaban programados en el día 2 (índice 2)
        turno_dia_2 = turnos_iniciales[2]
        adelantado_1 = db.session.get(Aprendiz, turno_dia_2.aprendiz_1_id)
        adelantado_2 = db.session.get(Aprendiz, turno_dia_2.aprendiz_2_id)

        # Ahora el instructor ajusta manualmente el día 0 para asignar a adelantado_1 y adelantado_2
        turno_dia_0 = turnos_iniciales[0]
        reemplazar_aprendices(
            turno_dia_0,
            adelantado_1,
            adelantado_2,
            observacion='Ajuste manual de prueba',
            recalcular_cascada=True,
        )
        db.session.commit()

        # Verificar que el día 0 quedó con los aprendices manuales y origen instructor
        self.assertEqual(turno_dia_0.aprendiz_1_id, adelantado_1.id)
        self.assertEqual(turno_dia_0.aprendiz_2_id, adelantado_2.id)
        self.assertEqual(turno_dia_0.generado_por, 'instructor')

        # Verificar el día 2 posterior: ya NO debe contener a adelantado_1 ni adelantado_2
        turno_dia_2_actualizado = (
            TurnoAseo.query.filter_by(ficha_id=self.ficha.id, fecha=self.fechas[2]).first()
        )
        pareja_dia_2 = {
            turno_dia_2_actualizado.aprendiz_1_id,
            turno_dia_2_actualizado.aprendiz_2_id,
        }
        self.assertNotIn(
            adelantado_1.id,
            pareja_dia_2,
            "El aprendiz adelantado manualmente no debe repetirse en su turno futuro original.",
        )
        self.assertNotIn(
            adelantado_2.id,
            pareja_dia_2,
            "El aprendiz adelantado manualmente no debe repetirse en su turno futuro original.",
        )

        # Verificar que ningún turno en el rango tiene a una persona en días consecutivos
        todos_turnos = (
            TurnoAseo.query.filter(
                TurnoAseo.ficha_id == self.ficha.id,
                TurnoAseo.fecha.between(self.fechas[0], self.fechas[4]),
            )
            .order_by(TurnoAseo.fecha)
            .all()
        )
        for t1, t2 in zip(todos_turnos[:-1], todos_turnos[1:]):
            p1 = {t1.aprendiz_1_id, t1.aprendiz_2_id}
            p2 = {t2.aprendiz_1_id, t2.aprendiz_2_id}
            interseccion = p1.intersection(p2)
            self.assertEqual(
                len(interseccion),
                0,
                f"Conflicto de días consecutivos entre {t1.fecha} y {t2.fecha}: {interseccion}",
            )

    def test_enfriamiento_dinamico_en_cohorte_completa(self):
        """En un grupo de 10 aprendices (ronda = 5 sesiones, 70 % = 3 sesiones de descanso),

        ningún aprendiz repite turno antes de que pasen al menos 3 sesiones de descanso.
        """
        aprendiz_ids = list(range(1, 11))
        # 10 sesiones = 2 rondas completas de 5 sesiones
        sesiones = [date(2026, 11, d) for d in range(1, 11)]

        resultado = calcular_turnos_token_bucket(
            aprendiz_ids=aprendiz_ids,
            sesiones_fechas=sesiones,
            rng=random.Random(123),
        )

        asigs = resultado['asignaciones']
        self.assertEqual(len(asigs), 10)

        # Registrar el índice de sesión de cada asignación por aprendiz
        sesiones_por_aprendiz = {a_id: [] for a_id in aprendiz_ids}
        for idx, asig in enumerate(asigs):
            a1 = asig['aprendiz_1_id']
            a2 = asig['aprendiz_2_id']
            sesiones_por_aprendiz[a1].append(idx)
            sesiones_por_aprendiz[a2].append(idx)

        # Verificar que cada aprendiz fue asignado exactamente 2 veces (1 por ronda)
        for a_id, indices in sesiones_por_aprendiz.items():
            self.assertEqual(
                len(indices),
                2,
                f"El aprendiz {a_id} debe tener exactamente 2 turnos en 2 rondas.",
            )
            # Distancia entre su primer y segundo turno
            distancia_sesiones = indices[1] - indices[0]
            # Con 70 % de enfriamiento (k = 3), debe haber al menos 3 sesiones de descanso (distancia >= 4)
            self.assertGreaterEqual(
                distancia_sesiones,
                4,
                f"El aprendiz {a_id} repitió demasiado pronto (distancia de {distancia_sesiones} sesiones).",
            )
