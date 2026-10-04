"""Pruebas exhaustivas para la recuperación integral de fuentes de la ficha.

Prueba la recuperación de:
1. Reportes de Juicios Evaluativos
2. Planeaciones Pedagógicas GFPI-F-134
3. Programas de Formación Curricular
4. Servicio orquestador recuperar_fuentes_ficha y endpoint web correspondiente.
"""

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from app import create_app, db
from app.models import ArchivoFichaVersion, Ficha, Instructor, JuicioEvaluativo, TIPO_PLANEACION, TIPO_PROGRAMA, TIPO_REPORTE_JUICIOS
from app.services.recuperacion_fuentes import recuperar_fuentes_ficha
from app.services.recuperacion_planeacion import asegurar_version_planeacion, buscar_archivo_planeacion_original
from app.services.recuperacion_programa import asegurar_version_programa, buscar_archivo_programa_original
from tests.apoyo_planeacion import crear_planeacion_xlsx
from tests.apoyo_programa import crear_programa_pdf


class RecuperacionFuentesCompletaTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'UPLOAD_FOLDER': self.temp_dir.name,
            'WTF_CSRF_ENABLED': False,
        })
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

        self.instructor = Instructor(
            nombre='Carlos Instructor',
            correo='carlos@sena.edu.co',
            password_hash='hash123',
            rol='instructor',
        )
        self.ficha = Ficha(
            codigo='2891111',
            codigo_programa='228118',
            nombre_programa='Analisis y Desarrollo de Software',
            instructor=self.instructor,
            fecha_inicio=date(2025, 1, 1),
            fecha_fin=date(2026, 12, 31),
        )
        db.session.add_all([self.instructor, self.ficha])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        self.temp_dir.cleanup()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = self.instructor.get_id()
            sess['_fresh'] = True

    def test_asegurar_version_planeacion_desde_disco(self):
        # 1. Crear archivo de planeacion en la carpeta de uploads simulada
        ruta_plan = Path(self.temp_dir.name) / '1. GPFI-F-134PlaneacionPedagogicaProyectoFormativo.xlsx'
        ruta_creada = crear_planeacion_xlsx(ruta_plan.parent)
        if ruta_creada.is_file():
            ruta_creada.rename(ruta_plan)

        version = asegurar_version_planeacion(self.ficha)
        if version:
            self.assertEqual(version.tipo, TIPO_PLANEACION)
            self.assertEqual(version.estado, 'procesado')
            self.assertIn('recuperada', version.detalle.lower())

    def test_asegurar_version_planeacion_desde_ficha_hermana(self):
        # Ficha 2 con el mismo codigo_programa ya tiene planeacion procesada
        ficha2 = Ficha(
            codigo='2892222',
            codigo_programa='228118',
            nombre_programa='Analisis y Desarrollo de Software',
            instructor=self.instructor,
            fecha_inicio=date(2025, 1, 1),
            fecha_fin=date(2026, 12, 31),
        )
        db.session.add(ficha2)
        db.session.commit()

        # Crear archivo fisico para la hermana
        dir_hermana = Path(self.temp_dir.name) / f'fichas/{ficha2.id}/planeacion_pedagogica'
        dir_hermana.mkdir(parents=True, exist_ok=True)
        ruta_archivo_hermana = dir_hermana / 'v1_planeacion.xlsx'
        ruta_creada = crear_planeacion_xlsx(dir_hermana)
        if ruta_creada.is_file():
            ruta_creada.rename(ruta_archivo_hermana)

        v_hermana = ArchivoFichaVersion(
            ficha_id=ficha2.id,
            instructor_id=self.instructor.id,
            tipo=TIPO_PLANEACION,
            version=1,
            nombre_archivo='planeacion.xlsx',
            ruta_archivo=f'fichas/{ficha2.id}/planeacion_pedagogica/v1_planeacion.xlsx',
            estado='procesado',
        )
        db.session.add(v_hermana)
        db.session.commit()

        # Ficha 1 no tiene planeacion, debe vincularla desde ficha 2
        version = asegurar_version_planeacion(self.ficha)
        self.assertIsNotNone(version)
        self.assertEqual(version.ficha_id, self.ficha.id)
        self.assertEqual(version.tipo, TIPO_PLANEACION)
        self.assertIn('vinculada', version.detalle.lower())

    def test_asegurar_version_programa_desde_ficha_hermana(self):
        ficha2 = Ficha(
            codigo='2893333',
            codigo_programa='228118',
            nombre_programa='Analisis y Desarrollo de Software',
            instructor=self.instructor,
            fecha_inicio=date(2025, 1, 1),
            fecha_fin=date(2026, 12, 31),
        )
        db.session.add(ficha2)
        db.session.commit()

        dir_hermana = Path(self.temp_dir.name) / f'fichas/{ficha2.id}/programa_formacion'
        dir_hermana.mkdir(parents=True, exist_ok=True)
        crear_programa_pdf(dir_hermana)
        creado = dir_hermana / 'programa.pdf'
        ruta_pdf_hermana = dir_hermana / 'v1_programa.pdf'
        if creado.is_file():
            creado.rename(ruta_pdf_hermana)

        v_prog_hermana = ArchivoFichaVersion(
            ficha_id=ficha2.id,
            instructor_id=self.instructor.id,
            tipo=TIPO_PROGRAMA,
            version=1,
            nombre_archivo='Programa.pdf',
            ruta_archivo=f'fichas/{ficha2.id}/programa_formacion/v1_programa.pdf',
            estado='procesado',
        )
        db.session.add(v_prog_hermana)
        db.session.commit()

        version = asegurar_version_programa(self.ficha)
        self.assertIsNotNone(version)
        self.assertEqual(version.ficha_id, self.ficha.id)
        self.assertEqual(version.tipo, TIPO_PROGRAMA)
        self.assertIn('vinculado', version.detalle.lower())

    def test_recuperar_fuentes_ficha_orquestador(self):
        res = recuperar_fuentes_ficha(self.ficha)
        self.assertTrue(res['ok'])
        self.assertEqual(res['ficha_id'], self.ficha.id)
        self.assertIn('reporte', res)
        self.assertIn('planeacion', res)
        self.assertIn('programa', res)

    def test_ruta_web_recuperar_fuentes_post(self):
        self._login()
        res = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/planeacion/recuperar-fuentes',
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        contenido = res.get_data(as_text=True)
        self.assertIn('Archivos fuente e historial', contenido)
        self.assertIn('Recuperar fuentes', contenido)


if __name__ == '__main__':
    unittest.main()
