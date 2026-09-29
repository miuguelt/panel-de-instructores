import importlib.util
import os
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_MIGRACION = os.path.join(
    RAIZ, 'migrations', 'versions', 'b7f2c1d9a640_trabajos_y_chat_grupales.py'
)


def cargar_migracion():
    spec = importlib.util.spec_from_file_location('trabajos_chat_grupales', RUTA_MIGRACION)
    migracion = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migracion)
    return migracion


class GruposTrabajoMigrationTestCase(unittest.TestCase):
    def setUp(self):
        self.motor = create_engine('sqlite:///:memory:')
        self.conexion = self.motor.connect()
        self.conexion.execute(text('CREATE TABLE grupos (id INTEGER PRIMARY KEY)'))
        self.conexion.execute(text('CREATE TABLE aprendices (id INTEGER PRIMARY KEY)'))
        self.conexion.execute(text(
            'CREATE TABLE tareas (id INTEGER PRIMARY KEY, titulo VARCHAR(200) NOT NULL)'
        ))
        self.conexion.execute(text(
            'CREATE TABLE entregas (id INTEGER PRIMARY KEY, tarea_id INTEGER NOT NULL, '
            'aprendiz_id INTEGER NOT NULL, '
            'CONSTRAINT uq_entrega_tarea_aprendiz UNIQUE (tarea_id, aprendiz_id))'
        ))
        self.conexion.execute(text("INSERT INTO tareas (id, titulo) VALUES (1, 'Trabajo previo')"))
        self.conexion.execute(text('INSERT INTO aprendices (id) VALUES (2)'))
        self.conexion.execute(text('INSERT INTO aprendices (id) VALUES (6)'))
        self.conexion.execute(text('INSERT INTO entregas (id, tarea_id, aprendiz_id) VALUES (3, 1, 2)'))
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

    def test_upgrade_conserva_entregas_y_crea_esquema_grupal(self):
        self.aplicar(self.migracion.upgrade)

        tareas = {col['name']: col for col in inspect(self.conexion).get_columns('tareas')}
        entregas = {col['name']: col for col in inspect(self.conexion).get_columns('entregas')}
        tablas = set(inspect(self.conexion).get_table_names())
        self.assertFalse(tareas['es_grupal']['nullable'])
        self.assertIn('grupo_id', entregas)
        self.assertTrue(entregas['grupo_id']['nullable'])
        self.assertTrue({'tarea_grupo', 'grupo_mensajes'}.issubset(tablas))
        self.assertEqual(
            self.conexion.execute(text(
                'SELECT tarea_id, aprendiz_id FROM entregas WHERE id = 3'
            )).one(),
            (1, 2),
        )

        self.conexion.execute(text('INSERT INTO grupos (id) VALUES (4)'))
        self.conexion.execute(text(
            'INSERT INTO tarea_grupo (tarea_id, grupo_id) VALUES (1, 4)'
        ))
        self.conexion.execute(text(
            'INSERT INTO entregas (id, tarea_id, aprendiz_id, grupo_id) VALUES (5, 1, 6, 4)'
        ))
        self.conexion.commit()
        self.assertEqual(
            self.conexion.execute(text(
                'SELECT grupo_id FROM entregas WHERE id = 5'
            )).scalar_one(),
            4,
        )

    def test_downgrade_sin_datos_grupales_revierte_esquema_y_conserva_datos(self):
        self.aplicar(self.migracion.upgrade)
        self.aplicar(self.migracion.downgrade)

        self.assertNotIn('es_grupal', {c['name'] for c in inspect(self.conexion).get_columns('tareas')})
        self.assertNotIn('grupo_id', {c['name'] for c in inspect(self.conexion).get_columns('entregas')})
        self.assertNotIn('grupo_mensajes', inspect(self.conexion).get_table_names())
        self.assertEqual(
            self.conexion.execute(text('SELECT titulo FROM tareas WHERE id = 1')).scalar_one(),
            'Trabajo previo',
        )

    def test_downgrade_se_bloquea_si_perderia_asignaciones_grupales(self):
        self.aplicar(self.migracion.upgrade)
        self.conexion.execute(text('INSERT INTO grupos (id) VALUES (4)'))
        self.conexion.execute(text('INSERT INTO tarea_grupo (tarea_id, grupo_id) VALUES (1, 4)'))
        self.conexion.execute(text('UPDATE tareas SET es_grupal = 1 WHERE id = 1'))
        self.conexion.commit()

        with self.assertRaisesRegex(RuntimeError, 'trabajos o mensajes grupales'):
            self.aplicar(self.migracion.downgrade)


if __name__ == '__main__':
    unittest.main()
