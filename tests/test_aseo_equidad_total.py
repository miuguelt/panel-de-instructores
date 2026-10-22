"""Regresiones de equidad sobre el total de turnos (cumplidos + programados).

Cubren los dos defectos reportados:
1. El cálculo ignoraba los turnos ya programados fuera del rango, por lo que
   volvía a elegir primero a quienes ya tenían aseo asignado.
2. Una inasistencia debía recompensarse sin romper la equidad ni desalojar los
   turnos ya publicados de los demás.
"""

import random
from collections import defaultdict
from datetime import date, timedelta

import pytest

from app import db
from app.models import SesionAsistencia, TurnoAseo
from app.services.aseo import (
    cargas_pendientes,
    generar_turnos,
    rebalancear_turnos_pendientes,
    recalcular_contadores,
    resumen_equidad,
)
from app.services.aseo_motor_puro import calcular_turnos_token_bucket
from app.services.asistencia import guardar_asistencia
from app.services.festivos import es_festivo_colombia
from tests.test_aseo_equidad import fechas_futuras, grupo, registrar_turno


def cargas_totales(ficha, aprendices):
    contadores = recalcular_contadores(ficha.id)
    pendientes = cargas_pendientes(ficha.id)
    return {
        aprendiz.id: contadores[aprendiz.id].veces_aseo + pendientes.get(aprendiz.id, 0)
        for aprendiz in aprendices
    }


def test_motor_nunca_entrega_cupo_a_quien_tiene_mas_carga_total():
    """El motor puro prioriza siempre la carga total mínima, nunca la máxima."""
    res = calcular_turnos_token_bucket(
        aprendiz_ids=[1, 2, 3, 4, 5, 6],
        sesiones_fechas=[date(2026, 11, 2), date(2026, 11, 3)],
        cargas_iniciales={1: 5, 2: 4, 3: 3, 4: 2, 5: 1, 6: 0},
        rng=random.Random(1),
    )

    primera = {res['asignaciones'][0]['aprendiz_1_id'], res['asignaciones'][0]['aprendiz_2_id']}
    segunda = {res['asignaciones'][1]['aprendiz_1_id'], res['asignaciones'][1]['aprendiz_2_id']}
    assert primera == {5, 6}
    assert segunda == {4, 3}
    assert 1 not in primera | segunda
    assert 2 not in primera | segunda


def test_turno_pendiente_fuera_del_rango_consume_cupo(grupo):
    """Un turno ya programado en otro mes cuenta en el total y baja la prioridad."""
    ficha, aprendices = grupo
    fuera_de_rango = date.today() + timedelta(days=45)
    while es_festivo_colombia(fuera_de_rango):
        fuera_de_rango += timedelta(days=1)

    registrar_turno(
        ficha, aprendices, fuera_de_rango, (0, 1), estado='programado',
    )
    fecha = fechas_futuras(1)[0]
    db.session.add(SesionAsistencia(ficha_id=ficha.id, fecha=fecha))
    db.session.commit()

    turno = generar_turnos(
        ficha.id, fecha, fecha, rng=random.Random(3)
    )['creados'][0]

    # Ana y Bruno ya tienen un aseo programado: no deben repetir antes que el resto.
    assert not turno.incluye(aprendices[0].id)
    assert not turno.incluye(aprendices[1].id)


@pytest.mark.parametrize('semilla', [2, 11, 29])
def test_recalculo_asigna_a_los_de_menor_carga_total(semilla, grupo):
    """Con cargas totales distintas, los cupos van a los dos de menor total."""
    ficha, aprendices = grupo
    hoy = date.today()

    # Cumplidos: Ana y Bruno 2 cada uno; Carmen y Diego 1 cada uno; Elena 0.
    for desplazamiento in (30, 28):
        registrar_turno(
            ficha, aprendices, hoy - timedelta(days=desplazamiento), (0, 1),
        )
    registrar_turno(ficha, aprendices, hoy - timedelta(days=20), (2, 3))
    # Pendientes fuera de rango: suben la carga total de Carmen y Diego a 2.
    lejano_1 = hoy + timedelta(days=50)
    lejano_2 = hoy + timedelta(days=55)
    while es_festivo_colombia(lejano_1) or es_festivo_colombia(lejano_2):
        lejano_1 += timedelta(days=1)
        lejano_2 += timedelta(days=1)
    registrar_turno(ficha, aprendices, lejano_1, (2, 4), estado='programado')
    registrar_turno(ficha, aprendices, lejano_2, (3, 5), estado='programado')
    db.session.commit()

    totales = cargas_totales(ficha, aprendices)
    assert totales[aprendices[4].id] == 1
    assert totales[aprendices[5].id] == 1
    assert totales[aprendices[2].id] == 2
    assert totales[aprendices[3].id] == 2
    assert totales[aprendices[0].id] == 2

    fecha = fechas_futuras(1)[0]
    db.session.add(SesionAsistencia(ficha_id=ficha.id, fecha=fecha))
    db.session.commit()

    turno = generar_turnos(
        ficha.id, fecha, fecha, rng=random.Random(semilla)
    )['creados'][0]

    elegidos = {turno.aprendiz_1_id, turno.aprendiz_2_id}
    assert elegidos == {aprendices[4].id, aprendices[5].id}


