"""Distingue los turnos calculados por el motor de los ajustes manuales reales."""

import random
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app import db
from app.models import SesionAsistencia, TurnoAseo
from app.services.aseo import (
    _es_turno_manual,
    generar_turnos,
    reemplazar_aprendices,
    rebalancear_turnos_pendientes,
)
from tests.test_aseo_equidad import fechas_futuras, grupo, registrar_turno  # noqa: F401


@pytest.mark.parametrize('origen, auditoria, esperado', [
    ('aprendiz_admin', 'Asignación manual realizada por el aprendiz.', True),
    ('instructor', 'Asignacion manual realizada por el instructor.', True),
    ('aprendiz_admin', 'Asignado por bolsa de rondas (Ronda 2).', False),
    ('aprendiz', 'Recálculo por equidad total. Menor carga.', False),
    ('aprendiz_admin', 'Te eligió la cola justa porque tu carga era de 1.', False),
    ('instructor', None, True),
    ('instructor', 'Te eligió la cola justa porque tu carga era de 1.', True),
    ('manual', 'Asignado por bolsa de rondas (Ronda 2).', True),
    ('sistema', 'Asignación manual realizada por el instructor.', False),
])
def test_es_turno_manual_exige_origen_y_auditoria_manual(origen, auditoria, esperado):
    turno = SimpleNamespace(generado_por=origen, auditoria_1=auditoria)
    assert _es_turno_manual(turno) is esperado


def _sesiones(ficha, fechas):
    for fecha in fechas:
        db.session.add(SesionAsistencia(ficha_id=ficha.id, fecha=fecha))


def test_generacion_de_aprendiz_admin_queda_como_automatica(grupo):
    ficha, _ = grupo
    fechas = fechas_futuras(3)
    _sesiones(ficha, fechas)
    db.session.commit()

    resultado = generar_turnos(
        ficha.id, fechas[0], fechas[-1], generado_por='aprendiz_admin', rng=random.Random(1),
    )
    db.session.commit()

    assert len(resultado['creados']) == 3
    for turno in resultado['creados']:
        assert turno.generado_por == 'sistema'
        assert 'aprendiz administrador' in turno.auditoria_1
        assert not _es_turno_manual(turno)


def test_recalcular_corrige_turno_automatico_mal_etiquetado_como_manual(grupo):
    ficha, aprendices = grupo
    fechas = fechas_futuras(2)
    _sesiones(ficha, fechas)
    # Día anterior: aprendices 0 y 1. Día siguiente quedó con 0 y 2 marcado como
    # 'aprendiz_admin' por una generación automática: repite al aprendiz 0.
    registrar_turno(ficha, aprendices, fechas[0], (0, 1), 'programado', auditoria_1='Asignado por bolsa de rondas.')
    repetido = registrar_turno(
        ficha, aprendices, fechas[1], (0, 2), 'programado',
        auditoria_1='Asignado por bolsa de rondas (Ronda 1).',
    )
    repetido.generado_por = 'aprendiz_admin'
    db.session.commit()

    generar_turnos(ficha.id, fechas[1], fechas[1], rng=random.Random(3), respetar_manuales=True)
    db.session.commit()

    turno = db.session.get(TurnoAseo, repetido.id)
    pareja = {turno.aprendiz_1_id, turno.aprendiz_2_id}
    assert not pareja & {aprendices[0].id, aprendices[1].id}
    assert turno.generado_por == 'sistema'


def test_ajuste_manual_real_sigue_fijo_al_recalcular(grupo):
    ficha, aprendices = grupo
    fechas = fechas_futuras(2)
    _sesiones(ficha, fechas)
    turno = registrar_turno(ficha, aprendices, fechas[1], (0, 2), 'programado')
    db.session.commit()
    reemplazar_aprendices(turno, aprendices[0], aprendices[2], origen='instructor', recalcular_cascada=False)
    db.session.commit()

    generar_turnos(ficha.id, fechas[0], fechas[1], rng=random.Random(3), respetar_manuales=True)
    db.session.commit()

    conservado = db.session.get(TurnoAseo, turno.id)
    assert {conservado.aprendiz_1_id, conservado.aprendiz_2_id} == {aprendices[0].id, aprendices[2].id}
    assert conservado.generado_por == 'instructor'


def test_rebalancear_corrige_mal_etiquetado_y_respeta_manual_real(grupo):
    ficha, aprendices = grupo
    fechas = fechas_futuras(3)
    _sesiones(ficha, fechas)
    registrar_turno(ficha, aprendices, fechas[0] - timedelta(days=60), (0, 1))
    mal = registrar_turno(
        ficha, aprendices, fechas[0], (0, 1), 'programado',
        auditoria_1='Asignado por bolsa de rondas.',
    )
    mal.generado_por = 'aprendiz'
    manual = registrar_turno(ficha, aprendices, fechas[2], (4, 5), 'programado')
    db.session.commit()
    reemplazar_aprendices(manual, aprendices[4], aprendices[5], origen='aprendiz_admin', recalcular_cascada=False)
    db.session.commit()

    rebalancear_turnos_pendientes(ficha.id, fecha_inicio=fechas[0], generado_por='aprendiz', rng=random.Random(2))
    db.session.commit()

    corregido = db.session.get(TurnoAseo, mal.id)
    # Quienes ya cumplieron un aseo no deben repetir mientras haya alternativas.
    assert not {corregido.aprendiz_1_id, corregido.aprendiz_2_id} & {aprendices[0].id, aprendices[1].id}
    assert corregido.generado_por == 'sistema'
    assert 'aprendiz' in corregido.auditoria_1
    fijo = db.session.get(TurnoAseo, manual.id)
    assert {fijo.aprendiz_1_id, fijo.aprendiz_2_id} == {aprendices[4].id, aprendices[5].id}
