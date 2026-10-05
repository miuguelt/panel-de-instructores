"""Pruebas del orden de asignación con historiales y cargas diferentes."""

import random
import secrets
from collections import Counter, defaultdict
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor, SesionAsistencia, TurnoAseo
from app.services.aseo import _elegir_por_cola_justa, generar_turnos
from app.services.festivos import es_festivo_colombia


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
        instructor = Instructor(nombre='Instructor de prueba', correo='aseo@example.com')
        instructor.set_password(secrets.token_urlsafe(24))
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(
            codigo='ASEO-PRUEBA', nombre_programa='Programa de prueba',
            instructor_id=instructor.id,
        )
        db.session.add(ficha)
        db.session.flush()
        aprendices = [
            Aprendiz(
                ficha_id=ficha.id, documento=f'PRUEBA-{indice}',
                nombre=f'Aprendiz {indice}', apellidos='Prueba', estado='EN_FORMACION',
            )
            for indice in range(6)
        ]
        db.session.add_all(aprendices)
        db.session.commit()
        yield ficha, aprendices
        db.session.remove()
        db.drop_all()


def registrar_turno(ficha, aprendices, fecha, indices, estado='cumplido', **campos):
    turno = TurnoAseo(
        ficha_id=ficha.id, fecha=fecha,
        aprendiz_1_id=aprendices[indices[0]].id,
        aprendiz_2_id=aprendices[indices[1]].id,
        estado=estado, generado_por='sistema', **campos,
    )
    db.session.add(turno)
    return turno


def fechas_futuras(cantidad):
    fechas = []
    fecha = date.today() + timedelta(days=1)
    while len(fechas) < cantidad:
        if not es_festivo_colombia(fecha):
            fechas.append(fecha)
        fecha += timedelta(days=1)
    return fechas


@pytest.mark.parametrize('semilla', [3, 19, 42])
def test_menos_cumplidos_prevalecen_sobre_antiguedad_en_ambos_cupos(grupo, semilla):
    ficha, aprendices = grupo
    hoy = date.today()
    for desplazamiento in (30, 29):
        registrar_turno(ficha, aprendices, hoy - timedelta(days=desplazamiento), (0, 1))
    registrar_turno(ficha, aprendices, hoy - timedelta(days=10), (2, 3))
    registrar_turno(ficha, aprendices, hoy - timedelta(days=9), (4, 5))
    registrar_turno(ficha, aprendices, hoy - timedelta(days=3), (2, 3), 'programado')
    registrar_turno(ficha, aprendices, hoy - timedelta(days=2), (4, 5), 'intercambiado')
    fecha = fechas_futuras(1)[0]
    db.session.add(SesionAsistencia(ficha_id=ficha.id, fecha=fecha))
    db.session.commit()

    resultado = generar_turnos(ficha.id, fecha, fecha, rng=random.Random(semilla))
    db.session.commit()

    assert len(resultado['creados']) == 1
    turno = db.session.get(TurnoAseo, resultado['creados'][0].id)
    menos_cumplidos = {aprendiz.id for aprendiz in aprendices[2:]}
    assert turno.aprendiz_1_id in menos_cumplidos
    assert turno.aprendiz_2_id in menos_cumplidos
    assert turno.aprendiz_1_id != turno.aprendiz_2_id


def test_rotar_companeros_no_adelanta_a_quien_tiene_mas_cumplidos(grupo):
    ficha, aprendices = grupo
    hoy = date.today()
    # Carga 1 para todos: dos aprendices tienen un pendiente y los demás un cumplido.
    registrar_turno(ficha, aprendices, hoy - timedelta(days=3), (0, 1), 'programado')
    registrar_turno(ficha, aprendices, hoy - timedelta(days=20), (2, 3))
    registrar_turno(ficha, aprendices, hoy - timedelta(days=19), (4, 5))
    fecha = fechas_futuras(1)[0]
    db.session.add(SesionAsistencia(ficha_id=ficha.id, fecha=fecha))
    db.session.commit()

    turno = generar_turnos(ficha.id, fecha, fecha, rng=random.Random(5))['creados'][0]

    assert {turno.aprendiz_1_id, turno.aprendiz_2_id} == {
        aprendices[0].id, aprendices[1].id,
    }


def test_calendario_completo_equilibra_cumplidos_y_nuevas_asignaciones(grupo):
    ficha, aprendices = grupo
    hoy = date.today()
    for desplazamiento in (30, 29, 28):
        registrar_turno(ficha, aprendices, hoy - timedelta(days=desplazamiento), (0, 1))
    registrar_turno(ficha, aprendices, hoy - timedelta(days=20), (2, 3))
    fechas = fechas_futuras(15)
    db.session.add_all([
        SesionAsistencia(ficha_id=ficha.id, fecha=fecha) for fecha in fechas
    ])
    db.session.commit()

    resultado = generar_turnos(ficha.id, fechas[0], fechas[-1], rng=random.Random(42))

    cargas = Counter({aprendices[i].id: cantidad for i, cantidad in enumerate((3, 3, 1, 1, 0, 0))})
    assert len(resultado['creados']) == len(fechas)
    for turno in resultado['creados']:
        disponibles = dict(cargas)
        for aprendiz_id in (turno.aprendiz_1_id, turno.aprendiz_2_id):
            minimo = min(disponibles.values())
            assert disponibles.pop(aprendiz_id) == minimo
            cargas[aprendiz_id] += 1
    assert max(cargas.values()) - min(cargas.values()) <= 1


