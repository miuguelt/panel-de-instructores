"""Pruebas unitarias para seed_admin.py utilizado en el despliegue."""

import os
import unittest
from unittest.mock import patch

from app import create_app, db
from app.models.instructor import Instructor
from seed_admin import seed_admin


class SeedAdminTestCase(unittest.TestCase):
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

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_seed_admin_sin_password_omite_creacion_sin_fallar(self):
        with patch.dict(os.environ, {'ADSO_ADMIN_PASSWORD': '', 'ADSO_ADMIN_EMAIL': 'nuevo@sena.edu.co'}):
            codigo = seed_admin()
            self.assertEqual(codigo, 0)
            self.assertIsNone(Instructor.query.filter_by(correo='nuevo@sena.edu.co').first())

    def test_seed_admin_password_corta_retorna_error(self):
        with patch.dict(os.environ, {'ADSO_ADMIN_PASSWORD': 'corta', 'ADSO_ADMIN_EMAIL': 'admin@sena.edu.co'}):
            codigo = seed_admin()
            self.assertEqual(codigo, 1)
            self.assertIsNone(Instructor.query.filter_by(correo='admin@sena.edu.co').first())

    def test_seed_admin_crea_usuario_admin_exitosamente(self):
        with patch.dict(os.environ, {
            'ADSO_ADMIN_EMAIL': 'superadmin@sena.edu.co',
            'ADSO_ADMIN_PASSWORD': 'password_segura_123',
            'ADSO_ADMIN_NOMBRE': 'Super Administrador',
        }):
            codigo = seed_admin()
            self.assertEqual(codigo, 0)

            admin = Instructor.query.filter_by(correo='superadmin@sena.edu.co').first()
            self.assertIsNotNone(admin)
            self.assertEqual(admin.nombre, 'Super Administrador')
            self.assertEqual(admin.rol, 'admin')
            self.assertTrue(admin.check_password('password_segura_123'))

    def test_seed_admin_existente_no_duplica_ni_falla(self):
        admin_existente = Instructor(
            nombre='Admin Existente',
            correo='admin_existente@sena.edu.co',
            rol='admin',
        )
        admin_existente.set_password('clave_existente_123')
        db.session.add(admin_existente)
        db.session.commit()

        with patch.dict(os.environ, {
            'ADSO_ADMIN_EMAIL': 'admin_existente@sena.edu.co',
            'ADSO_ADMIN_PASSWORD': 'otra_password_diferente',
        }):
            codigo = seed_admin()
            self.assertEqual(codigo, 0)
            # Conserva contraseña original
            admin_recuperado = Instructor.query.filter_by(correo='admin_existente@sena.edu.co').one()
            self.assertTrue(admin_recuperado.check_password('clave_existente_123'))


if __name__ == '__main__':
    unittest.main()
