"""Verifica la conservación del historial y la equidad al limpiar el calendario."""

import random
from collections import Counter
from datetime import date, datetime, time, timedelta

import pytest

from app import db
from app.models import ContadorAseo, TurnoAseo
from app.services.aseo import generar_turnos
from app.services.festivos import es_festivo_colombia
from tests.test_aseo_equidad import (
    fechas_futuras,
    grupo,
    proximo_fin_de_semana,
    registrar_turno,
)


def datos_persistidos(turno):
    return {columna.name: getattr(turno, columna.name)
            for columna in TurnoAseo.__table__.columns}


@pytest.mark.parametrize('tipo_fecha', ['laborable', 'sabado', 'domingo', 'festivo'])
@pytest.mark.parametrize('marcas', [(True, True), (True, False), (False, True), (None, None)])
def test_cumplidos_conservan_todos_sus_datos_y_cuentan_solo_cumplimientos(grupo, tipo_fecha, marcas):
    ficha, aprendices = grupo
    sabado, domingo = proximo_fin_de_semana()
    fecha = {
        'laborable': fechas_futuras(1)[0],
        'sabado': sabado,
        'domingo': domingo,
        'festivo': date(date.today().year + 1, 1, 1),
    }[tipo_fecha]
    if tipo_fecha == 'festivo':
        assert es_festivo_colombia(fecha)
    turno = registrar_turno(
        ficha, aprendices, fecha, (0, 1),
        completado_1=marcas[0], completado_2=marcas[1],
        completado_en=datetime.combine(fecha, time(10, 15)),
        auditoria_1='Asignación histórica del primer aprendiz.',
        auditoria_2='Asignación histórica del segundo aprendiz.',
        observacion='Aseo registrado antes de recalcular el calendario.',
    )
    turno.generado_por = 'instructor'
    db.session.commit()
    anteriores = datos_persistidos(turno)

    for _ in range(2):
        resultado = generar_turnos(
            ficha.id, fecha, fecha, rng=random.Random(7),
            recalcular_existentes=True, respetar_manuales=False, proteger_pasados=False,
        )
        db.session.commit()

        conservado = db.session.get(TurnoAseo, anteriores['id'])
        assert conservado is not None
        assert datos_persistidos(conservado) == anteriores
        assert resultado['eliminados'] == 0
        assert resultado['creados'] == resultado['recalculados'] == []
        assert TurnoAseo.query.count() == 1
        contadores = {contador.aprendiz_id: contador.veces_aseo
                      for contador in ContadorAseo.query.filter_by(ficha_id=ficha.id).all()}
        assert contadores == {aprendiz.id: int(marcas[indice] is not False) if indice < 2 else 0
                              for indice, aprendiz in enumerate(aprendices)}


@pytest.mark.parametrize('semilla', [0, 7, 42, 91])
def test_limpieza_y_recalculo_eligen_menor_carga_en_ambos_cupos(grupo, semilla):
    ficha, aprendices = grupo
    for indice, cantidad in ((0, 4), (2, 2)):
        for numero in range(cantidad):
            registrar_turno(
                ficha, aprendices,
                date.today() - timedelta(days=90 + indice * 10 + numero),
                (indice, indice + 1), completado_1=True, completado_2=True,
            )
    sabado, domingo = proximo_fin_de_semana()
    fechas = [fecha for fecha in fechas_futuras(30) if fecha > domingo][:18]
    assert len(fechas) == 18
    previo = registrar_turno(ficha, aprendices, sabado - timedelta(days=1), (0, 1), 'programado')
    for fecha, indices in ((sabado, (0, 1)), (domingo, (2, 3))):
        registrar_turno(ficha, aprendices, fecha, indices, 'programado')
    for fecha in fechas[:-1]:
        registrar_turno(ficha, aprendices, fecha, (0, 1), 'programado')
    manual = registrar_turno(ficha, aprendices, fechas[-1], (4, 5), 'programado')
    manual.generado_por = 'instructor'
    db.session.commit()
    cumplidos = {turno.id: datos_persistidos(turno)
                 for turno in TurnoAseo.query.filter_by(ficha_id=ficha.id, estado='cumplido').all()}
    manual_antes, previo_antes = datos_persistidos(manual), datos_persistidos(previo)

    resultado = generar_turnos(ficha.id, sabado, fechas[-1], rng=random.Random(semilla))
    db.session.commit()

    assert resultado['eliminados'] == 2
    assert len(resultado['recalculados']) == 17
    assert resultado['creados'] == []
    assert datos_persistidos(db.session.get(TurnoAseo, manual_antes['id'])) == manual_antes
    assert datos_persistidos(db.session.get(TurnoAseo, previo_antes['id'])) == previo_antes
    assert {turno.id: datos_persistidos(turno) for turno in TurnoAseo.query.filter_by(
        ficha_id=ficha.id, estado='cumplido',
    ).all()} == cumplidos

    # Incluye el historial cumplido y las reservas pendientes que se conservan.
    cargas = Counter({aprendiz.id: cantidad
                      for aprendiz, cantidad in zip(aprendices, (5, 5, 2, 2, 1, 1))})
    for turno in sorted(resultado['recalculados'], key=lambda item: item.fecha):
        disponibles = dict(cargas)
        for aprendiz_id in (turno.aprendiz_1_id, turno.aprendiz_2_id):
            assert disponibles[aprendiz_id] == min(disponibles.values())
            disponibles.pop(aprendiz_id)
            cargas[aprendiz_id] += 1
    assert max(cargas.values()) - min(cargas.values()) <= 1
    assert not TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha.id, TurnoAseo.fecha.in_([sabado, domingo]),
    ).count()
    assert {contador.aprendiz_id: contador.veces_aseo for contador in
            ContadorAseo.query.filter_by(ficha_id=ficha.id).all()} == {
                aprendiz.id: cantidad for aprendiz, cantidad in zip(aprendices, (4, 4, 2, 2, 0, 0))
            }
