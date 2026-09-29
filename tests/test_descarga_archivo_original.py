import io
import unittest
import zipfile
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import openpyxl

from app import create_app, db
from app.models import Aprendiz, ArchivoFichaVersion, Ficha, Instructor, JuicioEvaluativo
from app.services.archivos import nombre_original_desde_ruta
from app.services.versiones_archivos import (
    asegurar_version_reporte,
    buscar_archivo_reporte_original,
)
from tests.apoyo_planeacion import crear_planeacion_xlsx
from tests.apoyo_programa import crear_programa_pdf


def _crear_reporte_sofia_test(ruta_destino, codigo_ficha, fecha_str='12/09/2026'):
    """Genera un archivo Excel con la estructura de cabeceras oficiales de SOFIA Plus."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Hoja'
    ws.append(['Reporte de Juicios de Evaluación', '', '', '', ''])
    ws.append(['Fecha del Reporte:', '', fecha_str, '', ''])
    ws.append(['Ficha de Caracterización:', '', str(codigo_ficha), '', ''])
    ws.append(['Código:', '', '228118', '', ''])
    ws.append(['Versión:', '', 1, '', ''])
    ws.append(['Denominación:', '', 'ANALISIS Y DESARROLLO DE SOFTWARE', '', ''])
    ws.append(['Estado de la Ficha de Caracterización:', '', 'EN EJECUCION', '', ''])
    ws.append(['Fecha Inicio:', '', '2026-01-01', '', ''])
    ws.append(['Fecha Fin:', '', '2026-12-31', '', ''])
    ws.append(['Modalidad de Formación:', '', 'PRESENCIAL', '', ''])
    ws.append(['Regional:', '', '68 - REGIONAL SANTANDER', '', ''])
    ws.append(['Centro de Formación:', '', '9546 - CENTRO DE GESTION AGROEMPRESARIAL', '', ''])
    ws.append([
        'Tipo de Documento', 'Número de Documento', 'Nombre', 'Apellidos',
        'Estado', 'Competencia', 'Resultado de Aprendizaje',
        'Juicio de Evaluación', '', 'Fecha y Hora del Juicio Evaluativo',
        'Funcionario que registro el juicio evaluativo'
    ])
    ws.append([
        'CC', '1005248950', 'CRISTIAN YESID', 'MUÑOZ QUIROGA', 'EN FORMACION',
        '2 - RESULTADOS', '590803 - APLICAR', 'APROBADO', '',
        '12/09/2026 10:00:00', 'INSTRUCTOR'
    ])
    ruta = Path(ruta_destino)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    wb.save(ruta)
    return ruta


class DescargaArchivoOriginalTestCase(unittest.TestCase):
    def setUp(self):
        self.uploads = TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'UPLOAD_FOLDER': self.uploads.name,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor = Instructor(nombre='Instructor Prueba', correo='instructor@sena.edu.co')
        self.instructor.set_password('secreto123')
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='3235642',
            codigo_ficha='3235642',
            codigo_programa='228118',
            nombre_programa='Analisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 12, 31),
        )
        db.session.add(self.ficha)
        db.session.commit()

        self.cliente = self.app.test_client()
        self.cliente.post('/login', data={'correo': self.instructor.correo, 'password': 'secreto123'})

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def test_nombre_original_desde_ruta_limpia_prefijos_tecnicos_y_versiones(self):
        casos = {
            'v1_8f39f712876a48dc987d54244bfc36ea_Reporte_de_Juicios_Evaluativos_37.xls':
                'Reporte_de_Juicios_Evaluativos_37.xls',
            'v5_0950d782c83842d391567da2e72a9ad2_Reporte_de_Juicios_Evaluativos_37.xls':
                'Reporte_de_Juicios_Evaluativos_37.xls',
            'tarea_9_ab12cd34ef56_Guia_JEE.docx':
                'Guia_JEE.docx',
            'v1_8741a23244f64031b8e7439f7dd7c2bd_Planeacion.xlsx':
                'Planeacion.xlsx',
            'sin_prefijo.pdf':
                'sin_prefijo.pdf',
        }
        for entrada, esperado in casos.items():
            self.assertEqual(nombre_original_desde_ruta(entrada), esperado)

    def test_descargar_version_usa_nombre_original_sin_prefijo_v1(self):
        # Crear archivo físico
        dir_ficha = Path(self.uploads.name) / f'fichas/{self.ficha.id}/planeacion'
        dir_ficha.mkdir(parents=True, exist_ok=True)
        arch_disco = dir_ficha / 'v1_abc12345678901234567890123456789_Planeacion_Pedagogica.xlsx'
        arch_disco.write_bytes(b'dummy content')

        version = ArchivoFichaVersion(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            tipo='planeacion',
            version=1,
            nombre_archivo='Planeacion_Pedagogica.xlsx',
            ruta_archivo=f'fichas/{self.ficha.id}/planeacion/{arch_disco.name}',
            hash_sha256='abc',
            tamano_bytes=len(b'dummy content'),
            estado='procesado',
        )
        db.session.add(version)
        db.session.commit()

        resp = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/planeacion/archivos/{version.id}/descargar'
        )
        self.assertEqual(resp.status_code, 200)
        disp = resp.headers.get('Content-Disposition', '')
        self.assertIn('Planeacion_Pedagogica.xlsx', disp)
        self.assertNotIn('v1_Planeacion_Pedagogica.xlsx', disp)
        resp.close()

    def test_descargar_todos_zip_contiene_nombres_originales_limpios(self):
        ruta_plan = crear_planeacion_xlsx(self.uploads.name)
        ruta_prog = crear_programa_pdf(self.uploads.name)

        with ruta_plan.open('rb') as s_plan, ruta_prog.open('rb') as s_prog:
            self.cliente.post(
                f'/instructor/fichas/{self.ficha.id}/planeacion/cargar-todo',
                data={
                    'archivo_planeacion': (s_plan, 'Planeacion_Oficial.xlsx'),
                    'archivo_programa': (s_prog, 'Programa_Oficial.pdf'),
                },
                content_type='multipart/form-data',
                follow_redirects=True,
            )

        resp_zip = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/planeacion/descargar-todos')
        self.assertEqual(resp_zip.status_code, 200)
        self.assertEqual(resp_zip.mimetype, 'application/zip')

        with zipfile.ZipFile(io.BytesIO(resp_zip.data)) as zf:
            nombres = zf.namelist()
            self.assertIn('Planeacion_Oficial.xlsx', nombres)
            self.assertIn('Programa_Oficial.pdf', nombres)
            for n in nombres:
                self.assertFalse(n.startswith('v1_'), f'El nombre {n} no debería tener prefijo v1_')

    def test_buscar_archivo_reporte_original_localiza_candidato_valido(self):
        # Crear un archivo auténtico en uploads/fichas/99/reporte_juicios/
        ruta_original = Path(self.uploads.name) / 'fichas/99/reporte_juicios/v5_12345678901234567890123456789012_Reporte_de_Juicios_Evaluativos_37.xlsx'
        _crear_reporte_sofia_test(ruta_original, self.ficha.codigo, fecha_str='12/09/2026')

        match = buscar_archivo_reporte_original(self.ficha)
        self.assertIsNotNone(match)
        self.assertEqual(match['path'].resolve(), ruta_original.resolve())

    def test_asegurar_version_reporte_actualiza_version_sintetica_con_archivo_original(self):
        # 1. Crear una versión sintética previa generada por openpyxl
        dir_rep = Path(self.uploads.name) / f'fichas/{self.ficha.id}/reporte_juicios'
        dir_rep.mkdir(parents=True, exist_ok=True)
        arch_sintetico = dir_rep / f'v1_dummy_Reporte_de_Juicios_Evaluativos_{self.ficha.codigo}.xlsx'
        arch_sintetico.write_bytes(b'fake openpyxl content')

        version_sintetica = ArchivoFichaVersion(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            tipo='reporte_juicios',
            version=1,
            nombre_archivo=f'Reporte_de_Juicios_Evaluativos_{self.ficha.codigo}.xlsx',
            ruta_archivo=f'fichas/{self.ficha.id}/reporte_juicios/{arch_sintetico.name}',
            hash_sha256='hash_fake',
            tamano_bytes=len(b'fake openpyxl content'),
            estado='procesado',
            detalle='27 aprendices, 2025 juicios sincronizados',
        )
        db.session.add(version_sintetica)
        db.session.commit()

        # 2. Guardar un reporte original auténtico de SOFIA Plus en otra subcarpeta de uploads
        ruta_autentica = Path(self.uploads.name) / 'fichas/3/reporte_juicios/v5_0950d782c83842d391567da2e72a9ad2_Reporte_de_Juicios_Evaluativos_37.xlsx'
        _crear_reporte_sofia_test(ruta_autentica, self.ficha.codigo, fecha_str='12/09/2026')

        # 3. Invocar asegurar_version_reporte
        version_actualizada = asegurar_version_reporte(self.ficha)
        self.assertIsNotNone(version_actualizada)
        self.assertEqual(version_actualizada.id, version_sintetica.id)
        self.assertEqual(version_actualizada.nombre_archivo, 'Reporte_de_Juicios_Evaluativos_37.xlsx')
        self.assertNotEqual(version_actualizada.hash_sha256, 'hash_fake')
        self.assertGreater(version_actualizada.tamano_bytes, 100)

        # 4. Al solicitar la descarga, debe descargarse el archivo original auténtico con su nombre original
        resp = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/planeacion/archivos/{version_actualizada.id}/descargar'
        )
        self.assertEqual(resp.status_code, 200)
        disp = resp.headers.get('Content-Disposition', '')
        self.assertIn('Reporte_de_Juicios_Evaluativos_37.xlsx', disp)
        self.assertNotIn('v1_Reporte_de_Juicios_Evaluativos_37.xlsx', disp)
        resp.close()


if __name__ == '__main__':
    unittest.main()
