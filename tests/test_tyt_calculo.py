from datetime import date, datetime, timezone

import pytest

from app.tyt.calculo import calcular_seguimiento


def calcular(juicios=(), aprendices=None, hoy=date(2026, 3, 11), **fechas):
    return calcular_seguimiento(
        aprendices or [{'id': 1, 'nombre': 'Ana'}, {'id': 2, 'nombre': 'Luis'}],
        juicios, fechas.get('inicio', date(2026, 1, 1)),
        fechas.get('fin', date(2026, 4, 10)), hoy,
    )


def rap(aprendiz, numero, juicio):
    return {'aprendiz_id': aprendiz, 'competencia': 'C1',
            'resultado_aprendizaje': f'R{numero}', 'juicio': juicio}


def test_umbral_exacto_y_dias_inclusivos():
    antes = calcular(hoy=date(2026, 3, 10))
    hito = calcular()
    assert antes['tiempo']['porcentaje'] == 69
    assert not antes['tiempo']['alcanzado']
    assert antes['tiempo']['dias_faltantes'] == 1
    assert hito['tiempo']['fecha_hito'] == date(2026, 3, 11)
    assert hito['tiempo']['alcanzado']


def test_no_activar_por_redondeo_ni_zona_del_servidor():
    r = calcular(hoy=datetime(2026, 3, 11, 2, tzinfo=timezone.utc))
    assert not r['tiempo']['alcanzado']


def test_redondeo_visual_no_adelanta_la_alarma():
    from datetime import timedelta
    inicio = date(2000, 1, 1)
    r = calcular(inicio=inicio, fin=inicio + timedelta(days=9999),
                 hoy=inicio + timedelta(days=6998))
    assert r['tiempo']['porcentaje'] == 70
    assert r['tiempo']['dias_faltantes'] == 1
    assert not r['tiempo']['alcanzado']


@pytest.mark.parametrize('hoy,porcentaje', [(date(2025, 12, 1), 0), (date(2027, 1, 1), 100)])
def test_limites_del_calendario(hoy, porcentaje):
    assert calcular(hoy=hoy)['tiempo']['porcentaje'] == porcentaje


def test_promedio_incluye_aprendiz_sin_juicios_y_no_aprobados():
    datos = [rap(1, n, 'APROBADO' if n < 6 else 'AÚN NO APROBADO') for n in range(10)]
    r = calcular(datos)
    assert r['total_resultados'] == 10
    assert r['promedio_aprobados'] == 30
    assert r['promedio_evaluados'] == 50
    ana, luis = r['aprendices']
    assert ana['faltan_aprobar'] == 1
    assert ana['faltan_evaluar'] == 0
    assert luis['faltan_evaluar'] == 7
    assert r['pendientes_evaluacion'] == 1
    assert r['pendientes_aprobacion'] == 2


def test_meta_redondea_hacia_arriba_y_no_confunde_promedio_con_cumplimiento():
    r = calcular([rap(1, n, 'APROBADO') for n in range(3)])
    assert r['meta_resultados'] == 3
    assert r['aprendices'][1]['faltan_aprobar'] == 3


def test_reimportacion_no_duplica_y_usa_estado_mas_reciente():
    r = calcular([rap(1, 1, 'APROBADO'), rap(1, 1, 'POR EVALUAR')])
    assert r['total_resultados'] == 1
    assert r['aprendices'][0]['aprobados'] == 0
    assert r['aprendices'][0]['evaluados'] == 0


@pytest.mark.parametrize('estado,evaluados,aprobados', [
    ('APROBADO', 1, 1), ('A', 1, 1), ('NO APROBADO', 1, 0),
    ('AUN NO APROBADO', 1, 0), ('NA', 1, 0), ('POR EVALUAR', 0, 0),
    ('PENDIENTE', 0, 0), ('', 0, 0), ('DESCONOCIDO', 0, 0),
])
def test_estados_explicitos(estado, evaluados, aprobados):
    a = calcular([rap(1, 1, estado)])['aprendices'][0]
    assert (a['evaluados'], a['aprobados']) == (evaluados, aprobados)


@pytest.mark.parametrize('inicio,fin', [(None, None), (date(2026, 5, 1), date(2026, 1, 1))])
def test_fechas_invalidas_y_reporte_vacio_no_cumplen(inicio, fin):
    r = calcular(inicio=inicio, fin=fin)
    assert r['tiempo']['porcentaje'] is None
    assert r['promedio_aprobados'] is None
    assert not r['aprendices'][0]['cumple_evaluacion']
    assert r['aprendices'][0]['faltan_evaluar'] is None


def test_ignora_juicios_ajenos_y_resultados_sin_identidad():
    r = calcular([rap(99, 1, 'APROBADO'), dict(rap(1, 1, 'APROBADO'), resultado_aprendizaje='')])
    assert r['total_resultados'] == 0
