"""Cabecera de tareas: plazos exclusivos y entregas por calificar."""

import secrets
import unittest
from types import SimpleNamespace

from app import create_app, db
from app.models import Ficha, Instructor
from app.models.aprendiz import Aprendiz
from app.models.tarea import Entrega, Tarea
from app.services.metricas_tareas import contar_por_calificar, resumir_plazos


def tarea(estado):
    return SimpleNamespace(progreso_tiempo={'estado': estado})


class ResumirPlazosTest(unittest.TestCase):
    def test_cada_tarea_cuenta_en_un_solo_grupo(self):
        tareas = [tarea(e) for e in ('normal', 'atencion', 'urgente', 'vencida', 'vencida', 'sin_limite')]
        resumen = resumir_plazos(tareas)
        self.assertEqual(resumen['total'], 6)
        self.assertEqual(resumen['conteo'], {'en_plazo': 2, 'por_vencer': 1, 'vencidas': 2, 'sin_limite': 1})
        self.assertEqual(sum(v for _, v, _ in resumen['segmentos']), 6)
        self.assertEqual(resumen['segmentos'][2], ('Vencidas', 2, 'danger'))

    def test_estado_desconocido_no_se_cuenta_y_vacio(self):
        self.assertEqual(resumir_plazos([tarea('otro')])['conteo']['en_plazo'], 0)
        self.assertEqual(resumir_plazos([])['total'], 0)


class PorCalificarTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        instructor = Instructor(nombre='Instructor', correo='metricas@example.com')
        instructor.set_password(secrets.token_urlsafe(16))
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='222', nombre_programa='ADSO', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.flush()
        self.activo = Aprendiz(documento='1', nombre='Ana', apellidos='Ruiz', ficha_id=ficha.id)
        self.retirado = Aprendiz(documento='2', nombre='Luis', apellidos='Paz', ficha_id=ficha.id,
                                 estado='CANCELADO')
        db.session.add_all([self.activo, self.retirado])
        db.session.flush()
        self.evidencia = Tarea(ficha_id=ficha.id, instructor_id=instructor.id, titulo='E', modalidad='evidencia')
        self.evidencia2 = Tarea(ficha_id=ficha.id, instructor_id=instructor.id, titulo='E2', modalidad='evidencia')
        self.clase = Tarea(ficha_id=ficha.id, instructor_id=instructor.id, titulo='C', modalidad='clase')
        db.session.add_all([self.evidencia, self.evidencia2, self.clase])
        db.session.flush()
        db.session.add_all([
            Entrega(tarea_id=self.evidencia.id, aprendiz_id=self.activo.id),
            Entrega(tarea_id=self.evidencia2.id, aprendiz_id=self.activo.id, calificada=True,
                    estado_revision='aprobada'),
            Entrega(tarea_id=self.evidencia.id, aprendiz_id=self.retirado.id),
            Entrega(tarea_id=self.clase.id, aprendiz_id=self.activo.id),
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_solo_evidencias_sin_calificar_de_aprendices_en_formacion(self):
        self.assertEqual(contar_por_calificar([self.evidencia.id, self.evidencia2.id, self.clase.id]), 1)

    def test_sin_tareas(self):
        self.assertEqual(contar_por_calificar([]), 0)


if __name__ == '__main__':
    unittest.main()
