import unittest
from datetime import date, datetime
from app import create_app, db
from app.models.ficha import Ficha
from app.models.aprendiz import Aprendiz
from app.models.instructor import Instructor
from app.models.atencion import TurnoAtencion
from app.models.observador import NotaObservador
from app.services.atencion_service import AtencionService

class TestAtencionServiceYFlujo(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.instructor = Instructor(nombre='Instructor Test', correo='test@sena.edu.co', password_hash='hash')
        db.session.add(self.instructor)
        db.session.commit()

        self.ficha = Ficha(codigo='1001', nombre_programa='ADSO', instructor_id=self.instructor.id)
        db.session.add(self.ficha)
        db.session.commit()

        self.aprendiz = Aprendiz(ficha_id=self.ficha.id, documento='12345', nombre='Juan', apellidos='Perez', estado='En formación')
        db.session.add(self.aprendiz)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_solicitar_turno_crea_turno_en_espera(self):
        turno = AtencionService.solicitar_turno(self.ficha.id, self.aprendiz.id, motivo="Duda en proyecto")
        self.assertIsNotNone(turno.id)
        self.assertEqual(turno.estado, 'esperando')
        self.assertEqual(turno.motivo, "Duda en proyecto")

    def test_solicitar_turno_duplicado_retorna_existente(self):
        turno1 = AtencionService.solicitar_turno(self.ficha.id, self.aprendiz.id, motivo="Primera vez")
        turno2 = AtencionService.solicitar_turno(self.ficha.id, self.aprendiz.id, motivo="Segunda vez")
        self.assertEqual(turno1.id, turno2.id)

    def test_obtener_fila_retorna_en_orden(self):
        a2 = Aprendiz(ficha_id=self.ficha.id, documento='99999', nombre='Maria', apellidos='Gomez', estado='En formación')
        db.session.add(a2)
        db.session.commit()

        t1 = AtencionService.solicitar_turno(self.ficha.id, self.aprendiz.id)
        t2 = AtencionService.solicitar_turno(self.ficha.id, a2.id)

        fila = AtencionService.obtener_fila(self.ficha.id)
        self.assertEqual(len(fila), 2)
        self.assertEqual(fila[0].id, t1.id)
        self.assertEqual(fila[1].id, t2.id)

    def test_cambiar_estado_iniciar_atencion_y_finalizar(self):
        turno = AtencionService.solicitar_turno(self.ficha.id, self.aprendiz.id)
        t_en_atencion = AtencionService.cambiar_estado(turno.id, 'en_atencion')
        self.assertEqual(t_en_atencion.estado, 'en_atencion')
        self.assertIsNotNone(t_en_atencion.atendido_en)

        t_fin = AtencionService.cambiar_estado(turno.id, 'atendido')
        self.assertEqual(t_fin.estado, 'atendido')
        self.assertIsNotNone(t_fin.completado_en)

    def test_cambiar_estado_cancelar(self):
        turno = AtencionService.solicitar_turno(self.ficha.id, self.aprendiz.id)
        t_canc = AtencionService.cambiar_estado(turno.id, 'cancelado')
        self.assertEqual(t_canc.estado, 'cancelado')
        self.assertIsNotNone(t_canc.completado_en)

        # La fila ahora debe estar vacia
        self.assertEqual(len(AtencionService.obtener_fila(self.ficha.id)), 0)

    def test_completar_turno_genera_nota_observador_en_seguimiento(self):
        # Simular inicio de sesion de instructor
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.instructor.id)
            sess['_fresh'] = True

        turno = AtencionService.solicitar_turno(self.ficha.id, self.aprendiz.id, motivo="Duda en base de datos")
        AtencionService.cambiar_estado(turno.id, 'en_atencion')

        # Instructor completa el turno via POST
        res = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/fila-atencion/{turno.id}/estado',
            data={'estado': 'atendido'},
            follow_redirects=True
        )
        self.assertEqual(res.status_code, 200)

        # Verificar que se creo la nota en el observador
        nota = NotaObservador.query.filter_by(aprendiz_id=self.aprendiz.id, ficha_id=self.ficha.id).first()
        self.assertIsNotNone(nota)
        self.assertEqual(nota.tipo, 'positiva')
        self.assertEqual(nota.categoria, 'compromiso')
        self.assertIn('Duda en base de datos', nota.descripcion)

