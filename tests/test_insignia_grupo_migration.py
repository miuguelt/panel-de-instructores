"""Pruebas de la migración que permite otorgar insignias a grupos."""

import importlib.util
import os
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_MIGRACION = os.path.join(
    RAIZ,
    'migrations',
    'versions',
    'f016a2b9c421_insignias_otorgadas_a_grupos.py',
)


def cargar_migracion():
    spec = importlib.util.spec_from_file_location('insignias_grupos', RUTA_MIGRACION)
    migracion = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migracion)
    return migracion


class InsigniasGrupoMigrationTestCase(unittest.TestCase):
    def setUp(self):
        self.motor = create_engine('sqlite:///:memory:')
        self.conexion = self.motor.connect()
        self.conexion.execute(text('CREATE TABLE aprendices (id INTEGER PRIMARY KEY)'))
        self.conexion.execute(text('CREATE TABLE grupos (id INTEGER PRIMARY KEY)'))
        self.conexion.execute(text('CREATE TABLE insignias (id INTEGER PRIMARY KEY)'))
        self.conexion.execute(text('CREATE TABLE instructores (id INTEGER PRIMARY KEY)'))
        self.conexion.execute(text(
            'CREATE TABLE insignias_otorgadas ('
            'id INTEGER PRIMARY KEY, aprendiz_id INTEGER NOT NULL, '
            'insignia_id INTEGER NOT NULL, fecha_obtencion DATETIME NOT NULL, '
            'otorgada_por VARCHAR(30) NOT NULL, instructor_id INTEGER, '
            'notificada BOOLEAN NOT NULL, '
            'CONSTRAINT uq_aprendiz_insignia UNIQUE (aprendiz_id, insignia_id))'
        ))
        self.conexion.execute(text('INSERT INTO aprendices (id) VALUES (1)'))
        self.conexion.execute(text('INSERT INTO insignias (id) VALUES (1), (2)'))
        self.conexion.execute(text(
            "INSERT INTO insignias_otorgadas "
            "(id, aprendiz_id, insignia_id, fecha_obtencion, otorgada_por, notificada) "
            "VALUES (1, 1, 1, CURRENT_TIMESTAMP, 'sistema', 0)"
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

    def test_upgrade_conserva_otorgamientos_y_habilita_otorgamiento_a_grupo(self):
        self.aplicar(self.migracion.upgrade)

        columnas = {columna['name']: columna for columna in inspect(self.conexion).get_columns(
            'insignias_otorgadas'
        )}
        self.assertTrue(columnas['aprendiz_id']['nullable'])
        self.assertTrue(columnas['grupo_id']['nullable'])
        self.assertEqual(
            self.conexion.execute(text(
                'SELECT aprendiz_id, insignia_id FROM insignias_otorgadas WHERE id = 1'
            )).one(),
            (1, 1),
        )
        self.conexion.execute(text('INSERT INTO grupos (id) VALUES (7)'))
        self.conexion.execute(text(
            "INSERT INTO insignias_otorgadas "
            "(id, aprendiz_id, grupo_id, insignia_id, fecha_obtencion, "
            "otorgada_por, notificada) "
            "VALUES (2, NULL, 7, 2, CURRENT_TIMESTAMP, 'instructor', 0)"
        ))
        self.conexion.commit()
        self.assertEqual(self.conexion.execute(text(
            'SELECT grupo_id FROM insignias_otorgadas WHERE id = 2'
        )).scalar_one(), 7)

    def test_upgrade_rechaza_filas_sin_un_solo_propietario(self):
        self.aplicar(self.migracion.upgrade)

        with self.assertRaises(IntegrityError):
            self.conexion.execute(text(
                "INSERT INTO insignias_otorgadas "
                "(id, aprendiz_id, grupo_id, insignia_id, fecha_obtencion, "
                "otorgada_por, notificada) "
                "VALUES (2, 1, 7, 2, CURRENT_TIMESTAMP, 'instructor', 0)"
            ))
        self.conexion.rollback()

    def test_downgrade_se_bloquea_si_perderia_otorgamientos_a_grupos(self):
        self.aplicar(self.migracion.upgrade)
        self.conexion.execute(text('INSERT INTO grupos (id) VALUES (7)'))
        self.conexion.execute(text(
            "INSERT INTO insignias_otorgadas "
            "(id, aprendiz_id, grupo_id, insignia_id, fecha_obtencion, "
            "otorgada_por, notificada) "
            "VALUES (2, NULL, 7, 2, CURRENT_TIMESTAMP, 'instructor', 0)"
        ))
        self.conexion.commit()

        with self.assertRaisesRegex(RuntimeError, 'otorgamientos a grupos'):
            self.aplicar(self.migracion.downgrade)

    def test_downgrade_sin_otorgamientos_de_grupo_conserva_datos_previos(self):
        self.aplicar(self.migracion.upgrade)
        self.aplicar(self.migracion.downgrade)

        columnas = {columna['name']: columna for columna in inspect(self.conexion).get_columns(
            'insignias_otorgadas'
        )}
        self.assertNotIn('grupo_id', columnas)
        self.assertFalse(columnas['aprendiz_id']['nullable'])
        self.assertEqual(
            self.conexion.execute(text(
                'SELECT aprendiz_id, insignia_id FROM insignias_otorgadas WHERE id = 1'
            )).one(),
            (1, 1),
        )


if __name__ == '__main__':
    unittest.main()
