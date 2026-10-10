"""Pruebas para el servicio de precalentamiento (warmup) de fichas."""

from datetime import date
import unittest
from unittest.mock import patch

from app import create_app, db
from app.models import Ficha, Instructor


class WarmupTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Instructor Warmup',
            correo='warmup@sena.edu.co',
            rol='instructor',
        )
        self.instructor.set_password('clave123')
        db.session.add(self.instructor)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_precargar_todas_las_fichas_vacio(self):
        from app.services.warmup import precargar_todas_las_fichas
        resumen = precargar_todas_las_fichas(self.app)
        self.assertEqual(resumen, {'total': 0, 'exitosas': 0, 'fallidas': 0})

    def test_precargar_todas_las_fichas_con_datos(self):
        from app.services.warmup import precargar_todas_las_fichas

        f1 = Ficha(
            id=101, codigo='101', nombre_programa='Prog 1',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2025, 1, 1), fecha_fin=date(2025, 12, 31),
        )
        f2 = Ficha(
            id=102, codigo='102', nombre_programa='Prog 2',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2025, 1, 1), fecha_fin=date(2025, 12, 31),
        )
        db.session.add_all([f1, f2])
        db.session.commit()

        resumen = precargar_todas_las_fichas(self.app, hoy=date(2025, 6, 1))
        self.assertEqual(resumen['total'], 2)
        self.assertEqual(resumen['exitosas'], 2)
        self.assertEqual(resumen['fallidas'], 0)

    def test_precargar_todas_las_fichas_maneja_errores_aislados(self):
        from app.services.warmup import precargar_todas_las_fichas

        f1 = Ficha(
            id=103, codigo='103', nombre_programa='Prog 3',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2025, 1, 1), fecha_fin=date(2025, 12, 31),
        )
        db.session.add(f1)
        db.session.commit()

        with patch('app.services.warmup.precargar_resultados_ficha', side_effect=RuntimeError('Fallo simulado')):
            resumen = precargar_todas_las_fichas(self.app, hoy=date(2025, 6, 1))
            self.assertEqual(resumen['total'], 1)
            self.assertEqual(resumen['exitosas'], 0)
            self.assertEqual(resumen['fallidas'], 1)
