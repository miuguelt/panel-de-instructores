"""Pruebas de carga y descarga de archivos (evidencias, materiales, soportes)."""

import os
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from io import BytesIO

from flask import g

from app import create_app, db
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.instructor import Instructor
from app.models.material import MaterialFicha
from app.services.archivos import (
    ArchivoService,
    ErrorArchivo,
    ErrorArchivoVacio,
    ErrorMimeType,
    TiposCarpeta,
    mimetype_de,
    nombre_original_desde_ruta,
)

PDF = b'%PDF-1.4\n' + b'contenido de prueba ' * 40 + b'\n%%EOF'
DOCX = b'PK\x03\x04' + b'documento word simulado ' * 20


def crear_zip(archivos=None):
    """Crea un ZIP pequeño y completo para las pruebas de validación."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as paquete:
        for nombre, contenido in (archivos or {'README.txt': 'Evidencia de prueba'}).items():
            paquete.writestr(nombre, contenido)
    return buffer.getvalue()


class ArchivosTestCase(unittest.TestCase):
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
            nombre='Instructor Archivos',
            correo='archivos@sena.edu.co',
            rol='admin',
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='4000001',
            codigo_ficha='4000001',
            nombre_programa='ADSO',
            instructor_id=self.instructor.id,
            fecha_inicio=date.today() - timedelta(days=10),
            fecha_fin=date.today() + timedelta(days=100),
        )
        db.session.add(self.ficha)
        db.session.flush()

        self.aprendiz = Aprendiz(
            documento='2000001',
            nombre='Ana',
            apellidos='Prueba',
            ficha_id=self.ficha.id,
        )
        db.session.add(self.aprendiz)
        db.session.commit()

        self.cliente = self.app.test_client()
        g.pop('_login_user', None)
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    # ------------------------------------------------------------------
    # Guardado
    # ------------------------------------------------------------------
    def _subir_material(self, contenido=PDF, nombre='Guía de Aprendizaje.pdf'):
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/materiales',
            data={'archivo': (BytesIO(contenido), nombre), 'descripcion': 'Material'},
            content_type='multipart/form-data',
        )
        self.assertEqual(respuesta.status_code, 302)
        return MaterialFicha.query.order_by(MaterialFicha.id.desc()).first()

    def test_archivo_vacio_no_se_guarda_ni_deja_residuos(self):
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/materiales',
            data={'archivo': (BytesIO(b''), 'vacio.pdf')},
            content_type='multipart/form-data',
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertIsNone(MaterialFicha.query.first())
        self.assertEqual(self._listar_uploads(), [])

    def test_extension_falsa_se_rechaza_por_firma(self):
        with self.assertRaises(ErrorArchivo):
            from werkzeug.datastructures import FileStorage
            ArchivoService.guardar(
                archivo=FileStorage(
                    stream=BytesIO(b'<html>no soy un pdf</html>'),
                    filename='trampa.pdf',
                    content_type='application/pdf',
                ),
                carpeta=TiposCarpeta.MATERIALES_FICHA,
            )
        self.assertEqual(self._listar_uploads(), [])

    def test_guardado_no_deja_archivos_parciales(self):
        material = self._subir_material()
        archivos = self._listar_uploads()
        self.assertEqual(len(archivos), 1)
        self.assertFalse(any(nombre.endswith('.part') for nombre in archivos))
        ruta = os.path.join(self.uploads.name, material.url_archivo)
        self.assertEqual(os.path.getsize(ruta), len(PDF))

    def test_archivo_vacio_lanza_error_controlado(self):
        from werkzeug.datastructures import FileStorage
        with self.assertRaises(ErrorArchivoVacio):
            ArchivoService.guardar(
                archivo=FileStorage(stream=BytesIO(b''), filename='x.pdf'),
                carpeta=TiposCarpeta.MATERIALES_FICHA,
            )

    def test_zip_valido_acepta_mime_generico_y_conserva_el_archivo(self):
        from werkzeug.datastructures import FileStorage
        contenido = crear_zip({'src/Aplicacion.java': 'class Aplicacion {}'})
        subido = FileStorage(
            stream=BytesIO(contenido),
            filename='proyecto.zip',
            content_type='application/octet-stream',
        )

        resultado = ArchivoService.guardar(
            archivo=subido,
            carpeta=TiposCarpeta.ENTREGAS,
        )

        with open(resultado.ruta, 'rb') as archivo_guardado:
            self.assertEqual(archivo_guardado.read(), contenido)
        self.assertEqual(resultado.tamano, len(contenido))

    def test_zip_autoextraible_y_zip_vacio_son_validos(self):
        from werkzeug.datastructures import FileStorage
        zip_autoextraible = b'MZ-prefijo-' + crear_zip()
        vacio = BytesIO()
        with zipfile.ZipFile(vacio, 'w'):
            pass

        for nombre, contenido in (
            ('instalador.zip', zip_autoextraible),
            ('sin_archivos.zip', vacio.getvalue()),
        ):
            with self.subTest(nombre=nombre):
                resultado = ArchivoService.guardar(
                    archivo=FileStorage(
                        stream=BytesIO(contenido),
                        filename=nombre,
                        content_type='application/x-zip-compressed',
                    ),
                    carpeta=TiposCarpeta.ENTREGAS,
                )
                self.assertEqual(os.path.getsize(resultado.ruta), len(contenido))

    def test_zip_incompleto_tiene_error_accionable(self):
        from werkzeug.datastructures import FileStorage
        with self.assertRaisesRegex(ErrorArchivo, 'está dañado o incompleto'):
            ArchivoService.guardar(
                archivo=FileStorage(
                    stream=BytesIO(b'PK\x03\x04contenido truncado'),
                    filename='proyecto.zip',
                    content_type='application/octet-stream',
                ),
                carpeta=TiposCarpeta.ENTREGAS,
            )
        self.assertEqual(self._listar_uploads(), [])

    def test_zip_con_mime_incompatible_se_rechaza(self):
        from werkzeug.datastructures import FileStorage
        with self.assertRaises(ErrorMimeType):
            ArchivoService.guardar(
                archivo=FileStorage(
                    stream=BytesIO(crear_zip()),
                    filename='proyecto.zip',
                    content_type='text/plain',
                ),
                carpeta=TiposCarpeta.ENTREGAS,
            )
        self.assertEqual(self._listar_uploads(), [])

    def test_zip_respeta_limite_por_archivo_sin_dejar_parciales(self):
        from werkzeug.datastructures import FileStorage
        contenido = crear_zip()
        self.app.config['MAX_UPLOAD_BYTES'] = len(contenido) - 1
        with self.assertRaisesRegex(ErrorArchivo, 'máximo permitido'):
            ArchivoService.guardar(
                archivo=FileStorage(
                    stream=BytesIO(contenido),
                    filename='proyecto.zip',
                    content_type='application/zip',
                ),
                carpeta=TiposCarpeta.ENTREGAS,
            )
        self.assertEqual(self._listar_uploads(), [])

    def test_mime_generico_no_se_acepta_para_otras_extensiones(self):
        from werkzeug.datastructures import FileStorage
        with self.assertRaises(ErrorMimeType):
            ArchivoService.guardar(
                archivo=FileStorage(
                    stream=BytesIO(PDF),
                    filename='evidencia.pdf',
                    content_type='application/octet-stream',
                ),
                carpeta=TiposCarpeta.ENTREGAS,
            )

    # ------------------------------------------------------------------
    # Descarga
    # ------------------------------------------------------------------
    def test_descarga_usa_el_nombre_original_y_mime_correcto(self):
        material = self._subir_material(DOCX, 'Plan de Trabajo.docx')
        respuesta = self.cliente.get(f'/aprendiz/descargar/{material.url_archivo}')
        self.assertEqual(respuesta.status_code, 200)
        disposicion = respuesta.headers['Content-Disposition']
        self.assertIn('attachment', disposicion)
        self.assertIn('Plan_de_Trabajo.docx', disposicion)
        self.assertEqual(
            respuesta.headers['Content-Type'].split(';')[0],
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        self.assertEqual(respuesta.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn('private', respuesta.headers['Cache-Control'])
        respuesta.close()

    def test_descarga_admite_rango_para_reanudar(self):
        material = self._subir_material()
        respuesta = self.cliente.get(
            f'/aprendiz/descargar/{material.url_archivo}',
            headers={'Range': 'bytes=0-9'},
        )
        self.assertEqual(respuesta.status_code, 206)
        self.assertEqual(respuesta.data, PDF[:10])
        self.assertEqual(respuesta.headers['Accept-Ranges'], 'bytes')
        respuesta.close()

    def test_descarga_repetida_responde_304_con_etag(self):
        material = self._subir_material()
        primera = self.cliente.get(f'/aprendiz/descargar/{material.url_archivo}')
        etag = primera.headers.get('ETag')
        primera.close()
        self.assertTrue(etag)

        segunda = self.cliente.get(
            f'/aprendiz/descargar/{material.url_archivo}',
            headers={'If-None-Match': etag},
        )
        self.assertEqual(segunda.status_code, 304)
        segunda.close()

    def test_inline_solo_se_concede_a_formatos_seguros(self):
        pdf = self._subir_material(PDF, 'guia.pdf')
        docx = self._subir_material(DOCX, 'planeacion.docx')

        vista_pdf = self.cliente.get(f'/aprendiz/descargar/{pdf.url_archivo}?inline=1')
        self.assertIn('inline', vista_pdf.headers['Content-Disposition'])
        vista_pdf.close()

        vista_docx = self.cliente.get(f'/aprendiz/descargar/{docx.url_archivo}?inline=1')
        self.assertIn('attachment', vista_docx.headers['Content-Disposition'])
        vista_docx.close()

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def test_nombre_original_quita_el_prefijo_tecnico(self):
        self.assertEqual(
            nombre_original_desde_ruta('tarea_9_ab12cd34ef56_Guia_JEE.docx'),
            'Guia_JEE.docx',
        )
        self.assertEqual(
            nombre_original_desde_ruta('entregas/ficha_2/0a1b2c3d4e5f_informe.pdf'),
            'informe.pdf',
        )
        self.assertEqual(nombre_original_desde_ruta('sin_prefijo.pdf'), 'sin_prefijo.pdf')

    def test_mimetype_conocido_no_depende_del_sistema(self):
        self.assertEqual(
            mimetype_de('xlsx'),
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.assertEqual(mimetype_de('desconocida'), 'application/octet-stream')

    def test_health_reporta_el_estado_del_volumen(self):
        datos = self.cliente.get('/health?uploads=1').get_json()
        self.assertTrue(datos['uploads']['escribible'])
        self.assertIn('archivos', datos['uploads'])

    def test_limite_de_solicitud_reserva_espacio_para_multipart(self):
        self.assertEqual(
            self.app.config['MAX_CONTENT_LENGTH'],
            self.app.config['MAX_UPLOAD_BYTES'] + 1024 * 1024,
        )

    # ------------------------------------------------------------------
    def _listar_uploads(self):
        encontrados = []
        for raiz, _dirs, nombres in os.walk(self.uploads.name):
            encontrados.extend(nombres)
        return encontrados


if __name__ == '__main__':
    unittest.main()
