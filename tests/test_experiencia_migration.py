"""Migración reversible de preferencias e hitos sin modificar datos académicos."""

import importlib.util
from pathlib import Path
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


class ExperienciaMigrationTestCase(unittest.TestCase):
    def test_upgrade_downgrade_pk_fk_y_revision(self):
        ruta = Path(__file__).resolve().parents[1] / 'migrations/versions/r41experienciaaprendiz_persistente.py'
        spec = importlib.util.spec_from_file_location('experiencia_migration', ruta)
        migracion = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migracion)
        self.assertEqual(migracion.down_revision, 'q40personalizacionaprendiz')
        with create_engine('sqlite:///:memory:').connect() as conexion:
            conexion.execute(text('PRAGMA foreign_keys=ON'))
            conexion.execute(text('CREATE TABLE aprendices (id INTEGER PRIMARY KEY, nombre TEXT)'))
            conexion.execute(text("INSERT INTO aprendices VALUES (1, 'Ana')"))
            conexion.commit()
            with Operations.context(MigrationContext.configure(conexion)):
                migracion.upgrade()
            columnas = {columna['name'] for columna in inspect(conexion).get_columns('experiencias_aprendiz')}
            self.assertEqual(columnas, {'aprendiz_id', 'preferences', 'revision', 'logros'})
            conexion.execute(text("INSERT INTO experiencias_aprendiz VALUES (1, '{}', 1, '[]')"))
            with self.assertRaises(IntegrityError):
                conexion.execute(text("INSERT INTO experiencias_aprendiz VALUES (1, '{}', 2, '[]')"))
            with self.assertRaises(IntegrityError):
                conexion.execute(text("INSERT INTO experiencias_aprendiz VALUES (2, '{}', 1, '[]')"))
            with self.assertRaises(IntegrityError):
                conexion.execute(text('UPDATE experiencias_aprendiz SET revision=0'))
            conexion.execute(text('DELETE FROM aprendices WHERE id=1'))
            self.assertEqual(conexion.execute(text('SELECT count(*) FROM experiencias_aprendiz')).scalar_one(), 0)
            conexion.execute(text("INSERT INTO aprendices VALUES (1, 'Ana')"))
            with Operations.context(MigrationContext.configure(conexion)):
                migracion.downgrade()
            self.assertNotIn('experiencias_aprendiz', inspect(conexion).get_table_names())
            self.assertEqual(conexion.execute(text('SELECT nombre FROM aprendices')).scalar_one(), 'Ana')