def test_recalculo_completo_equilibra_el_total_incluyendo_otros_rangos(grupo):
    """Recalcular un rango deja el total (cumplidos + programados) equilibrado."""
    ficha, aprendices = grupo
    fechas = fechas_futuras(9)
    db.session.add_all([
        SesionAsistencia(ficha_id=ficha.id, fecha=fecha) for fecha in fechas
    ])

    # Historial desigual: Ana y Bruno con 2 cumplidos; el resto con 0.
    for desplazamiento in (20, 18):
        registrar_turno(
            ficha, aprendices, date.today() - timedelta(days=desplazamiento),
            (0, 1),
        )
    db.session.commit()

    generar_turnos(
        ficha.id, fechas[0], fechas[2], rng=random.Random(5), recalcular_existentes=True,
    )
    db.session.commit()

    # Un turno pendiente lejano a la pareja que más carga tiene.
    lejano = fechas[-1] + timedelta(days=30)
    while es_festivo_colombia(lejano):
        lejano += timedelta(days=1)
    registrar_turno(ficha, aprendices, lejano, (0, 1), estado='programado')
    db.session.commit()

    generar_turnos(
        ficha.id, fechas[0], fechas[-1], rng=random.Random(5), recalcular_existentes=True,
    )
    db.session.commit()

    totales = cargas_totales(ficha, aprendices)
    assert max(totales.values()) - min(totales.values()) <= 1


def test_rebalancear_pendientes_iguala_totales_sin_crear_ni_borrar(grupo):
    """El reequilibrio global solo cambia parejas de turnos existentes."""
    ficha, aprendices = grupo
    fechas = fechas_futuras(6)
    db.session.add_all([
        SesionAsistencia(ficha_id=ficha.id, fecha=fecha) for fecha in fechas
    ])
    # Calendario injusto: siempre la misma pareja.
    for fecha in fechas:
        registrar_turno(ficha, aprendices, fecha, (0, 1), estado='programado')
    db.session.commit()
    total_turnos = TurnoAseo.query.count()

    rebalanceados = rebalancear_turnos_pendientes(ficha.id)

    assert TurnoAseo.query.count() == total_turnos
    assert rebalanceados
    reparto = defaultdict(int)
    for turno in TurnoAseo.query.filter_by(ficha_id=ficha.id).all():
        reparto[turno.aprendiz_1_id] += 1
        reparto[turno.aprendiz_2_id] += 1
    assert max(reparto.values()) - min(reparto.values()) <= 1
    assert all(
        'equidad' in (turno.auditoria_1 or '').lower()
        for turno in rebalanceados
    )


def test_rebalancear_conserva_turnos_manuales(grupo):
    """Un ajuste manual publicado no se mueve al equilibrar el calendario."""
    ficha, aprendices = grupo
    fechas = fechas_futuras(4)
    db.session.add_all([
        SesionAsistencia(ficha_id=ficha.id, fecha=fecha) for fecha in fechas
    ])
    for fecha in fechas:
        registrar_turno(ficha, aprendices, fecha, (0, 1), estado='programado')
    manual = TurnoAseo.query.filter_by(ficha_id=ficha.id, fecha=fechas[1]).first()
    manual.generado_por = 'instructor'
    db.session.commit()

    rebalancear_turnos_pendientes(ficha.id)

    db.session.refresh(manual)
    assert {manual.aprendiz_1_id, manual.aprendiz_2_id} == {
        aprendices[0].id, aprendices[1].id,
    }


