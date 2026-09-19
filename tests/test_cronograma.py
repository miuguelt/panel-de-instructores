import unittest
from datetime import date, datetime

from app import create_app, db
from app.models import Alerta, Aprendiz, Ficha, Instructor, Notificacion
from app.services.cronograma import actualizar_alertas_cronograma, obtener_cronograma


class CronogramaTestCase(unittest.TestCase):
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
        instructor = Instructor(nombre='Cronograma', correo='cronograma@sena.edu.co')
        instructor.set_password('x')
        db.session.add(instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='1', nombre_programa='Programa', instructor_id=instructor.id,
                           fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31))
        db.session.add(self.ficha)
        db.session.add(Aprendiz(documento='1', nombre='Ana', apellidos='Pérez', ficha=self.ficha))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def test_calcula_inicio_productiva_y_porcentaje(self):
        cronograma = obtener_cronograma(self.ficha, date(2026, 7, 1))
        self.assertTrue(cronograma['configurado'])
        self.assertEqual(cronograma['inicio_productiva'], date(2026, 6, 30))
        self.assertEqual(cronograma['fase'], 'productiva')
        self.assertGreater(cronograma['porcentaje'], 49)

    def test_alerta_de_finalizacion_es_general_de_ficha(self):
        alertas = actualizar_alertas_cronograma(self.ficha.id, datetime(2026, 12, 10))
        db.session.commit()
        self.assertTrue(alertas)
        self.assertTrue(Alerta.query.filter_by(ficha_id=self.ficha.id, aprendiz_id=None).count())
        self.assertTrue(Notificacion.query.filter_by(ficha_id=self.ficha.id).count())

    def test_dias_para_iniciar_lectiva_y_cierre_ficha(self):
        # 15 días antes de iniciar la etapa lectiva
        cronograma_previo = obtener_cronograma(self.ficha, date(2025, 12, 17))
        self.assertEqual(cronograma_previo['fase'], 'por_iniciar')
        self.assertEqual(cronograma_previo['dias_para_iniciar_lectiva'], 15)
        self.assertFalse(cronograma_previo['etapa_lectiva_iniciada'])
        self.assertTrue(cronograma_previo['alerta_inicio_lectiva']['activa'])
        self.assertEqual(cronograma_previo['alerta_inicio_lectiva']['tipo'], 'proxima')
        self.assertEqual(cronograma_previo['dias_cierre_ficha'], 379)

        # En la fecha exacta de inicio
        cronograma_hoy = obtener_cronograma(self.ficha, date(2026, 1, 1))
        self.assertEqual(cronograma_hoy['dias_para_iniciar_lectiva'], 0)
        self.assertTrue(cronograma_hoy['etapa_lectiva_inicia_hoy'])
        self.assertTrue(cronograma_hoy['alerta_inicio_lectiva']['activa'])
        self.assertEqual(cronograma_hoy['alerta_inicio_lectiva']['tipo'], 'hoy')

        # Cerca al cierre de la ficha (10 días antes)
        cronograma_cierre = obtener_cronograma(self.ficha, date(2026, 12, 21))
        self.assertEqual(cronograma_cierre['dias_cierre_ficha'], 10)
        self.assertTrue(cronograma_cierre['alerta_cierre_ficha']['activa'])
        self.assertEqual(cronograma_cierre['alerta_cierre_ficha']['tipo'], 'inminente')

    def test_alerta_inicio_lectiva_generada_correctamente(self):
        # Generar alerta cuando faltan 10 días para iniciar
        alertas = actualizar_alertas_cronograma(self.ficha.id, datetime(2025, 12, 22))
        db.session.commit()
        self.assertTrue(any(a.tipo == 'cronograma_inicio_lectiva' for a in alertas))
        alerta_db = Alerta.query.filter_by(ficha_id=self.ficha.id, tipo='cronograma_inicio_lectiva', estado='activa').first()
        self.assertIsNotNone(alerta_db)
        self.assertIn('Se acerca el inicio de la etapa lectiva', alerta_db.titulo)


if __name__ == '__main__':
    unittest.main()
