"""Agregados de «Mis fichas»: una consulta por indicador para todas las fichas."""

import secrets
import unittest
from datetime import date, datetime, timedelta

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor
from app.models.alertas import Alerta, PlanMejoramiento
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.models.juicio import JuicioEvaluativo
from app.models.observador import NotaObservador
from app.models.tarea import Entrega, Tarea
from app.services.estadisticas_fichas import (
    calcular_estadisticas_fichas,
    competencias_mas_debiles,
    consolidar_ficha,
)

AHORA = datetime(2026, 11, 20, 12, 0)


class CompetenciasMasDebilesTest(unittest.TestCase):
    def test_menor_aprobacion_primero_y_desempate_por_volumen(self):
        comps = {'A': {'total': 10, 'aprobados': 9}, 'B': {'total': 4, 'aprobados': 1},
                 'C': {'total': 8, 'aprobados': 2}, 'D': {'total': 0, 'aprobados': 0}}
        self.assertEqual([n for n, _ in competencias_mas_debiles(comps)], ['D', 'C'])
        self.assertEqual([n for n, _ in competencias_mas_debiles(comps, limite=4)], ['D', 'C', 'B', 'A'])
        self.assertEqual(competencias_mas_debiles({}), [])


class ConsolidarFichaTest(unittest.TestCase):
    def test_sin_sesiones_ni_tareas_no_inventa_porcentajes(self):
        extra = consolidar_ficha(activos=5, total=6, sesiones=0, faltas=0, tareas={'total': 0, 'entregas': 0, 'pendientes': 0},
                                 juicios={}, pct_tiempo=12.7)
        self.assertIsNone(extra['pct_asistencia'])
        self.assertIsNone(extra['pct_entregas'])
        self.assertEqual((extra['pct_juicios'], extra['pct_tiempo']), (0, 12))

    def test_porcentajes(self):
        extra = consolidar_ficha(activos=2, total=3, sesiones=4, faltas=1, tareas={'total': 2, 'entregas': 3, 'pendientes': 1},
                                 juicios={'total': 4, 'aprobados': 1}, pct_tiempo=50)
        self.assertEqual((extra['pct_asistencia'], extra['pct_entregas'], extra['pct_juicios']), (87.5, 75, 25))
        self.assertEqual((extra['total_aprendices'], extra['total_aprendices_incl_inactivos']), (2, 3))


class CalcularEstadisticasTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'SQLALCHEMY_ENGINE_OPTIONS': {}})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.yo, self.otro = (Instructor(nombre=n, correo=f'{n}@example.com') for n in ('yo', 'otro'))
        for instructor in (self.yo, self.otro):
            instructor.set_password(secrets.token_urlsafe(16))
        db.session.add_all([self.yo, self.otro])
        db.session.flush()
        self.ficha = Ficha(codigo='7070', nombre_programa='ADSO', instructor_id=self.yo.id)
        self.vacia = Ficha(codigo='7071', nombre_programa='ADSO', instructor_id=self.yo.id)
        db.session.add_all([self.ficha, self.vacia])
        db.session.flush()
        self.ana, self.luis = (Aprendiz(documento=d, nombre=n, apellidos='X', ficha_id=self.ficha.id) for d, n in (('1', 'Ana'), ('2', 'Luis')))
        retirado = Aprendiz(documento='3', nombre='Eva', apellidos='X', ficha_id=self.ficha.id, estado='CANCELADO')
        db.session.add_all([self.ana, self.luis, retirado])
        db.session.flush()
        for dia, (estado_ana, estado_luis) in enumerate([('ASISTE', 'FALTA'), ('FALTA_JUSTIFICADA', 'ASISTE')], start=1):
            sesion = SesionAsistencia(ficha_id=self.ficha.id, fecha=date(2026, 11, dia))
            db.session.add(sesion)
            db.session.flush()
            db.session.add_all([RegistroAsistencia(sesion_id=sesion.id, aprendiz_id=self.ana.id, estado=estado_ana),
                                RegistroAsistencia(sesion_id=sesion.id, aprendiz_id=self.luis.id, estado=estado_luis),
                                RegistroAsistencia(sesion_id=sesion.id, aprendiz_id=retirado.id, estado='FALTA')])
        vencida = Tarea(ficha_id=self.ficha.id, instructor_id=self.yo.id, titulo='Vencida', fecha_limite=AHORA - timedelta(days=1))
        vigente = Tarea(ficha_id=self.ficha.id, instructor_id=self.yo.id, titulo='Vigente', fecha_limite=AHORA + timedelta(days=3))
        ajena = Tarea(ficha_id=self.ficha.id, instructor_id=self.otro.id, titulo='De otro', fecha_limite=AHORA - timedelta(days=1))
        db.session.add_all([vencida, vigente, ajena])
        db.session.flush()
        db.session.add_all([
            Entrega(tarea_id=vencida.id, aprendiz_id=self.ana.id, calificada=True, estado_revision='rechazada'),
            Entrega(tarea_id=vigente.id, aprendiz_id=self.ana.id),
            Alerta(ficha_id=self.ficha.id, titulo='Riesgo', mensaje='m'),
            Alerta(ficha_id=self.ficha.id, titulo='Resuelta', mensaje='m', estado='resuelta'),
            PlanMejoramiento(ficha_id=self.ficha.id, aprendiz_id=self.luis.id, actividades='Repasar'),
            NotaObservador(ficha_id=self.ficha.id, aprendiz_id=self.ana.id, instructor_id=self.yo.id, tipo='positiva', descripcion='Bien'),
            NotaObservador(ficha_id=self.ficha.id, aprendiz_id=self.luis.id, instructor_id=self.yo.id, tipo='negativa', descripcion='Llamado'),
        ])
        for aprendiz, competencia, juicio in [(self.ana, 'Programar', 'APROBADO'), (self.ana, 'Inglés', 'APROBADO'),
                                              (self.luis, 'Programar', 'NO APROBADO'), (self.luis, 'Inglés', 'APROBADO'),
                                              (self.luis, ' ', 'APROBADO')]:
            db.session.add(JuicioEvaluativo(ficha_id=self.ficha.id, aprendiz_id=aprendiz.id, competencia=competencia,
                                            resultado_aprendizaje=f'{competencia}-{aprendiz.id}', juicio=juicio))
        db.session.commit()
        self.cronogramas = {self.ficha.id: {'porcentaje': 40.9}, self.vacia.id: {}}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_agregados_del_instructor(self):
        estados, extra = calcular_estadisticas_fichas([self.ficha, self.vacia], self.cronogramas, instructor_id=self.yo.id, ahora=AHORA)
        self.assertEqual(estados[self.ficha.id], {'total': 3, 'activos': 2, 'estados': {'EN_FORMACION': 2, 'CANCELADO': 1}})
        e = extra[self.ficha.id]
        # 2 sesiones × 2 activos, 1 falta sin justificar (la del retirado no cuenta) → 75 %.
        self.assertEqual((e['sesiones'], e['pct_asistencia']), (2, 75.0))
        # Solo sus 2 tareas; la vencida suma 1 rechazada y 1 aprendiz sin entrega.
        self.assertEqual((e['tareas_totales'], e['entregas_totales'], e['pendientes']), (2, 2, 2))
        self.assertEqual((e['pct_entregas'], e['por_calificar']), (50, 1))
        self.assertEqual((e['juicios_totales'], e['juicios_aprobados'], e['pct_juicios']), (5, 4, 80))
        self.assertEqual(e['aprendices_certificados'], 1)
        self.assertEqual([n for n, _ in e['top_competencias']], ['Programar', 'Inglés'])
        self.assertEqual((e['alertas_activas'], e['planes_pendientes']), (1, 1))
        self.assertEqual((e['notas_positivas'], e['notas_negativas'], e['notas_total']), (1, 1, 2))
        self.assertEqual(e['pct_tiempo'], 40)

    def test_administrador_ve_todas_las_tareas(self):
        _, extra = calcular_estadisticas_fichas([self.ficha], self.cronogramas, instructor_id=None, ahora=AHORA)
        self.assertEqual(extra[self.ficha.id]['tareas_totales'], 3)

    def test_ficha_sin_datos_y_lista_vacia(self):
        _, extra = calcular_estadisticas_fichas([self.ficha, self.vacia], self.cronogramas, instructor_id=self.yo.id, ahora=AHORA)
        vacia = extra[self.vacia.id]
        self.assertIsNone(vacia['pct_asistencia'])
        self.assertEqual((vacia['total_aprendices'], vacia['top_competencias'], vacia['pct_tiempo']), (0, [], 0))
        self.assertEqual(calcular_estadisticas_fichas([], {}), ({}, {}))


if __name__ == '__main__':
    unittest.main()
