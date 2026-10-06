"""Ejecuta las regresiones de aseo con fechas cercanas a festivos y fines de semana."""

import unittest
from contextlib import ExitStack
from datetime import date
from unittest.mock import patch

import pytest

from app.services import aseo as servicio_aseo
from tests import test_aseo as pruebas_aseo
from tests import test_aseo_equidad as pruebas_equidad


@pytest.mark.parametrize('hoy', [
    date(2026, 4, 1),
    date(2026, 5, 1),
    date(2026, 7, 17),
    date(2026, 10, 6),
    date(2026, 10, 7),
    date(2026, 12, 24),
    date(2027, 1, 1),
], ids=str)
@pytest.mark.parametrize('nombre_prueba', [
    'test_diversidad_parejas_evita_repetir_mismo_companero',
    'test_proteger_fechas_pasadas_al_recalcular_mes',
])
def test_regresiones_de_aseo_con_fecha_controlada(hoy, nombre_prueba):
    # Solo se controla el reloj. Los casos conservan sus aserciones y su base de datos real en memoria.
    with ExitStack() as contexto:
        for modulo in (pruebas_aseo, pruebas_equidad, servicio_aseo):
            reloj = contexto.enter_context(patch.object(modulo, 'date', wraps=date))
            reloj.today.return_value = hoy

        caso = pruebas_aseo.TurnosAseoTestCase(nombre_prueba)
        resultado = unittest.TestResult()
        caso.run(resultado)

    assert resultado.testsRun == 1
    assert not resultado.skipped
    assert resultado.wasSuccessful(), '\n'.join(
        detalle for _, detalle in resultado.failures + resultado.errors
    )