def test_ausente_se_sustituye_por_quien_menos_carga_total_tiene(grupo):
    """La suplencia por inasistencia usa la carga total, no solo los cumplidos."""
    ficha, aprendices = grupo
    hoy = date.today()

    # Ana y Bruno tienen un cumplido; Carmen no tiene ninguno, pero Diego y
    # Elena arrastran un turno programado lejano: su carga total es mayor.
    registrar_turno(ficha, aprendices, hoy - timedelta(days=10), (0, 1))
    registrar_turno(ficha, aprendices, hoy - timedelta(days=6), (4, 5))
    lejano = hoy + timedelta(days=40)
    while es_festivo_colombia(lejano):
        lejano += timedelta(days=1)
    registrar_turno(ficha, aprendices, lejano, (3, 5), estado='programado')

    fecha = fechas_futuras(1)[0]
    db.session.add(SesionAsistencia(ficha_id=ficha.id, fecha=fecha))
    db.session.commit()

    turno = TurnoAseo(
        ficha_id=ficha.id, fecha=fecha,
        aprendiz_1_id=aprendices[0].id, aprendiz_2_id=aprendices[1].id,
        estado='programado', generado_por='sistema',
    )
    db.session.add(turno)
    db.session.commit()

    totales = cargas_totales(ficha, aprendices)
    assert totales[aprendices[2].id] == 0
    assert totales[aprendices[3].id] == 1
    assert totales[aprendices[4].id] == 1

    registros = {
        aprendiz.id: ('FALTA' if aprendiz.id == aprendices[0].id else 'ASISTE', None)
        for aprendiz in aprendices
    }
    guardar_asistencia(ficha.id, fecha, registros)
    db.session.refresh(turno)

    assert not turno.incluye(aprendices[0].id)
    # El suplente debe ser Carmen: es quien menos carga total tiene de los presentes.
    assert turno.aprendiz_1_id == aprendices[2].id


def test_ausente_con_reposicion_mantiene_la_equidad_del_grupo(grupo):
    """Tras una inasistencia el grupo sigue con diferencia máxima de un turno."""
    ficha, aprendices = grupo
    fechas = fechas_futuras(6)
    db.session.add_all([
        SesionAsistencia(ficha_id=ficha.id, fecha=fecha) for fecha in fechas
    ])
    db.session.commit()
    generar_turnos(ficha.id, fechas[0], fechas[-1], rng=random.Random(9))
    db.session.commit()

    turno = TurnoAseo.query.filter_by(ficha_id=ficha.id, fecha=fechas[0]).first()
    ausente_id = turno.aprendiz_1_id
    registros = {
        aprendiz.id: ('FALTA' if aprendiz.id == ausente_id else 'ASISTE', None)
        for aprendiz in aprendices
    }
    guardar_asistencia(ficha.id, fechas[0], registros)
    db.session.commit()

    totales = cargas_totales(ficha, aprendices)
    assert max(totales.values()) - min(totales.values()) <= 1

    reposicion = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha.id,
        TurnoAseo.fecha > fechas[0],
        TurnoAseo.observacion.like('%Reposición%'),
    ).first()
    assert reposicion is not None
    assert reposicion.incluye(ausente_id)
    # El compañero de reposición sale del grupo de menor carga total del momento.
    companero_id = (
        reposicion.aprendiz_2_id
        if reposicion.aprendiz_1_id == ausente_id
        else reposicion.aprendiz_1_id
    )
    assert totales[companero_id] <= min(totales.values()) + 1


def test_varias_inasistencias_mantienen_el_delta_en_uno(grupo):
    """Las ausencias compensadas no desbalancean el total del grupo."""
    ficha, aprendices = grupo
    fechas = fechas_futuras(8)
    db.session.add_all([
        SesionAsistencia(ficha_id=ficha.id, fecha=fecha) for fecha in fechas
    ])
    db.session.commit()
    generar_turnos(ficha.id, fechas[0], fechas[-1], rng=random.Random(21))
    db.session.commit()

    for indice, fecha in enumerate(fechas[:5]):
        turno = TurnoAseo.query.filter_by(ficha_id=ficha.id, fecha=fecha).first()
        ausente_id = (
            turno.aprendiz_1_id if indice % 2 == 0 else turno.aprendiz_2_id
        )
        registros = {
            aprendiz.id: ('FALTA' if aprendiz.id == ausente_id else 'ASISTE', None)
            for aprendiz in aprendices
        }
        guardar_asistencia(ficha.id, fecha, registros)
        db.session.commit()
        totales = cargas_totales(ficha, aprendices)
        assert max(totales.values()) - min(totales.values()) <= 1
        # El ausente conserva una reposición pendiente para igualar su cupo.
        assert TurnoAseo.query.filter(
            TurnoAseo.ficha_id == ficha.id,
            TurnoAseo.fecha > fecha,
            TurnoAseo.estado.in_(('programado', 'intercambiado')),
            TurnoAseo.observacion.like('%Reposición%'),
        ).count() >= 1


