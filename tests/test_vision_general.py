"""Pruebas unitarias y de integración para la Visión General de la Ficha (Ficha 360)."""

from datetime import date, datetime, timedelta
import tempfile
import unittest

from app import create_app, db
from app.models.ficha import Ficha
from app.models.ficha_instructor import FichaInstructor
from app.models.instructor import Instructor
from app.models.aprendiz import Aprendiz
from app.models.asistencia import SesionAsistencia, RegistroAsistencia
from app.models.tarea import Tarea, Entrega, MODALIDAD_EVIDENCIA
from app.models.alertas import Alerta, ConfiguracionAlertas, PlanMejoramiento
from app.models.aseo import TurnoAseo
from app.models.juicio import JuicioEvaluativo
from app.models.observador import NotaObservador
from app.services.resumen_ficha import obtener_resumen_ficha_360


class VisionGeneralTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'UPLOAD_FOLDER': self.tmp_dir.name,
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Instructor principal
        self.instructor = Instructor(
            nombre='Carlos Instructor',
            correo='carlos@sena.edu.co',
            rol='instructor',
        )
        self.instructor.set_password('clave123')

        # Instructor ajeno
        self.otro_instructor = Instructor(
            nombre='Maria Ajena',
            correo='maria@sena.edu.co',
            rol='instructor',
        )
        self.otro_instructor.set_password('clave123')

        db.session.add_all([self.instructor, self.otro_instructor])
        db.session.flush()

        # Ficha de prueba
        self.ficha = Ficha(
            codigo='2890123',
            codigo_ficha='2890123',
            codigo_programa='228118',
            nombre_programa='Análisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
            fecha_inicio=date.today() - timedelta(days=60),
            fecha_fin=date.today() + timedelta(days=180),
            duracion_productiva_meses=6,
        )
        db.session.add(self.ficha)
        db.session.flush()

        db.session.add(FichaInstructor(ficha_id=self.ficha.id, instructor_id=self.instructor.id))

        # Aprendices
        self.ap1 = Aprendiz(
            ficha_id=self.ficha.id,
            documento='1001',
            nombre='Juan',
            apellidos='Perez',
            estado='EN_FORMACION',
        )
        self.ap2 = Aprendiz(
            ficha_id=self.ficha.id,
            documento='1002',
            nombre='Ana',
            apellidos='Gomez',
            estado='EN_FORMACION',
        )
        self.ap3 = Aprendiz(
            ficha_id=self.ficha.id,
            documento='1003',
            nombre='Pedro',
            apellidos='Cancelado',
            estado='CANCELADO',
        )
        db.session.add_all([self.ap1, self.ap2, self.ap3])
        db.session.flush()

        # Tareas
        self.tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo='Taller de Base de Datos',
            descripcion='Modelo entidad relacion',
            modalidad=MODALIDAD_EVIDENCIA,
            fecha_limite=datetime.utcnow() + timedelta(days=5),
        )
        db.session.add(self.tarea)
        db.session.flush()

        # Entrega pendiente de calificar
        self.entrega = Entrega(
            tarea_id=self.tarea.id,
            aprendiz_id=self.ap1.id,
            calificada=False,
            estado_revision='pendiente',
            archivo_url='evidencias/taller.pdf',
        )
        db.session.add(self.entrega)

        # Inasistencias (Juan tiene fallas para semáforo)
        sesion = SesionAsistencia(
            ficha_id=self.ficha.id,
            fecha=date.today() - timedelta(days=2),
        )
        db.session.add(sesion)
        db.session.flush()

        reg1 = RegistroAsistencia(
            sesion_id=sesion.id,
            aprendiz_id=self.ap1.id,
            estado='FALTA',
        )
        reg2 = RegistroAsistencia(
            sesion_id=sesion.id,
            aprendiz_id=self.ap2.id,
            estado='ASISTE',
        )
        db.session.add_all([reg1, reg2])

        # Turno de aseo de hoy
        self.turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=datetime.utcnow().date(),
            aprendiz_1_id=self.ap1.id,
            aprendiz_2_id=self.ap2.id,
            estado='programado',
            completado_1=False,
            completado_2=False,
        )
        db.session.add(self.turno)

        # Juicio evaluativo
        juicio1 = JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=self.ap1.id,
            competencia='Construir algoritmos',
            resultado_aprendizaje='RAP 1',
            juicio='APROBADO',
            huella='huella-test-1',
        )
        juicio2 = JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=self.ap2.id,
            competencia='Construir algoritmos',
            resultado_aprendizaje='RAP 1',
            juicio='POR EVALUAR',
            huella='huella-test-2',
        )
        db.session.add_all([juicio1, juicio2])

        # Alerta activa
        alerta = Alerta(
            ficha_id=self.ficha.id,
            aprendiz_id=self.ap1.id,
            titulo='Inasistencia reiterada',
            mensaje='El aprendiz superó el límite de fallas.',
            estado='activa',
            nivel='amarilla',
        )
        db.session.add(alerta)

        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.tmp_dir.cleanup()

    def _login(self, correo='carlos@sena.edu.co', password='clave123'):
        return self.client.post('/login', data={'correo': correo, 'password': password}, follow_redirects=True)

    def test_servicio_obtener_resumen_ficha_360(self):
        resumen = obtener_resumen_ficha_360(self.ficha)
        self.assertIsNotNone(resumen)
        self.assertEqual(resumen['total_aprendices'], 2)  # Solo activos
        self.assertEqual(resumen['total_aprendices_general'], 3)
        self.assertEqual(resumen['num_entregas_pendientes'], 1)
        self.assertEqual(len(resumen['alertas_activas']), 1)
        self.assertIsNotNone(resumen['turno_aseo_hoy'])
        self.assertEqual(resumen['juicios_totales'], 2)
        self.assertEqual(resumen['juicios_aprobados'], 1)
        self.assertEqual(resumen['pct_juicios'], 50)

    def test_ruta_vision_general_autorizada(self):
        self._login()
        res = self.client.get(f'/instructor/fichas/{self.ficha.id}')
        self.assertEqual(res.status_code, 200)
        contenido = res.get_data(as_text=True)
        self.assertIn('Visión General', contenido)
        self.assertIn('2890123', contenido)
        self.assertIn('Análisis y Desarrollo de Software', contenido)
        self.assertIn('Atención Inmediata de la Ficha', contenido)
        self.assertIn('Entregas por Calificar', contenido)
        self.assertIn('Turno de Aseo Hoy', contenido)

    def test_ruta_vision_general_alias_resumen(self):
        self._login()
        res = self.client.get(f'/instructor/fichas/{self.ficha.id}/resumen')
        self.assertEqual(res.status_code, 200)
        self.assertIn('Atención Inmediata', res.get_data(as_text=True))

    def test_instructor_no_autorizado_es_bloqueado(self):
        self._login(correo='maria@sena.edu.co')
        res = self.client.get(f'/instructor/fichas/{self.ficha.id}', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        # Redirige a fichas por falta de permisos
        self.assertIn('Ficha no encontrada o sin permisos de acceso', res.get_data(as_text=True))

    def test_redireccion_desde_dashboard_con_ficha_id(self):
        self._login()
        res = self.client.get(f'/instructor/?ficha_id={self.ficha.id}', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn(f'/instructor/fichas/{self.ficha.id}', res.headers.get('Location'))
