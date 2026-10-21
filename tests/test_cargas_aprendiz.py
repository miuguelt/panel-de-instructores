"""Las cargas conservan el archivo anterior y distinguen errores posteriores."""

from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import RegistroAsistencia, PlanMejoramiento, Entrega
from tests import test_flujos_web as apoyo


class TestCargasAprendiz(unittest.TestCase):
    setUp = apoyo.FlujosWebTestCase.setUp
    tearDown = apoyo.FlujosWebTestCase.tearDown
    _autenticar = apoyo.FlujosWebTestCase._autenticar

    def cargar_soporte(self):
        registro = RegistroAsistencia.query.filter_by(aprendiz_id=self.aprendiz.id).one()
        return self.cliente.post(f'/aprendiz/{self.ficha.id}/justificar/{registro.id}',
            data={'documento': self.aprendiz.documento, 'soporte': (BytesIO(b'%PDF-1.4\nsoporte\n%%EOF'), 'soporte.pdf')},
            headers={'X-Requested-With': 'XMLHttpRequest'}, content_type='multipart/form-data')

    def test_soporte_fallo_db_conserva_anterior_y_limpia_nuevo(self):
        registro = RegistroAsistencia.query.filter_by(aprendiz_id=self.aprendiz.id).one()
        anterior = Path(self.uploads.name, 'anterior.pdf')
        anterior.write_bytes(b'%PDF-anterior')
        registro.soporte_url = anterior.name
        db.session.commit()
        with patch('app.routes.aprendiz.db.session.commit', side_effect=SQLAlchemyError('fallo controlado')):
            respuesta = self.cargar_soporte()
        self.assertEqual(respuesta.status_code, 422)
        self.assertIn('guardar', respuesta.json['message'])
        db.session.refresh(registro)
        self.assertEqual(registro.soporte_url, anterior.name)
        self.assertEqual([p for p in Path(self.uploads.name).rglob('*') if p.is_file()], [anterior])

    def test_soporte_confirmado_no_falla_si_indicadores_no_responden(self):
        with patch('app.routes.aprendiz.actualizar_alertas_ficha', side_effect=RuntimeError('fallo controlado')):
            respuesta = self.cargar_soporte()
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.json['ok'])
        self.assertIn('guardado', respuesta.json['message'])
        registro = RegistroAsistencia.query.filter_by(aprendiz_id=self.aprendiz.id).one()
        self.assertTrue(Path(self.uploads.name, registro.soporte_url).is_file())

    def test_reemplazo_soporte_elimina_anterior_despues_de_confirmar(self):
        registro = RegistroAsistencia.query.filter_by(aprendiz_id=self.aprendiz.id).one()
        anterior = Path(self.uploads.name, 'anterior.pdf')
        anterior.write_bytes(b'%PDF-anterior')
        registro.soporte_url = anterior.name
        db.session.commit()
        respuesta = self.cargar_soporte()
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(anterior.exists())
        self.assertEqual(len([p for p in Path(self.uploads.name).rglob('*') if p.is_file()]), 1)

    def test_plan_confirmado_no_se_pierde_si_notificacion_falla(self):
        plan = PlanMejoramiento(ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id,
            creado_por=self.instructor.id, actividades='Adjuntar evidencia.')
        db.session.add(plan)
        db.session.commit()
        self.cliente.post(f'/aprendiz/{self.ficha.id}', data={'documento': self.aprendiz.documento})
        with patch('app.routes.aprendiz.registrar_notificacion', side_effect=RuntimeError('fallo controlado')):
            respuesta = self.cliente.post(f'/aprendiz/{self.ficha.id}/subir-evidencia-plan/{plan.id}',
                data={'archivo_evidencia_plan': (BytesIO(b'%PDF-1.4\nevidencia\n%%EOF'), 'evidencia.pdf')},
                headers={'X-Requested-With': 'XMLHttpRequest'}, content_type='multipart/form-data')
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.json['ok'])
        self.assertIn('guardada', respuesta.json['message'])
        db.session.refresh(plan)
        self.assertTrue(Path(self.uploads.name, plan.evidencia_url).is_file())

    def test_evidencia_xhr_guarda_word_y_zip_y_conserva_anterior_ante_error(self):
        from tests.test_archivos import crear_zip
        self.cliente.post(f'/aprendiz/{self.ficha.id}', data={'documento': self.aprendiz.documento})
        url = f'/aprendiz/{self.ficha.id}/subir-evidencia/{self.tarea.id}'
        cliente = self.cliente
        for nombre, contenido in [('informe.docx', b'PK\x03\x04documento'), ('proyecto.zip', crear_zip())]:
            with self.subTest(nombre=nombre):
                respuesta = cliente.post(url, data={'archivo_evidencia': (BytesIO(contenido), nombre, 'application/octet-stream')},
                    headers={'X-Requested-With': 'XMLHttpRequest'}, content_type='multipart/form-data')
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(respuesta.json['ok'])
                entrega = Entrega.query.filter_by(tarea_id=self.tarea.id, aprendiz_id=self.aprendiz.id).one()
                self.assertEqual(Path(self.uploads.name, entrega.archivo_url).read_bytes(), contenido)
                descarga = cliente.get(f'/aprendiz/descargar-evidencia/{entrega.id}')
                try:
                    self.assertEqual(descarga.status_code, 200)
                    self.assertEqual(descarga.data, contenido)
                finally:
                    descarga.close()
        anterior = entrega.archivo_url
        respuesta = cliente.post(url, data={'archivo_evidencia': (BytesIO(b'PK\x03\x04truncado'), 'error.zip')},
            headers={'X-Requested-With': 'XMLHttpRequest'}, content_type='multipart/form-data')
        self.assertEqual(respuesta.status_code, 422)
        self.assertIn('dañado o incompleto', respuesta.json['message'])
        db.session.refresh(entrega)
        self.assertEqual(entrega.archivo_url, anterior)
        self.assertEqual(len([p for p in Path(self.uploads.name).rglob('*') if p.is_file()]), 1)