def candidatos_con_historial(cumplidos, pendientes=None, ultimas=None):
    candidatos = [SimpleNamespace(id=indice) for indice in range(1, len(cumplidos) + 1)]
    contadores = {
        candidato.id: SimpleNamespace(
            veces_aseo=cumplidos[indice],
            ultima_vez_aseo=(ultimas or {}).get(candidato.id),
        )
        for indice, candidato in enumerate(candidatos)
    }
    return candidatos, contadores, defaultdict(int, pendientes or {})


def test_cola_compartida_prioriza_cumplidos_antes_de_pareja_y_fecha():
    candidatos, contadores, cargas = candidatos_con_historial(
        [1, 2], {1: 1}, {1: date(2026, 9, 30), 2: date(2026, 7, 1)},
    )
    elegido = _elegir_por_cola_justa(
        candidatos, contadores, cargas, {}, rng=random.Random(42),
        companero_id=9, historial_parejas={(1, 9): 4},
    )
    assert elegido.id == 1


def test_cola_sin_candidatos_y_exclusiones():
    assert _elegir_por_cola_justa([], {}, {}, {}) is None
    candidatos, contadores, cargas = candidatos_con_historial([0, 1])
    assert _elegir_por_cola_justa(
        candidatos, contadores, cargas, {}, excluir_ids={1},
    ).id == 2
    assert _elegir_por_cola_justa(
        candidatos, contadores, cargas, {}, excluir_ids={1, 2},
    ).id == 1


def test_cola_desempata_por_antiguedad_y_sorteo_reproducible():
    candidatos, contadores, cargas = candidatos_con_historial(
        [1, 1, 1], ultimas={1: date(2026, 9, 1), 2: date(2026, 8, 1), 3: date(2026, 9, 1)},
    )
    assert _elegir_por_cola_justa(candidatos, contadores, cargas, {}).id == 2
    for contador in contadores.values():
        contador.ultima_vez_aseo = None
    elegido = _elegir_por_cola_justa(candidatos, contadores, cargas, {}, rng=random.Random(17))
    assert elegido == random.Random(17).choice(candidatos)


def test_evitar_consecutivos_no_desplaza_a_quien_tiene_menor_carga():
    candidatos, contadores, cargas = candidatos_con_historial([0, 2])
    assert _elegir_por_cola_justa(
        candidatos, contadores, cargas, {}, evitar_ids={1},
    ).id == 1


def test_con_carga_igual_prefiere_descansar_a_la_pareja_anterior():
    candidatos, contadores, cargas = candidatos_con_historial([0, 1], {1: 1})
    assert _elegir_por_cola_justa(
        candidatos, contadores, cargas, {}, evitar_ids={1},
    ).id == 2


def test_dos_aprendices_pueden_repetir_sin_quedarse_sin_turno():
    candidatos, contadores, cargas = candidatos_con_historial([0, 0])
    assert _elegir_por_cola_justa(
        candidatos, contadores, cargas, {}, evitar_ids={1, 2},
    ).id in {1, 2}


@pytest.mark.parametrize('cantidad', [2, 3, 4, 8])
def test_rotacion_considera_las_parejas_que_quedan_sin_asignar(cantidad):
    candidatos, contadores, cargas = candidatos_con_historial(
        [0] * cantidad,
        ultimas={indice: date(2026, 8, indice) for indice in range(1, cantidad + 1)},
    )
    historial = {
        (primero, segundo): 1
        for primero in range(1, cantidad)
        for segundo in range(primero + 1, cantidad)
    }
    elegido = _elegir_por_cola_justa(
        candidatos, contadores, cargas, {}, companero_id=9,
        historial_parejas=historial, anticipar_parejas=True,
    )
    assert elegido.id == 1


def test_explicacion_muestra_cumplidos_pendientes_y_prioridad():
    from app.services.aseo_cola import razon_eleccion

    contador = SimpleNamespace(veces_aseo=1, ultima_vez_aseo=date(2026, 8, 12))
    explicacion = razon_eleccion(contador, 2, 1.5, False)
    assert 'carga era de 3' in explicacion
    assert '1 turno(s) cumplido(s) y 2 programado(s)' in explicacion
    assert 'menos turnos cumplidos, antes de rotar compañeros' in explicacion
    assert '12/08/2026' in explicacion
    assert 'Tu compañero' not in explicacion
    assert 'te marcaba como presente' not in explicacion
    contador.veces_aseo = 0
    contador.ultima_vez_aseo = None
    explicacion = razon_eleccion(contador, 0, 1, True, companero_nombre='Aprendiz de prueba')
    assert 'Todavía no has cumplido' in explicacion
    assert '0 turno(s) cumplido(s) y 0 programado(s)' in explicacion
    assert 'Tu compañero es Aprendiz de prueba' in explicacion
    assert '0 turno(s) antes de esta asignación' in explicacion
    assert 'te marcaba como presente' in explicacion


@pytest.mark.parametrize('anticipar', [False, True])
def test_companero_con_menos_repeticiones_resuelve_el_empate(anticipar):
    candidatos, contadores, cargas = candidatos_con_historial([0, 0, 0])
    elegido = _elegir_por_cola_justa(
        candidatos, contadores, cargas, {}, companero_id=9,
        historial_parejas={(1, 9): 2, (2, 9): 1}, anticipar_parejas=anticipar,
    )
    assert elegido.id == 3
