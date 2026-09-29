"""Comprueba la topología y el carácter no destructivo del merge Alembic."""

import importlib.util
import os
import unittest

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text


RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REVISION_MERGE = 'e025798e7b92'
REVISION_HEAD = 'b7f2c1d9a640'
REVISION_TRABAJOS_GRUPALES = 'b7f2c1d9a640'
REVISION_INSIGNIAS_GRUPO = 'f016a2b9c421'
RAMA_GRUPOS = 'dfe8ae6bc6d3'
RAMA_RECUPERACION = 'n37passwordreset'


def _script_directory():
    config = Config()
    config.set_main_option(
        'script_location', os.path.join(RAIZ, 'migrations').replace('\\', '/')
    )
    return ScriptDirectory.from_config(config)


class MigrationHeadsTestCase(unittest.TestCase):
    def test_todas_las_ramas_terminan_en_un_solo_head(self):
        scripts = _script_directory()

        self.assertEqual(scripts.get_heads(), [REVISION_HEAD])
        self.assertEqual(
            set(scripts.get_revision(REVISION_MERGE).down_revision),
            {RAMA_GRUPOS, RAMA_RECUPERACION},
        )
        self.assertEqual(
            scripts.get_revision(REVISION_INSIGNIAS_GRUPO).down_revision,
            REVISION_MERGE,
        )
        self.assertEqual(
            scripts.get_revision(REVISION_HEAD).down_revision,
            REVISION_INSIGNIAS_GRUPO,
        )

    def test_merge_no_modifica_ni_el_esquema_ni_los_datos_existentes(self):
        ruta = os.path.join(
            RAIZ,
            'migrations',
            'versions',
            f'{REVISION_MERGE}_unificar_ramas_de_migracion.py',
        )
        spec = importlib.util.spec_from_file_location('revision_merge', ruta)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)

        motor = create_engine('sqlite:///:memory:')
        conexion = motor.connect()
        try:
            conexion.execute(text(
                'CREATE TABLE registro_existente (id INTEGER PRIMARY KEY, valor TEXT)'
            ))
            conexion.execute(
                text('INSERT INTO registro_existente (id, valor) VALUES (1, :valor)'),
                {'valor': 'dato que debe conservarse'},
            )
            conexion.commit()
            esquema_antes = conexion.execute(text(
                "SELECT sql FROM sqlite_master WHERE type = 'table' "
                "AND name = 'registro_existente'"
            )).fetchone()

            contexto = MigrationContext.configure(conexion)
            with Operations.context(contexto):
                revision.upgrade()
                revision.downgrade()

            esquema_despues = conexion.execute(text(
                "SELECT sql FROM sqlite_master WHERE type = 'table' "
                "AND name = 'registro_existente'"
            )).fetchone()
            datos = conexion.execute(text(
                'SELECT id, valor FROM registro_existente'
            )).fetchall()

            self.assertEqual(esquema_despues, esquema_antes)
            self.assertEqual(datos, [(1, 'dato que debe conservarse')])
        finally:
            conexion.close()
            motor.dispose()


if __name__ == '__main__':
    unittest.main()
