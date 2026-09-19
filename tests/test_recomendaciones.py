"""Pruebas unitarias para el motor de recomendaciones pedagógicas y logros formativos."""

from datetime import date, datetime, timedelta
import unittest

from app import create_app, db
from app.models.ficha import Ficha
from app.models.instructor import Instructor
from app.models.aprendiz import Aprendiz
from app.models.asistencia import SesionAsistencia, RegistroAsistencia
from app.models.tarea import Tarea, Entrega, MODALIDAD_EVIDENCIA
from app.models.alertas import Alerta, PlanMejoramiento
from app.models.juicio import JuicioEvaluativo
from app.services.recomendaciones import (
    obtener_recomendaciones_ficha,
    obtener_recomendaciones_aprendiz,
    obtener_logros_aprendiz,
    CAT_FASES,
    CAT_TAREAS,
    CAT_ASISTENCIA,
    SEV_CRITICA,
    SEV_PREVENTIVA,
)


class RecomendacionesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.instructor = Instructor(nombre='Instructor Demo', correo='inst@sena.edu.co', rol='instructor')
        self.instructor.set_password('clave123')
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='2890001',
            codigo_ficha='2890001',
            codigo_programa='228118',
            nombre_programa='ADSO',
            instructor_id=self.instructor.id,
            fecha_inicio=date.today() - timedelta(days=90),
            fecha_fin=date.today() + timedelta(days=270),
        )
        db.session.add(self.ficha)
        db.session.flush()

        self.aprendiz1 = Aprendiz(
            documento='1001',
            nombre='Carlos',
            apellidos='Gomez',
            ficha_id=self.ficha.id,
            estado='EN_FORMACION',
        )
        self.aprendiz2 = Aprendiz(
            documento='1002',
            nombre='Ana',
            apellidos='Perez',
            ficha_id=self.ficha.id,
            estado='EN_FORMACION',
        )
        db.session.add_all([self.aprendiz1, self.aprendiz2])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_recomendacion_desfase_fases(self):
        """Verifica que un desfase entre fase esperada y real dispare la recomendación adecuada."""
        fases_mock = {
            'disponible': True,
            'desfase_fases': 1,
            'fase_esperada': {'nombre': 'EJECUCIÓN', 'orden': 3},
            'fase_real': {'nombre': 'ANÁLISIS', 'orden': 2, 'resultados_total': 10, 'resultados_aprobados': 6},
        }
        contexto = {
            'fases_data': fases_mock,
            'cronograma': {'configurado': True},
        }
        recoms = obtener_recomendaciones_ficha(self.ficha.id, contexto_precalculado=contexto)
        desfase_rec = next((r for r in recoms if r.categoria == CAT_FASES and 'Priorizar evaluaciones' in r.titulo), None)
        self.assertIsNotNone(desfase_rec)
        self.assertEqual(desfase_rec.severidad, SEV_PREVENTIVA)
        self.assertIn('Análisis', desfase_rec.titulo)
        self.assertIn('Ejecución', desfase_rec.mensaje)

    def test_recomendacion_entregas_sin_calificar(self):
        """Verifica detección de cuello de botella docente en tareas."""
        tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo='Diagrama de Clases UML',
            modalidad=MODALIDAD_EVIDENCIA,
            fecha_limite=datetime.utcnow() - timedelta(days=5),
        )
        db.session.add(tarea)
        db.session.flush()

        entrega = Entrega(
            tarea_id=tarea.id,
            aprendiz_id=self.aprendiz1.id,
            calificada=False,
            estado_revision='pendiente',
            fecha_entrega=datetime.utcnow() - timedelta(days=4),
        )
        db.session.add(entrega)
        db.session.commit()

        recoms = obtener_recomendaciones_ficha(self.ficha.id)
        rec_calif = next((r for r in recoms if r.categoria == CAT_TAREAS and 'Priorizar calificación' in r.titulo), None)
        self.assertIsNotNone(rec_calif)
        self.assertIn('esperando retroalimentación', rec_calif.mensaje)

    def test_recomendacion_aprendiz_tarea_urgente(self):
        """Verifica que el aprendiz reciba recomendación de tarea próxima a vencer."""
        ahora = datetime.utcnow()
        tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo='API REST con Flask',
            modalidad=MODALIDAD_EVIDENCIA,
            fecha_limite=ahora + timedelta(hours=20),
        )
        db.session.add(tarea)
        db.session.commit()

        recoms_ap = obtener_recomendaciones_aprendiz(self.ficha.id, self.aprendiz1.id, ahora=ahora)
        rec_tarea = next((r for r in recoms_ap if 'API REST' in r.titulo), None)
        self.assertIsNotNone(rec_tarea)
        self.assertEqual(rec_tarea.severidad, SEV_CRITICA)
        self.assertEqual(rec_tarea.destinatario, 'aprendiz')

    def test_logros_aprendiz_calculo(self):
        """Verifica cálculo y estructura de los logros formativos."""
        # Creamos 5 entregas a tiempo para el aprendiz 1
        for i in range(5):
            t = Tarea(
                ficha_id=self.ficha.id,
                instructor_id=self.instructor.id,
                titulo=f'Actividad {i}',
                modalidad=MODALIDAD_EVIDENCIA,
                fecha_limite=datetime.utcnow() + timedelta(days=1),
            )
            db.session.add(t)
            db.session.flush()
            e = Entrega(
                tarea_id=t.id,
                aprendiz_id=self.aprendiz1.id,
                calificada=True,
                estado_revision='aprobada',
                fecha_entrega=datetime.utcnow() - timedelta(hours=2),
            )
            db.session.add(e)
        db.session.commit()

        res_logros = obtener_logros_aprendiz(self.ficha.id, self.aprendiz1.id)
        self.assertIn('logros', res_logros)
        logro_puntualidad = next((l for l in res_logros['logros'] if l.codigo == 'LOG_PUNTUALIDAD_TAREAS'), None)
        self.assertIsNotNone(logro_puntualidad)
        self.assertTrue(logro_puntualidad.desbloqueado)
        self.assertEqual(logro_puntualidad.porcentaje, 100)

    def test_recomendacion_asistencia_riesgo_aprendiz(self):
        """Verifica advertencia de asistencia al acercarse al 75%."""
        # 10 sesiones: 2 faltas = 80% (zona preventiva 75-82%)
        for i in range(10):
            s = SesionAsistencia(ficha_id=self.ficha.id, fecha=date.today() - timedelta(days=i + 1))
            db.session.add(s)
            db.session.flush()
            reg = RegistroAsistencia(
                sesion_id=s.id,
                aprendiz_id=self.aprendiz1.id,
                estado='FALTA' if i < 2 else 'PRESENTE',
            )
            db.session.add(reg)
        db.session.commit()

        recoms = obtener_recomendaciones_aprendiz(self.ficha.id, self.aprendiz1.id)
        rec_asis = next((r for r in recoms if r.categoria == CAT_ASISTENCIA and 'límite reglamentario' in r.titulo), None)
        self.assertIsNotNone(rec_asis)
        self.assertIn('80%', rec_asis.mensaje)
        self.assertEqual(rec_asis.severidad, SEV_PREVENTIVA)

    def test_recomendacion_plan_mejoramiento_urgente(self):
        """Verifica alerta de plan de mejoramiento próximo a vencer."""
        ahora = datetime.utcnow()
        plan = PlanMejoramiento(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz1.id,
            creado_por=self.instructor.id,
            actividades='Entregar informe de base de datos',
            fecha_creacion=ahora - timedelta(days=5),
            fecha_limite=ahora + timedelta(days=1),
            estado='pendiente',
        )
        db.session.add(plan)
        db.session.commit()

        recoms = obtener_recomendaciones_aprendiz(self.ficha.id, self.aprendiz1.id, ahora=ahora)
        rec_plan = next((r for r in recoms if 'plan de mejoramiento' in r.titulo), None)
        self.assertIsNotNone(rec_plan)
        self.assertEqual(rec_plan.severidad, SEV_CRITICA)

    def test_ruta_panel_aprendiz_renderiza_recomendaciones_y_logros(self):
        """Verifica que /aprendiz/<ficha_id>/panel renderice las recomendaciones y logros."""
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['aprendiz_documento'] = self.aprendiz1.documento
            sess['aprendiz_ficha_id'] = self.ficha.id

        res = client.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Tus Logros y Reconocimientos Formativos', html)
        self.assertIn('Racha de Hierro', html)
        self.assertIn('Entregas Impecables', html)

