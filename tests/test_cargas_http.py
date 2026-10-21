"""Regresiones de compatibilidad y mensajes del recorrido de carga."""

from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch

from flask import abort, flash, redirect
from werkzeug.datastructures import FileStorage

from app.models.material import MaterialFicha
from app.services.archivos import ArchivoService, ErrorArchivo, TiposCarpeta
from tests import test_archivos as apoyo


class TestCargasCompatibles(unittest.TestCase):
    setUp = apoyo.ArchivosTestCase.setUp
    tearDown = apoyo.ArchivosTestCase.tearDown
    _listar_uploads = apoyo.ArchivosTestCase._listar_uploads

    def test_binarios_genericos_conservan_validacion_de_contenido(self):
        for nombre, contenido in [('guia.pdf', apoyo.PDF), ('tabla.xlsx', apoyo.DOCX),
                                  ('informe.docx', apoyo.DOCX), ('diapositivas.ppt', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1contenido'),
                                  ('carpeta.7z', b'7z\xbc\xaf\x27\x1ccontenido')]:
            with self.subTest(nombre=nombre):
                resultado = ArchivoService.guardar(
                    FileStorage(BytesIO(contenido), filename=nombre, content_type='application/octet-stream'),
                    TiposCarpeta.ENTREGAS,
                )
                self.assertEqual(Path(resultado.ruta).read_bytes(), contenido)
        with self.assertRaises(ErrorArchivo):
            ArchivoService.guardar(FileStorage(BytesIO(b'contenido falso'), filename='guia.pdf',
                                  content_type='application/octet-stream'), TiposCarpeta.ENTREGAS)

    def test_zip_acepta_alias_de_compresores(self):
        resultado = ArchivoService.guardar(FileStorage(BytesIO(apoyo.crear_zip()), filename='CARPETA.ZIP',
                                           content_type='application/x-compressed'), TiposCarpeta.ENTREGAS)
        self.assertTrue(Path(resultado.ruta).is_file())

    def test_archivo_ausente_o_ilegible_tiene_error_controlado(self):
        with self.assertRaises(ErrorArchivo):
            ArchivoService.guardar(None, TiposCarpeta.ENTREGAS)
        archivo = FileStorage(BytesIO(apoyo.PDF), filename='guia.pdf')
        archivo.close()
        with self.assertRaisesRegex(ErrorArchivo, 'leer'):
            ArchivoService.guardar(archivo, TiposCarpeta.ENTREGAS)
        self.assertEqual(self._listar_uploads(), [])

    def test_importaciones_respetan_limite_sin_parciales(self):
        self.app.config['MAX_UPLOAD_BYTES'] = 10
        with self.assertRaisesRegex(ErrorArchivo, 'máximo permitido'):
            ArchivoService.guardar_crudo(FileStorage(BytesIO(apoyo.PDF), filename='original.xlsx'),
                                         'importaciones', 'original.xlsx')
        self.assertEqual(self._listar_uploads(), [])

    def test_fallo_de_escritura_atomica_limpia_el_archivo_parcial(self):
        with patch('app.services.archivos.os.replace', side_effect=OSError('fallo de almacenamiento')):
            with self.assertRaisesRegex(ErrorArchivo, 'no pudo guardar'):
                ArchivoService.guardar(FileStorage(BytesIO(apoyo.PDF), filename='guia.pdf'), TiposCarpeta.ENTREGAS)
        self.assertEqual(self._listar_uploads(), [])

    def test_xhr_rechazado_muestra_error_sin_consumir_otra_pagina(self):
        respuesta = self.cliente.post(f'/instructor/fichas/{self.ficha.id}/materiales',
            data={'archivo': (BytesIO(b'PK\x03\x04truncado'), 'carpeta.zip')},
            headers={'X-Requested-With': 'XMLHttpRequest'}, content_type='multipart/form-data')
        self.assertEqual(respuesta.status_code, 422)
        self.assertFalse(respuesta.json['ok'])
        self.assertIn('dañado o incompleto', respuesta.json['message'])
        self.assertIsNone(MaterialFicha.query.first())
        with self.cliente.session_transaction() as sesion:
            self.assertFalse(sesion.get('_flashes'))

    def test_xhr_correcto_conserva_flash_hasta_navegacion(self):
        respuesta = self.cliente.post(f'/instructor/fichas/{self.ficha.id}/materiales',
            data={'archivo': (BytesIO(apoyo.PDF), 'guia.pdf')},
            headers={'X-Requested-With': 'XMLHttpRequest'}, content_type='multipart/form-data')
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.json['ok'])
        self.assertIsNotNone(MaterialFicha.query.first())
        with self.cliente.session_transaction() as sesion:
            self.assertTrue(sesion.get('_flashes'))
        pagina = self.cliente.get(respuesta.json['redirect'])
        self.assertIn('success', pagina.text)

    def test_error_json_de_planeacion_no_reaparece_tras_corregir_archivo(self):
        respuesta = self.cliente.post(f'/instructor/fichas/{self.ficha.id}/planeacion/cargar',
            data={'archivo_planeacion': (BytesIO(apoyo.PDF), 'formato.pdf')},
            headers={'X-Requested-With': 'XMLHttpRequest'}, content_type='multipart/form-data')
        self.assertEqual(respuesta.status_code, 422)
        self.assertFalse(respuesta.json['ok'])
        self.assertIn('.xlsx', respuesta.json['message'])
        with self.cliente.session_transaction() as sesion:
            self.assertFalse(sesion.get('_flashes'))

    def test_csrf_y_limite_responden_json_accionable(self):
        url = f'/instructor/fichas/{self.ficha.id}/materiales'
        self.app.config['WTF_CSRF_ENABLED'] = True
        respuesta = self.cliente.post(url, data={'archivo': (BytesIO(apoyo.PDF), 'guia.pdf')},
            headers={'X-Requested-With': 'XMLHttpRequest'}, content_type='multipart/form-data')
        self.assertEqual(respuesta.status_code, 400)
        self.assertTrue(respuesta.json['reload'])
        self.assertIn('expiró', respuesta.json['message'])
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['MAX_CONTENT_LENGTH'] = 100
        respuesta = self.cliente.post(url, data={'archivo': (BytesIO(apoyo.PDF), 'guia.pdf')},
            headers={'X-Requested-With': 'XMLHttpRequest'}, content_type='multipart/form-data')
        self.assertEqual(respuesta.status_code, 413)
        self.assertIn('límite', respuesta.json['message'])

    def test_http_y_sesion_expirada_no_parecen_exito(self):
        @self.app.post('/prueba-carga-error/<int:codigo>')
        def fallo(codigo):
            abort(codigo)

        for codigo in (400, 403, 404, 429, 503):
            with self.subTest(codigo=codigo):
                respuesta = self.cliente.post(f'/prueba-carga-error/{codigo}', data={},
                    headers={'X-Requested-With': 'XMLHttpRequest'}, content_type='multipart/form-data')
                self.assertEqual(respuesta.status_code, codigo)
                self.assertFalse(respuesta.json['ok'])
                self.assertTrue(respuesta.json['message'])
        with self.cliente.session_transaction() as sesion:
            sesion.clear()
        from flask import g
        g.pop('_login_user', None)
        respuesta = self.cliente.post(f'/instructor/fichas/{self.ficha.id}/materiales',
            data={}, headers={'X-Requested-With': 'XMLHttpRequest'}, content_type='multipart/form-data')
        self.assertEqual(respuesta.status_code, 401)
        self.assertIn('sesión', respuesta.json['message'])

    def test_no_convierte_redirecciones_ajenas_a_cargas(self):
        @self.app.post('/prueba-redireccion')
        def redireccion():
            flash('Mensaje de otro formulario.', 'error')
            return redirect('/')

        respuesta = self.cliente.post('/prueba-redireccion', data={},
            headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(respuesta.status_code, 302)

    def test_plantilla_ofrece_formatos_admitidos_y_carpetas_comprimidas(self):
        from html.parser import HTMLParser
        from app import db
        from app.models import Tarea, PlanMejoramiento
        db.session.add_all([
            Tarea(ficha_id=self.ficha.id, instructor_id=self.instructor.id, titulo='Evidencia requerida', requiere_archivo=True),
            Tarea(ficha_id=self.ficha.id, instructor_id=self.instructor.id, titulo='Evidencia opcional', requiere_archivo=False),
            PlanMejoramiento(ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id, actividades='Entregar archivo.'),
        ])
        db.session.commit()
        self.cliente.post(f'/aprendiz/{self.ficha.id}', data={'documento': self.aprendiz.documento})
        pagina = self.cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(pagina.status_code, 200)
        campos = []

        class Campos(HTMLParser):
            def handle_starttag(self, etiqueta, atributos):
                campo = dict(atributos)
                if etiqueta == 'input' and campo.get('name') in {'archivo_evidencia', 'archivo_evidencia_plan', 'soporte'}:
                    campos.append(campo)

        Campos().feed(pagina.text)
        self.assertGreaterEqual(len(campos), 3)
        for campo in campos:
            permitidas = {extension.lstrip('.') for extension in campo['accept'].split(',')}
            self.assertEqual(permitidas, self.app.config['ALLOWED_EXTENSIONS'])
        self.assertIn('comprime la carpeta', pagina.text)

