import tempfile
import unittest
from datetime import date, datetime, timedelta
from io import BytesIO
from flask import g

from app import create_app, db
from app.models import (
    Alerta,
    Aprendiz,
    ConfiguracionAlertas,
    ConfiguracionAlertasComite,
    ConfiguracionAseo,
    ConfiguracionRanking,
    Entrega,
    Ficha,
    Instructor,
    NotaObservador,
    Notificacion,
    PlanMejoramiento,
    ProrrogaTarea,
    Tarea,
)
from app.services.alertas import (
    actualizar_alertas_ficha,
    obtener_linea_tiempo,
)
from app.services.tareas import (
    conceder_prorroga_tarea,
    revocar_prorroga_tarea,
)


class ProrrogasYExtemporaneasTestCase(unittest.TestCase):
    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'UPLOAD_FOLDER': self.uploads.name,
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Carlos Instructor', correo='carlos@sena.edu.co', rol='admin'
        )
        self.instructor.set_password('clave123')
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='2670123', codigo_ficha='2670123',
            nombre_programa='ADSO', instructor_id=self.instructor.id,
            fecha_inicio=date.today() - timedelta(days=30),
            fecha_fin=date.today() + timedelta(days=300),
        )
        db.session.add(self.ficha)
        db.session.flush()

        db.session.add_all([
            ConfiguracionAlertas(ficha_id=self.ficha.id),
            ConfiguracionAlertasComite(ficha_id=self.ficha.id, umbral_tareas_incumplidas=1),
            ConfiguracionAseo(ficha_id=self.ficha.id),
            ConfiguracionRanking(ficha_id=self.ficha.id),
        ])

        self.aprendiz = Aprendiz(
            documento='1001234567', nombre='Laura', apellidos='Gomez',
            ficha_id=self.ficha.id, estado='EN_FORMACION'
        )
        db.session.add(self.aprendiz)
        db.session.flush()

        # Tarea vencida ayer
        self.tarea = Tarea(
            ficha_id=self.ficha.id,
            titulo='Evidencia GA1-220501093-AA1',
            descripcion='Documento de especificación de requisitos del sistema.',
            fecha_limite=datetime.utcnow() - timedelta(days=2),
            instructor_id=self.instructor.id,
            requiere_archivo=True,
        )
        db.session.add(self.tarea)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def _aprendiz_cliente(self):
        cliente = self.app.test_client()
        cliente.post(f'/aprendiz/{self.ficha.id}', data={'documento': self.aprendiz.documento})
        return cliente

    def _instructor_cliente(self):
        cliente = self.app.test_client()
        g.pop('_login_user', None)
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True
        return cliente

    def test_servicio_conceder_y_revocar_prorroga(self):
        nueva_fecha = datetime.utcnow() + timedelta(days=5)
        prorroga = conceder_prorroga_tarea(
            tarea_id=self.tarea.id,
            aprendiz_id=self.aprendiz.id,
            nueva_fecha_limite=nueva_fecha,
            motivo='Incapacidad médica justificada oportunamente',
            instructor_id=self.instructor.id,
        )
        self.assertIsNotNone(prorroga)
        self.assertEqual(prorroga.motivo, 'Incapacidad médica justificada oportunamente')
        self.assertEqual(prorroga.instructor_id, self.instructor.id)

        # Verifica notificación al aprendiz
        notif = Notificacion.query.filter_by(
            destinatario_tipo='aprendiz', destinatario_id=self.aprendiz.id
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn('prórroga', notif.mensaje.lower())

        # Revocar prórroga
        ok = revocar_prorroga_tarea(self.tarea.id, self.aprendiz.id)
        self.assertTrue(ok)
        prorroga_revocada = ProrrogaTarea.query.filter_by(
            tarea_id=self.tarea.id, aprendiz_id=self.aprendiz.id
        ).first()
        self.assertIsNone(prorroga_revocada)

    def test_prorroga_pospone_incumplimiento_academico(self):
        # Sin prórroga: la tarea está vencida y debe disparar alerta de incumplimiento
        actualizar_alertas_ficha(self.ficha.id)
        alertas = Alerta.query.filter_by(
            ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id, estado='activa'
        ).all()
        self.assertTrue(any('tarea' in a.titulo.lower() or 'incumplimiento' in a.titulo.lower() for a in alertas))

        # Concede prórroga para dentro de 4 días
        conceder_prorroga_tarea(
            tarea_id=self.tarea.id,
            aprendiz_id=self.aprendiz.id,
            instructor_id=self.instructor.id,
            nueva_fecha_limite=datetime.utcnow() + timedelta(days=4),
            motivo='Prórroga técnica concertada',
        )

        # Al actualizar alertas nuevamente, como tiene prórroga vigente, no debe considerarse incumplimiento vencido
        actualizar_alertas_ficha(self.ficha.id)
        alertas_despues = Alerta.query.filter_by(
            ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id, estado='activa'
        ).all()
        # La alerta previa debió resolverse al no haber tareas pendientes vencidas activas
        self.assertEqual(len(alertas_despues), 0)

    def test_ruta_instructor_gestionar_prorroga(self):
        cliente = self._instructor_cliente()
        nueva_fecha_str = (datetime.utcnow() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')

        # Conceder prórroga vía POST
        resp = cliente.post(
            f'/instructor/tareas/{self.tarea.id}/aprendices/{self.aprendiz.id}/prorroga',
            data={
                'nueva_fecha_limite': nueva_fecha_str,
                'motivo': 'Falla de conectividad en zona rural',
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Pr\xc3\xb3rroga concedida', resp.data)

        prorroga = ProrrogaTarea.query.filter_by(
            tarea_id=self.tarea.id, aprendiz_id=self.aprendiz.id
        ).first()
        self.assertIsNotNone(prorroga)
        self.assertEqual(prorroga.motivo, 'Falla de conectividad en zona rural')

        # Revocar prórroga vía POST
        resp_revocar = cliente.post(
            f'/instructor/tareas/{self.tarea.id}/aprendices/{self.aprendiz.id}/prorroga',
            data={'accion': 'revocar'},
            follow_redirects=True,
        )
        self.assertEqual(resp_revocar.status_code, 200)
        self.assertIn(b'Pr\xc3\xb3rroga revocada', resp_revocar.data)
        self.assertIsNone(ProrrogaTarea.query.filter_by(
            tarea_id=self.tarea.id, aprendiz_id=self.aprendiz.id
        ).first())

    def test_ruta_instructor_anotar_observador_desde_tarea(self):
        cliente = self._instructor_cliente()
        resp = cliente.post(
            f'/instructor/tareas/{self.tarea.id}/aprendices/{self.aprendiz.id}/anotar-observador',
            data={'descripcion': ''},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Se registró un llamado de atención en el Observador'.encode('utf-8'), resp.data)

        nota = NotaObservador.query.filter_by(
            ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id
        ).first()
        self.assertIsNotNone(nota)
        self.assertIn(self.tarea.titulo, nota.descripcion)
        self.assertEqual(nota.categoria, 'compromiso')

    def test_aprendiz_entrega_extemporanea_con_justificacion(self):
        cliente = self._aprendiz_cliente()

        # Verifica que en el panel ve el aviso de entrega extemporánea permitida
        panel = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(panel.status_code, 200)
        self.assertIn('Entrega extemporánea permitida', panel.get_data(as_text=True))
        self.assertIn('justificacion_retraso', panel.get_data(as_text=True))

        # Realiza la entrega extemporánea con justificación
        archivo = (BytesIO(b'%PDF-1.4 prueba de evidencia extemporanea %%EOF'), 'evidencia_tardia.pdf')
        resp = cliente.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{self.tarea.id}',
            data={
                'archivo_evidencia': archivo,
                'enlace_repositorio': 'https://github.com/aprendiz/evidencia',
                'justificacion_retraso': 'Se me presentaron problemas de salud debidamente certificados.',
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        texto = resp.get_data(as_text=True)
        self.assertIn('extemporánea', texto)

        # Verifica en BD
        entrega = Entrega.query.filter_by(tarea_id=self.tarea.id, aprendiz_id=self.aprendiz.id).first()
        self.assertIsNotNone(entrega)
        self.assertEqual(entrega.justificacion_retraso, 'Se me presentaron problemas de salud debidamente certificados.')
        self.assertFalse(entrega.entregada_a_tiempo)
        self.assertTrue(entrega.es_extemporanea)

    def test_asociar_tarea_a_plan_mejoramiento(self):
        cliente = self._instructor_cliente()

        # GET con tarea_id preseleccionada
        vista_plan = cliente.get(
            f'/instructor/fichas/{self.ficha.id}/planes-mejoramiento?aprendiz_id={self.aprendiz.id}&tarea_id={self.tarea.id}'
        )
        self.assertEqual(vista_plan.status_code, 200)
        texto = vista_plan.get_data(as_text=True)
        self.assertIn(self.tarea.titulo, texto)

        # POST para crear plan asociado a la tarea
        resp = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/planes-mejoramiento',
            data={
                'aprendiz_id': self.aprendiz.id,
                'tarea_id': self.tarea.id,
                'actividades': f'Completar y entregar la evidencia de {self.tarea.titulo}',
                'fecha_limite': (date.today() + timedelta(days=10)).isoformat(),
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        plan = PlanMejoramiento.query.filter_by(
            ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id, tarea_id=self.tarea.id
        ).first()
        self.assertIsNotNone(plan)
        self.assertEqual(plan.tarea_id, self.tarea.id)
        self.assertEqual(plan.tarea.titulo, self.tarea.titulo)

        # Verificar que en la lista de planes aparece el origen
        pagina_planes = cliente.get(f'/instructor/fichas/{self.ficha.id}/planes-mejoramiento')
        self.assertEqual(pagina_planes.status_code, 200)
        self.assertIn('Evidencia origen:', pagina_planes.get_data(as_text=True))
        self.assertIn(self.tarea.titulo, pagina_planes.get_data(as_text=True))

    def test_linea_tiempo_comite_incluye_prorrogas_y_justificacion(self):
        # 1. Registrar prórroga
        conceder_prorroga_tarea(
            tarea_id=self.tarea.id,
            aprendiz_id=self.aprendiz.id,
            instructor_id=self.instructor.id,
            nueva_fecha_limite=datetime.utcnow() + timedelta(days=2),
            motivo='Prórroga concertada en comité primario',
        )

        # 2. Registrar entrega extemporánea con justificación
        entrega = Entrega(
            tarea_id=self.tarea.id,
            aprendiz_id=self.aprendiz.id,
            fecha_entrega=datetime.utcnow() + timedelta(days=3),
            archivo_url='evidencia.pdf',
            justificacion_retraso='Entregado posterior al vencimiento por fuerza mayor',
        )
        db.session.add(entrega)
        db.session.commit()

        # 3. Consultar línea de tiempo para comité
        eventos = obtener_linea_tiempo(self.aprendiz.id, self.ficha.id)
        self.assertTrue(len(eventos) > 0)

        # Debe haber evento de prórroga y entrega extemporánea con la justificación
        textos_eventos = [f"{e.get('titulo', '')} {e.get('detalle', '')}" for e in eventos]
        self.assertTrue(any('prórroga' in t.lower() or 'prorroga' in t.lower() for t in textos_eventos))
        self.assertTrue(any('extemporánea' in t.lower() or 'fuerza mayor' in t.lower() for t in textos_eventos))


if __name__ == '__main__':
    unittest.main()