def test_no_duplica_la_reposicion_al_guardar_dos_veces_la_inasistencia(grupo):
    """Marcar dos veces el mismo turno como no cumplido no crea dos reposiciones."""
    from app.services.aseo import marcar_no_cumplido

    ficha, aprendices = grupo
    fecha = fechas_futuras(1)[0]
    db.session.add(SesionAsistencia(ficha_id=ficha.id, fecha=fecha))
    db.session.commit()
    turno = TurnoAseo(
        ficha_id=ficha.id, fecha=fecha,
        aprendiz_1_id=aprendices[0].id, aprendiz_2_id=aprendices[1].id,
        estado='programado', generado_por='sistema',
    )
    db.session.add(turno)
    db.session.commit()

    marcar_no_cumplido(turno, observacion='No se realizó.')
    db.session.commit()
    marcar_no_cumplido(turno, observacion='Se confirmó la inasistencia.')
    db.session.commit()

    reposiciones = TurnoAseo.query.filter(
        TurnoAseo.ficha_id == ficha.id,
        TurnoAseo.fecha > fecha,
        TurnoAseo.observacion.like('%Reposición%'),
    ).all()
    assert len(reposiciones) == 2
    repuestos = set()
    for reposicion in reposiciones:
        repuestos.update((reposicion.aprendiz_1_id, reposicion.aprendiz_2_id))
    assert {aprendices[0].id, aprendices[1].id} <= repuestos


def test_resumen_equidad_reporta_delta_y_pendientes(grupo):
    ficha, aprendices = grupo
    hoy = date.today()
    registrar_turno(ficha, aprendices, hoy - timedelta(days=5), (0, 1))
    registrar_turno(
        ficha, aprendices, fechas_futuras(1)[0], (0, 1), estado='programado',
    )
    db.session.commit()

    resumen = resumen_equidad(ficha.id)

    filas = {fila['aprendiz'].id: fila for fila in resumen['filas']}
    assert filas[aprendices[0].id]['cumplidos'] == 1
    assert filas[aprendices[0].id]['programados'] == 1
    assert filas[aprendices[0].id]['total'] == 2
    assert filas[aprendices[4].id]['total'] == 0
    assert resumen['delta'] == 2
    assert resumen['minimo'] == 0
    assert resumen['maximo'] == 2


def test_boton_calcular_reporta_equidad_y_equilibra_todo(grupo):
    """El botón "Calcular turnos" informa el delta y reequilibra el total."""
    from flask import current_app

    ficha, aprendices = grupo
    fechas = fechas_futuras(3)
    db.session.add_all([
        SesionAsistencia(ficha_id=ficha.id, fecha=fecha) for fecha in fechas
    ])
    db.session.commit()

    cliente = current_app.test_client()
    with cliente.session_transaction() as sesion:
        sesion['_user_id'] = str(ficha.instructor_id)
        sesion['_fresh'] = True

    respuesta = cliente.post(
        f'/instructor/fichas/{ficha.id}/turnos-aseo/generar',
        data={
            'fecha_inicio': fechas[0].isoformat(),
            'fecha_fin': fechas[-1].isoformat(),
            'recalcular': 'on',
            'respetar_manuales': 'on',
            'equilibrar_calendario': 'on',
        },
        follow_redirects=True,
    )

    assert respuesta.status_code == 200
    assert 'Equidad resultante'.encode() in respuesta.data
    assert 'Calcular turnos'.encode() in respuesta.data
    assert 'Programados'.encode() in respuesta.data
    assert TurnoAseo.query.filter_by(ficha_id=ficha.id).count() == len(fechas)
