"""La tabla de personalización se crea y revierte sin cambiar datos académicos."""

import importlib.util
from pathlib import Path
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


class PersonalizacionMigrationTestCase(unittest.TestCase):
    def test_migracion_reversible_fk_y_datos_academicos(self):
        ruta = Path(__file__).resolve().parents[1] / 'migrations/versions/q40personalizacionaprendiz_persistente.py'
        spec = importlib.util.spec_from_file_location('personalizacion_migration', ruta)
        migracion = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migracion)
        self.assertEqual(migracion.down_revision, 'p39portafolioaprendiz')
        with create_engine('sqlite:///:memory:').connect() as conexion:
            conexion.execute(text('PRAGMA foreign_keys=ON'))
            conexion.execute(text('CREATE TABLE aprendices (id INTEGER PRIMARY KEY, nombre TEXT)'))
            conexion.execute(text("INSERT INTO aprendices VALUES (1, 'Ana')"))
            conexion.commit()
            with Operations.context(MigrationContext.configure(conexion)):
                migracion.upgrade()
            self.assertIn('personalizaciones_aprendiz', inspect(conexion).get_table_names())
            columnas = {columna['name'] for columna in inspect(conexion).get_columns('personalizaciones_aprendiz')}
            self.assertEqual(columnas, {'aprendiz_id', 'preferencias', 'foto', 'revision'})
            conexion.execute(text("INSERT INTO personalizaciones_aprendiz VALUES (1, '{}', X'FFD8', 1)"))
            with self.assertRaises(IntegrityError):
                conexion.execute(text("INSERT INTO personalizaciones_aprendiz VALUES (1, '{}', NULL, 2)"))
            with self.assertRaises(IntegrityError):
                conexion.execute(text("INSERT INTO personalizaciones_aprendiz VALUES (2, '{}', NULL, 1)"))
            with self.assertRaises(IntegrityError):
                conexion.execute(text('UPDATE personalizaciones_aprendiz SET revision=0'))
            conexion.execute(text('DELETE FROM aprendices WHERE id=1'))
            self.assertEqual(conexion.execute(text('SELECT count(*) FROM personalizaciones_aprendiz')).scalar_one(), 0)
            conexion.execute(text("INSERT INTO aprendices VALUES (1, 'Ana')"))
            with Operations.context(MigrationContext.configure(conexion)):
                migracion.downgrade()
            self.assertNotIn('personalizaciones_aprendiz', inspect(conexion).get_table_names())
            self.assertEqual(conexion.execute(text('SELECT nombre FROM aprendices')).scalar_one(), 'Ana')
