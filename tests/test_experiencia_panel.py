"""Integración del inicio con datos reales de entregas y ajustes guardados."""

import json
import re
import secrets
import unittest
from datetime import datetime, timedelta

from app import create_app, db
from app.models import Aprendiz, Entrega, Ficha, Instructor, Tarea


class ExperienciaPanelTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
                               'SECRET_KEY': secrets.token_hex(32), 'RATELIMIT_ENABLED': False})
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        instructor = Instructor(nombre='Instructor de pruebas', correo='docente@example.com')
        instructor.set_password(secrets.token_urlsafe(32))
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='PRUEBA-UX', nombre_programa='ADSO', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.flush()
        aprendiz = Aprendiz(documento='3001', nombre='Ana', apellidos='Pruebas', ficha_id=ficha.id)
        otro = Aprendiz(documento='3002', nombre='Luis', apellidos='Pruebas', ficha_id=ficha.id)
        db.session.add_all([aprendiz, otro])
        db.session.flush()
        ahora = datetime.utcnow()
        tareas = [Tarea(ficha_id=ficha.id, instructor_id=instructor.id, titulo=titulo,
                        requiere_archivo=False, fecha_limite=ahora + timedelta(days=2))
                  for titulo in ('Diseñar solución', 'Explicar decisiones', 'Probar solución')]
        db.session.add_all(tareas)
        db.session.flush()
        db.session.add_all([
            Entrega(tarea_id=tareas[0].id, aprendiz_id=aprendiz.id, estado_revision='rechazada',
                    feedback='Explica la decisión y vuelve a enviar.', calificada=True,
                    enlace_repositorio='https://example.com/evidencia'),
            Entrega(tarea_id=tareas[1].id, aprendiz_id=aprendiz.id, estado_revision='aprobada',
                    feedback='La explicación es clara.', calificada=True),
        ])
        db.session.commit()
        self.aprendiz_id, self.ficha_id = aprendiz.id, ficha.id
        self.tarea_ids = [tarea.id for tarea in tareas]
        self.client = self.app.test_client()
        with self.client.session_transaction() as sesion:
            sesion['aprendiz_documento'] = '3001'
            sesion['aprendiz_ficha_id'] = ficha.id

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def panel(self):
        respuesta = self.client.get(f'/aprendiz/{self.ficha_id}/panel')
        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.get_data(as_text=True)
        datos = json.loads(re.search(r'id="aprendiz-experiencia-data"[^>]*>(.*?)</script>', html, re.S).group(1))
        return html, datos

    def test_inicio_prioriza_correccion_muestra_estados_y_registra_hito_real(self):
        html, datos = self.panel()
        self.assertLess(html.index('id="aprendiz-experiencia"'), html.index('learner-priority-dashboard'))
        self.assertEqual(datos['next_action']['taskId'], self.tarea_ids[0])
        self.assertEqual(datos['evidence'], {'submitted': 2, 'review': 0, 'changes': 1, 'approved': 1})
        self.assertEqual(datos['weekly']['count'], 2)
        self.assertEqual(datos['milestones'][0]['title'], 'Primer paso')
        self.assertIn('Requiere ajustes', html)
        self.assertIn('Revisión aprobada', html)
        self.assertIn(f'data-experience-task-id="{self.tarea_ids[0]}"', html)

    def test_guardado_se_recupera_y_no_se_mezcla_con_otro_aprendiz(self):
        _, datos = self.panel()
        preferencias = {**datos['preferences'], 'weeklyGoal': 4, 'notificationMode': 'quiet',
                       'rankingVisible': False, 'reducedMotion': True, 'density': 'compact',
                       'resume': {'tab': 'evidencias', 'taskId': self.tarea_ids[2]}}
        respuesta = self.client.post(f'/aprendiz/{self.ficha_id}/experiencia',
                                    json={'preferences': preferencias, 'revision': datos['revision']},
                                    headers={'X-Learner-Id': str(self.aprendiz_id)})
        self.assertEqual(respuesta.status_code, 200)
        _, recargados = self.panel()
        self.assertEqual(recargados['preferences'], preferencias)
        self.assertEqual(recargados['weekly']['target'], 4)
        with self.client.session_transaction() as sesion:
            sesion['aprendiz_documento'] = '3002'
        _, ajenos = self.panel()
        self.assertEqual(ajenos['preferences']['weeklyGoal'], 2)
        self.assertIsNone(ajenos['preferences']['resume'])
        self.assertEqual(ajenos['milestones'], [])

    def test_reenviar_refresca_estado_y_siguiente_accion_sin_borrar_hito(self):
        self.panel()
        respuesta = self.client.post(f'/aprendiz/{self.ficha_id}/subir-evidencia/{self.tarea_ids[0]}',
                                    data={'enlace_repositorio': 'https://example.com/ajustes'})
        self.assertEqual(respuesta.status_code, 302)
        html, datos = self.panel()
        self.assertEqual(datos['evidence']['changes'], 0)
        self.assertEqual(datos['evidence']['review'], 1)
        self.assertEqual(datos['next_action']['taskId'], self.tarea_ids[2])
        self.assertIn('Recibida · En revisión', html)
        self.assertEqual(len(datos['milestones']), 1)
