import importlib.util
import os
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


class NotificacionesPushMigrationTestCase(unittest.TestCase):
    def test_migracion_crea_y_retira_el_buzon_y_las_suscripciones(self):
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ruta = os.path.join(raiz, 'migrations', 'versions', 'u45_avisos_push_aprendiz.py')
        spec = importlib.util.spec_from_file_location('u45_avisos_push_aprendiz', ruta)
        migracion = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migracion)
        motor = create_engine('sqlite:///:memory:')
        with motor.begin() as conexion:
            conexion.execute(text('CREATE TABLE aprendices (id INTEGER PRIMARY KEY)'))
            conexion.execute(text('CREATE TABLE fichas (id INTEGER PRIMARY KEY)'))
            conexion.execute(text('CREATE TABLE notificaciones (id INTEGER PRIMARY KEY)'))
            contexto = MigrationContext.configure(conexion)
            with Operations.context(contexto):
                migracion.upgrade()
            inspector = inspect(conexion)
            self.assertIn('aprendiz_push_subscriptions', inspector.get_table_names())
            self.assertIn('aprendiz_push_dispatches', inspector.get_table_names())
            columnas_suscripcion = {
                columna['name']
                for columna in inspector.get_columns('aprendiz_push_subscriptions')
            }
            self.assertTrue({
                'endpoint_hash', 'endpoint_cifrado', 'p256dh_cifrado', 'auth_cifrado',
            }.issubset(columnas_suscripcion))
            self.assertNotIn('suscripcion_id', columnas_suscripcion)
            self.assertIn('suscripcion_id', {
                columna['name']
                for columna in inspector.get_columns('aprendiz_push_dispatches')
            })
            self.assertIn('disponible_en', {
                columna['name']
                for columna in inspector.get_columns('aprendiz_push_dispatches')
            })
            with Operations.context(contexto):
                migracion.downgrade()
            self.assertNotIn('aprendiz_push_subscriptions', inspect(conexion).get_table_names())
            self.assertNotIn('aprendiz_push_dispatches', inspect(conexion).get_table_names())
        motor.dispose()


if __name__ == '__main__':
    unittest.main()
