from datetime import date
from types import SimpleNamespace

import pytest

from app.services.cronograma import obtener_cronograma


def ficha():
    return SimpleNamespace(fecha_inicio=date(2025, 7, 25), fecha_fin=date(2027, 10, 24),
                           duracion_productiva_meses=6)


def test_el_porcentaje_solo_incluye_induccion_y_etapa_lectiva():
    r = obtener_cronograma(ficha(), date(2026, 9, 10))
    assert r['porcentaje'] == 64.7
    assert r['dias_totales'] == 638
    assert r['fin_lectiva'] == date(2027, 4, 23)
    assert r['inicio_productiva'] == date(2027, 4, 24)
    assert r['meses_productiva'] == 6


@pytest.mark.parametrize('hoy', [date(2027, 4, 23), date(2027, 4, 24), date(2027, 10, 24), date(2028, 1, 1)])
def test_el_cien_por_ciento_se_alcanza_al_terminar_la_lectiva(hoy):
    assert obtener_cronograma(ficha(), hoy)['porcentaje'] == 100


def test_antes_de_induccion_el_avance_es_cero():
    assert obtener_cronograma(ficha(), date(2025, 7, 24))['porcentaje'] == 0


def test_fechas_sin_etapa_lectiva_no_inventan_porcentaje():
    f = ficha()
    f.fecha_inicio = date(2027, 5, 1)
    assert not obtener_cronograma(f)['configurado']
