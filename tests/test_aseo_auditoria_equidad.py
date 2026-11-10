"""Auditoría de equidad del aseo: créditos, cargas y suplencias.

Cada prueba fija un defecto encontrado en la revisión del algoritmo.
"""

import random
import secrets
from datetime import date, timedelta

import pytest

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor, TurnoAseo
from app.services.aseo import (
    _reemplazar_ausentes_del_dia,
    marcar_no_cumplido,
    recalcular_contadores,
)
from app.services.aseo_cola import razon_eleccion
from app.services.aseo_motor_puro import calcular_turnos_token_bucket


@pytest.fixture
def grupo():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
        'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False,
    })
    with app.app_context():
        db.create_all()
        instructor = Instructor(nombre='Instructor', correo='auditoria-aseo@example.com')
        instructor.set_password(secrets.token_urlsafe(24))
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='AUD-ASEO', nombre_programa='Programa', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.flush()
        aprendices = [
            Aprendiz(
                ficha_id=ficha.id, documento=f'AUD-{i}', nombre=f'Aprendiz {i}',
                apellidos='Prueba', estado='EN_FORMACION',
            )
            for i in range(4)
        ]
        db.session.add_all(aprendices)
        db.session.commit()
        yield ficha, aprendices
        db.session.remove()
        db.drop_all()


def _turno(ficha, a1, a2, fecha, estado='programado'):
    turno = TurnoAseo(
        ficha_id=ficha.id, fecha=fecha, aprendiz_1_id=a1.id if a1 else None,
        aprendiz_2_id=a2.id if a2 else None, estado=estado, generado_por='sistema',
    )
    db.session.add(turno)
    db.session.flush()
    return turno


def test_no_cumplido_parcial_acredita_a_quien_si_cumplio(grupo):
    ficha, ap = grupo
    turno = _turno(ficha, ap[0], ap[1], date.today() - timedelta(days=2))
    marcar_no_cumplido(turno, aprendiz_1_no_cumplio=True, aprendiz_2_no_cumplio=False)
    contadores = recalcular_contadores(ficha.id)
    assert contadores[ap[1].id].veces_aseo == 1
    assert contadores[ap[0].id].veces_aseo == 0


def test_no_cumplido_total_no_acredita_a_nadie(grupo):
    ficha, ap = grupo
    turno = _turno(ficha, ap[0], ap[1], date.today() - timedelta(days=2))
    marcar_no_cumplido(turno)
    contadores = recalcular_contadores(ficha.id)
    assert contadores[ap[0].id].veces_aseo == 0
    assert contadores[ap[1].id].veces_aseo == 0


def test_fijo_manual_no_cumplido_no_suma_carga():
    d = date(2026, 3, 2)
    resultado = calcular_turnos_token_bucket(
        aprendiz_ids=[1, 2, 3, 4],
        sesiones_fechas=[d, d + timedelta(days=7)],
        turnos_fijos={d: {
            'aprendiz_1_id': 1, 'aprendiz_2_id': 2,
            'estado': 'no_cumplido', 'es_manual': True,
        }},
        rng=random.Random(1),
    )
    assert resultado['cargas_finales'][1] == 0
    assert resultado['cargas_finales'][2] == 0
    libre = resultado['asignaciones'][1]
    assert {libre['aprendiz_1_id'], libre['aprendiz_2_id']} == {3, 4}


def test_fijo_manual_programado_si_suma_carga():
    d = date(2026, 3, 2)
    resultado = calcular_turnos_token_bucket(
        aprendiz_ids=[1, 2, 3, 4],
        sesiones_fechas=[d],
        turnos_fijos={d: {
            'aprendiz_1_id': 1, 'aprendiz_2_id': 2,
            'estado': 'programado', 'es_manual': True,
        }},
        rng=random.Random(1),
    )
    assert resultado['cargas_finales'][1] == 1


@pytest.mark.parametrize('semilla', range(50))
def test_invariante_carga_minima_respetando_descanso(semilla):
    rng = random.Random(semilla)
    ids = list(range(1, rng.randint(3, 12) + 1))
    cargas = {a: rng.randint(0, 3) for a in ids}
    inicio = date(2026, 2, 2)
    fechas = [inicio + timedelta(days=i) for i in range(rng.randint(5, 25))]
    resultado = calcular_turnos_token_bucket(
        aprendiz_ids=ids, sesiones_fechas=fechas,
        cargas_iniciales=dict(cargas), veces_cumplidas_iniciales=dict(cargas), rng=rng,
    )
    previa = set()
    for asig in resultado['asignaciones']:
        pareja = {asig['aprendiz_1_id'], asig['aprendiz_2_id']}
        assert len(pareja) == 2
        base = [a for a in ids if a not in previa] or ids
        minimo_base = min(cargas[a] for a in base)
        # El primer cupo siempre va a la menor carga entre quienes descansaron.
        primero = asig['aprendiz_1_id']
        assert primero in base and cargas[primero] == minimo_base
        if len(base) >= 2:
            assert pareja <= set(base)
            resto = [a for a in base if a != primero]
            assert cargas[asig['aprendiz_2_id']] == min(cargas[a] for a in resto)
        for a in pareja:
            cargas[a] += 1
        previa = pareja


@pytest.mark.parametrize('n', [4, 5, 6, 7, 10])
def test_brecha_de_carga_no_supera_uno_sin_ausencias(n):
    ids = list(range(1, n + 1))
    fechas = [date(2026, 2, 2) + timedelta(days=i) for i in range(3 * n)]
    resultado = calcular_turnos_token_bucket(ids, fechas, rng=random.Random(n))
    cargas = resultado['cargas_finales']
    assert max(cargas.values()) - min(cargas.values()) <= 1


def test_suplente_evita_a_quien_hizo_aseo_la_sesion_anterior(grupo):
    ficha, ap = grupo
    hoy = date.today()
    # ap[3] hizo aseo en la sesión anterior; ap[2] tiene la misma carga, pero más adelante.
    _turno(ficha, ap[3], ap[1], hoy - timedelta(days=1))
    _turno(ficha, ap[2], ap[1], hoy + timedelta(days=10))
    turno = _turno(ficha, ap[0], ap[1], hoy)
    recalcular_contadores(ficha.id)
    _reemplazar_ausentes_del_dia(turno, {ap[0].id, ap[2].id, ap[3].id})
    assert turno.aprendiz_2_id == ap[2].id


def test_razon_explica_descanso_obligatorio_y_carga():
    contador = type('C', (), {'veces_aseo': 2, 'ultima_vez_aseo': None})()
    texto = razon_eleccion(contador, 1, 2.0, False)
    assert 'carga era de 3' in texto
    assert 'no se repite en sesiones seguidas' in texto
    assert 'menor carga' in texto
