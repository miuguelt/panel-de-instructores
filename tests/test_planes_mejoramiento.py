import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from io import BytesIO

from flask import g

from app import create_app, db
from app.models import (
    Aprendiz,
    ConfiguracionAlertas,
    ConfiguracionAlertasComite,
    ConfiguracionAseo,
    ConfiguracionRanking,
    Ficha,
    Instructor,
    PlanMejoramiento,
)


class PlanesMejoramientoWebTestCase(unittest.TestCase):
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
            nombre='Instructor Planes', correo='planes@sena.edu.co', rol='admin'
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()
        self.ficha = Ficha(
            codigo='7000001', codigo_ficha='7000001',
            nombre_programa='ADSO', instructor_id=self.instructor.id,
            fecha_inicio=date.today() - timedelta(days=10),
            fecha_fin=date.today() + timedelta(days=300),
        )
        db.session.add(self.ficha)
        db.session.flush()
        db.session.add_all([
            ConfiguracionAlertas(ficha_id=self.ficha.id),
            ConfiguracionAlertasComite(ficha_id=self.ficha.id),
            ConfiguracionAseo(ficha_id=self.ficha.id),
            ConfiguracionRanking(ficha_id=self.ficha.id),
        ])
        self.aprendiz = Aprendiz(
            documento='7000001', nombre='Ana', apellidos='Plan', ficha_id=self.ficha.id
        )
        db.session.add(self.aprendiz)
        db.session.commit()
        self.plan = PlanMejoramiento(
            aprendiz_id=self.aprendiz.id,
            ficha_id=self.ficha.id,
            creado_por=self.instructor.id,
            actividades='Entregar la reflexión y participar en la asesoría.',
            fecha_limite=datetime.utcnow() + timedelta(days=10),
        )
        db.session.add(self.plan)
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

    def test_aprendiz_ve_el_plan_y_puede_enviar_evidencia(self):
        cliente = self._aprendiz_cliente()
        panel = cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(panel.status_code, 200)
        self.assertIn(b'Mis planes de mejoramiento', panel.data)
        self.assertIn(self.plan.actividades.encode(), panel.data)

        respuesta = cliente.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia-plan/{self.plan.id}',
            data={
                'archivo_evidencia_plan': (
                    BytesIO(b'%PDF-1.4\n evidencia del plan\n%%EOF'),
                    'cumplimiento.pdf',
                ),
                'observaciones_aprendiz': 'Realicé las dos actividades acordadas.',
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(self.plan)
        self.assertTrue(self.plan.evidencia_url)
        self.assertTrue(os.path.isfile(os.path.join(self.uploads.name, self.plan.evidencia_url)))
        descarga = cliente.get(f'/aprendiz/descargar-evidencia-plan/{self.plan.id}')
        self.assertEqual(descarga.status_code, 200)
        self.assertTrue(descarga.data.startswith(b'%PDF'))
        descarga.close()

    def test_instructor_no_puede_cerrar_sin_evidencia_y_luego_puede_revisarla(self):
        cliente = self._instructor_cliente()
        bloqueado = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/planes/{self.plan.id}/cumplir',
            follow_redirects=True,
        )
        self.assertIn('aún no ha enviado evidencia'.encode(), bloqueado.data)
        db.session.refresh(self.plan)
        self.assertEqual(self.plan.estado, 'pendiente')

        aprendiz_cliente = self._aprendiz_cliente()
        aprendiz_cliente.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia-plan/{self.plan.id}',
            data={
                'archivo_evidencia_plan': (
                    BytesIO(b'%PDF-1.4\n evidencia revisable\n%%EOF'),
                    'revisable.pdf',
                ),
            },
            content_type='multipart/form-data',
        )
        db.session.refresh(self.plan)
        pagina = cliente.get(f'/instructor/fichas/{self.ficha.id}/planes-mejoramiento')
        self.assertEqual(pagina.status_code, 200)
        self.assertIn(b'Evidencia del aprendiz', pagina.data)
        descarga = cliente.get(f'/instructor/planes/{self.plan.id}/evidencia')
        self.assertEqual(descarga.status_code, 200)
        self.assertTrue(descarga.data.startswith(b'%PDF'))
        descarga.close()
        cerrado = cliente.post(
            f'/instructor/fichas/{self.ficha.id}/planes/{self.plan.id}/cumplir',
            data={'observaciones_instructor': 'Evidencia revisada.'},
        )
        self.assertEqual(cerrado.status_code, 302)
        db.session.refresh(self.plan)
        self.assertEqual(self.plan.estado, 'cumplido')
        self.assertEqual(self.plan.observaciones_instructor, 'Evidencia revisada.')


if __name__ == '__main__':
    unittest.main()
