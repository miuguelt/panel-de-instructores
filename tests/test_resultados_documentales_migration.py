"""Verifica que la migración documental se pueda revertir sin perder datos."""

import importlib.util
import os
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_MIGRACION = os.path.join(
    RAIZ, 'migrations', 'versions', 'o38_resultados_documentales_persistidos.py'
)


def cargar_migracion():
    spec = importlib.util.spec_from_file_location('o38_resultados', RUTA_MIGRACION)
    migracion = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migracion)
    return migracion


class ResultadosDocumentalesMigrationTestCase(unittest.TestCase):
    def test_upgrade_y_downgrade_conservan_datos_anteriores(self):
        motor = create_engine('sqlite:///:memory:')
        conexion = motor.connect()
        try:
            conexion.execute(text('CREATE TABLE fichas (id INTEGER PRIMARY KEY)'))
            conexion.execute(text(
                'CREATE TABLE archivos_ficha_versiones '
                '(id INTEGER PRIMARY KEY, metadata_json TEXT)'
            ))
            conexion.execute(text(
                'CREATE TABLE importaciones_jobs '
                '(id INTEGER PRIMARY KEY, nombre_archivo VARCHAR(255))'
            ))
            conexion.execute(text('INSERT INTO fichas (id) VALUES (1)'))
            conexion.execute(text(
                "INSERT INTO archivos_ficha_versiones (id, metadata_json) "
                "VALUES (1, '{\"codigo\": \"228118\"}')"
            ))
            conexion.execute(text(
                "INSERT INTO importaciones_jobs (id, nombre_archivo) VALUES (1, 'reporte.xls')"
            ))
            conexion.commit()
            contexto = MigrationContext.configure(conexion)
            migracion = cargar_migracion()
            with Operations.context(contexto):
                migracion.upgrade()
            columnas_archivo = {c['name'] for c in inspect(conexion).get_columns('archivos_ficha_versiones')}
            columnas_ficha = {c['name'] for c in inspect(conexion).get_columns('fichas')}
            columnas_job = {c['name'] for c in inspect(conexion).get_columns('importaciones_jobs')}
            self.assertIn('contenido_extraido_json', columnas_archivo)
            self.assertIn('revision_calculos', columnas_ficha)
            self.assertIn('tipo_trabajo', columnas_job)
            self.assertIn('resultados_calculados_ficha', inspect(conexion).get_table_names())

            with Operations.context(MigrationContext.configure(conexion)):
                migracion.downgrade()
            self.assertEqual(
                conexion.execute(text(
                    'SELECT metadata_json FROM archivos_ficha_versiones WHERE id=1'
                )).scalar_one(),
                '{"codigo": "228118"}',
            )
            self.assertNotIn(
                'contenido_extraido_json',
                {c['name'] for c in inspect(conexion).get_columns('archivos_ficha_versiones')},
            )
        finally:
            conexion.close()
            motor.dispose()


if __name__ == '__main__':
    unittest.main()
