"""Pruebas unitarias para el servicio de recuperación de reportes originales."""

import unittest
from datetime import date
from tempfile import TemporaryDirectory

from app import create_app, db
from app.models import ArchivoFichaVersion, Ficha, Instructor, JuicioEvaluativo
from app.services.recuperacion_reportes import (
    asegurar_version_reporte,
    buscar_archivo_reporte_original,
)


class RecuperacionReportesTestCase(unittest.TestCase):
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

        self.instructor = Instructor(
            nombre='Carlos Instructor',
            correo='carlos@sena.edu.co',
            password_hash='hash123',
            rol='instructor',
        )
        self.ficha = Ficha(
            codigo='2899999',
            nombre_programa='ADSO',
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

    def test_buscar_archivo_reporte_original_ficha_sin_codigo_retorna_none(self):
        ficha_sin_codigo = Ficha(codigo=None, nombre_programa='ADSO')
        self.assertIsNone(buscar_archivo_reporte_original(ficha_sin_codigo))

    def test_asegurar_version_reporte_ficha_inexistente_retorna_none(self):
        self.assertIsNone(asegurar_version_reporte(999999))

    def test_asegurar_version_reporte_ficha_sin_juicios_retorna_none(self):
        self.assertIsNone(asegurar_version_reporte(self.ficha))

    def test_asegurar_version_reporte_crea_version_sintetica_si_hay_juicios(self):
        from app.models.aprendiz import Aprendiz
        aprendiz = Aprendiz(
            ficha_id=self.ficha.id,
            nombre='Juan',
            apellidos='Perez',
            tipo_documento='CC',
            documento='12345678',
            estado='EN_FORMACION',
        )
        db.session.add(aprendiz)
        db.session.flush()

        juicio = JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=aprendiz.id,
            competencia='Algoritmos',
            resultado_aprendizaje='RAP 1',
            juicio='APROBADO',
            huella='h1',
        )
        db.session.add(juicio)
        db.session.commit()

        version = asegurar_version_reporte(self.ficha)
        self.assertIsNotNone(version)
        self.assertEqual(version.ficha_id, self.ficha.id)
        self.assertEqual(version.estado, 'procesado')
        self.assertTrue(version.nombre_archivo.startswith('Reporte_de_Juicios_Evaluativos_'))

        # Si se vuelve a invocar, retorna la misma versión existente sin error
        version2 = asegurar_version_reporte(self.ficha.id)
        self.assertEqual(version2.id, version.id)


if __name__ == '__main__':
    unittest.main()
