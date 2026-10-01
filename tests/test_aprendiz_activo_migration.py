import importlib.util
import os
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_MIGRACION = os.path.join(
    RAIZ, 'migrations', 'versions', 'c8e3f2b1a950_agregar_campo_activo_a_aprendices.py'
)


def cargar_migracion():
    spec = importlib.util.spec_from_file_location('aprendiz_activo', RUTA_MIGRACION)
    migracion = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migracion)
    return migracion


class AprendizActivoMigrationTestCase(unittest.TestCase):
    def setUp(self):
        self.motor = create_engine('sqlite:///:memory:')
        self.conexion = self.motor.connect()
        self.conexion.execute(text(
            'CREATE TABLE aprendices ('
            'id INTEGER PRIMARY KEY, '
            'documento VARCHAR(20) NOT NULL, '
            'nombre VARCHAR(100) NOT NULL, '
            'apellidos VARCHAR(150) NOT NULL, '
            "estado VARCHAR(20) DEFAULT 'EN_FORMACION'"
            ')'
        ))
        self.conexion.execute(text(
            "INSERT INTO aprendices (id, documento, nombre, apellidos, estado) "
            "VALUES (1, '1001', 'Juan', 'Perez', 'EN_FORMACION')"
        ))
        self.conexion.commit()
        self.migracion = cargar_migracion()

    def tearDown(self):
        self.conexion.close()
        self.motor.dispose()

    def aplicar(self, funcion):
        contexto = MigrationContext.configure(self.conexion)
        with Operations.context(contexto):
            funcion()
        self.conexion.commit()

    def test_upgrade_agrega_campo_activo_con_default_true(self):
        self.aplicar(self.migracion.upgrade)

        columnas = {col['name']: col for col in inspect(self.conexion).get_columns('aprendices')}
        self.assertIn('activo', columnas)
        self.assertFalse(columnas['activo']['nullable'])

        fila = self.conexion.execute(text('SELECT id, activo FROM aprendices WHERE id = 1')).fetchone()
        self.assertEqual(fila[0], 1)
        self.assertTrue(bool(fila[1]))

    def test_downgrade_remueve_campo_activo(self):
        self.aplicar(self.migracion.upgrade)
        self.aplicar(self.migracion.downgrade)

        columnas = {col['name']: col for col in inspect(self.conexion).get_columns('aprendices')}
        self.assertNotIn('activo', columnas)


if __name__ == '__main__':
    unittest.main()
