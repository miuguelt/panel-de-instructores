"""La migración agrega sesiones durables sin alterar registros existentes."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_migracion_y_reversion_conservan_datos_anteriores():
    ruta = Path(__file__).resolve().parents[1] / 'migrations/versions/u44_cargas_reanudables.py'
    especificacion = importlib.util.spec_from_file_location('migracion_cargas', ruta)
    migracion = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(migracion)
    motor = create_engine('sqlite:///:memory:')
    with motor.begin() as conexion:
        conexion.execute(text('CREATE TABLE historico (id INTEGER PRIMARY KEY, valor TEXT)'))
        conexion.execute(text("INSERT INTO historico VALUES (1, 'Información conservada')"))
        with Operations.context(MigrationContext.configure(conexion)):
            migracion.upgrade()
            tablas = inspect(conexion).get_table_names()
            assert {'cargas_archivos', 'cargas_envios', 'historico'} <= set(tablas)
            columnas = {c['name']: c for c in inspect(conexion).get_columns('cargas_archivos')}
            assert {'offset', 'bloque_bytes', 'huellas', 'hash_sha256', 'envio_id'} <= columnas.keys()
            assert columnas['bloque_bytes']['nullable'] is False
            indices = {i['name'] for i in inspect(conexion).get_indexes('cargas_envios')}
            assert 'ix_cargas_envios_estado' in indices
            migracion.downgrade()
        assert inspect(conexion).get_table_names() == ['historico']
        assert conexion.execute(text('SELECT valor FROM historico')).scalar() == 'Información conservada'
    motor.dispose()
