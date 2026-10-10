"""Lectura autorizada del reporte TyT con persistencia en snapshots reutilizables."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Dict, List, Optional

from flask import current_app

from app import db
from app.models.aprendiz import Aprendiz
from app.models.juicio import JuicioEvaluativo
from app.models.resultado_calculado import ResultadoCalculadoFicha
from app.services.periodo_formacion import obtener_periodo_formacion
from app.services.resultados_persistidos import (
    ALGORITMO_RESULTADOS,
    _json_default,
    _json_object_hook,
    fecha_corte_bogota,
)
from app.tyt.calculo import _hoy_colombia, _tiempo, calcular_seguimiento


def _huella_fuentes_tyt(ficha) -> str:
    """Genera la clave de integridad del snapshot con la revisión actual."""
    entrada = {
        'tipo': 'tyt',
        'ficha_id': ficha.id,
        'revision': ficha.revision_calculos or 1,
    }
    serializado = json.dumps(entrada, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serializado.encode('utf-8')).hexdigest()


def _obtener_snapshot_tyt_reciente(ficha_id: int, revision: int) -> Optional[Dict[str, Any]]:
    """Recupera el último snapshot de TyT persistido para la revisión actual."""
    try:
        fila = (
            ResultadoCalculadoFicha.query.filter_by(
                ficha_id=ficha_id,
                tipo='tyt',
                revision_calculo=revision or 1,
                version_algoritmo=ALGORITMO_RESULTADOS,
            )
            .order_by(ResultadoCalculadoFicha.fecha_corte.desc())
            .first()
        )
        if fila and fila.payload_json:
            return json.loads(json.dumps(fila.payload_json), object_hook=_json_object_hook)
    except Exception:
        current_app.logger.exception('Error leyendo snapshot de TyT para la ficha %s', ficha_id)
    return None


def _adaptar_tyt_a_hoy(payload: Dict[str, Any], ficha, hoy: Optional[date] = None) -> Dict[str, Any]:
    """Recalcula los tiempos de calendario de un snapshot en microsegundos."""
    calendario = obtener_periodo_formacion(ficha, hoy)
    tiempo = _tiempo(calendario['inicio_lectiva'], calendario['fin_lectiva'], _hoy_colombia(hoy))
    resultado = dict(payload)
    resultado['tiempo'] = tiempo
    resultado['calendario'] = calendario
    return resultado


def _guardar_snapshot_tyt(ficha, resultado: Dict[str, Any], fecha_corte: date) -> None:
    """Persiste el cálculo base en la base de datos para reutilizarlo."""
    try:
        huella = _huella_fuentes_tyt(ficha)
        db.session.add(ResultadoCalculadoFicha(
            ficha_id=ficha.id,
            tipo='tyt',
            fecha_corte=fecha_corte,
            revision_calculo=ficha.revision_calculos or 1,
            version_algoritmo=ALGORITMO_RESULTADOS,
            huella_fuentes=huella,
            payload_json=json.loads(json.dumps(
                resultado, ensure_ascii=False, default=_json_default, separators=(',', ':'),
            )),
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error guardando snapshot de TyT para la ficha %s', ficha.id)


def obtener_seguimiento(ficha, hoy=None):
    """Retorna el seguimiento TyT vigente o lo calcula y persiste una sola vez."""
    hoy_fecha = hoy or fecha_corte_bogota()
    snapshot = _obtener_snapshot_tyt_reciente(ficha.id, ficha.revision_calculos)
    if snapshot:
        return _adaptar_tyt_a_hoy(snapshot, ficha, hoy_fecha)

    aprendices = [a for a in Aprendiz.query.filter_by(ficha_id=ficha.id)
                  .order_by(Aprendiz.apellidos, Aprendiz.nombre).all()
                  if a.activo_en_planeacion]
    juicios = JuicioEvaluativo.query.with_entities(
        JuicioEvaluativo.aprendiz_id, JuicioEvaluativo.competencia,
        JuicioEvaluativo.resultado_aprendizaje, JuicioEvaluativo.juicio,
    ).filter_by(ficha_id=ficha.id).order_by(
        JuicioEvaluativo.importado_en, JuicioEvaluativo.id,
    ).all()
    calendario = obtener_periodo_formacion(ficha, hoy_fecha)
    seguimiento = calcular_seguimiento(
        [{'id': a.id, 'nombre': a.nombre_completo} for a in aprendices],
        [dict(j._mapping) for j in juicios],
        calendario['inicio_lectiva'], calendario['fin_lectiva'], hoy_fecha,
    )
    resultado = {**seguimiento, 'calendario': calendario}
    _guardar_snapshot_tyt(ficha, resultado, hoy_fecha)
    return resultado


def obtener_seguimiento_por_fichas(fichas, hoy=None):
    """Carga y calcula el seguimiento TyT para un conjunto de fichas reutilizando snapshots."""
    if not fichas:
        return {}
    hoy_fecha = hoy or fecha_corte_bogota()
    ficha_ids = [f.id for f in fichas]
    fichas_por_id = {f.id: f for f in fichas}

    # 1. Buscar snapshots existentes para la revisión de cada ficha
    snapshots_candidatos = (
        ResultadoCalculadoFicha.query.filter(
            ResultadoCalculadoFicha.ficha_id.in_(ficha_ids),
            ResultadoCalculadoFicha.tipo == 'tyt',
            ResultadoCalculadoFicha.version_algoritmo == ALGORITMO_RESULTADOS,
        )
        .order_by(ResultadoCalculadoFicha.fecha_corte.desc())
        .all()
    )
    snapshots_validos: Dict[int, Dict[str, Any]] = {}
    for snap in snapshots_candidatos:
        fid = snap.ficha_id
        if fid not in snapshots_validos:
            ficha_obj = fichas_por_id.get(fid)
            rev_esperada = ficha_obj.revision_calculos or 1 if ficha_obj else 1
            if snap.revision_calculo == rev_esperada and snap.payload_json:
                snapshots_validos[fid] = json.loads(
                    json.dumps(snap.payload_json), object_hook=_json_object_hook
                )

    resultados = {}
    fichas_pendientes = []
    for ficha in fichas:
        fid = ficha.id
        if fid in snapshots_validos:
            resultados[fid] = _adaptar_tyt_a_hoy(snapshots_validos[fid], ficha, hoy_fecha)
        else:
            fichas_pendientes.append(ficha)

    if not fichas_pendientes:
        return resultados

    # 2. Solo para fichas sin snapshot vigente, ejecutar las dos consultas en lote
    ids_pendientes = [f.id for f in fichas_pendientes]
    aprendices_todos = (
        Aprendiz.query.filter(Aprendiz.ficha_id.in_(ids_pendientes))
        .order_by(Aprendiz.ficha_id, Aprendiz.apellidos, Aprendiz.nombre)
        .all()
    )
    juicios_todos = (
        JuicioEvaluativo.query.with_entities(
            JuicioEvaluativo.ficha_id,
            JuicioEvaluativo.aprendiz_id,
            JuicioEvaluativo.competencia,
            JuicioEvaluativo.resultado_aprendizaje,
            JuicioEvaluativo.juicio,
        )
        .filter(JuicioEvaluativo.ficha_id.in_(ids_pendientes))
        .order_by(
            JuicioEvaluativo.ficha_id,
            JuicioEvaluativo.importado_en,
            JuicioEvaluativo.id,
        )
        .all()
    )

    aprendices_por_ficha = {fid: [] for fid in ids_pendientes}
    for a in aprendices_todos:
        if a.activo_en_planeacion:
            aprendices_por_ficha[a.ficha_id].append(a)

    juicios_por_ficha = {fid: [] for fid in ids_pendientes}
    for j in juicios_todos:
        juicios_por_ficha[j.ficha_id].append({
            'aprendiz_id': j.aprendiz_id,
            'competencia': j.competencia,
            'resultado_aprendizaje': j.resultado_aprendizaje,
            'juicio': j.juicio,
        })

    for ficha in fichas_pendientes:
        fid = ficha.id
        ap_lista = [{'id': a.id, 'nombre': a.nombre_completo} for a in aprendices_por_ficha.get(fid, [])]
        j_lista = juicios_por_ficha.get(fid, [])
        calendario = obtener_periodo_formacion(ficha, hoy_fecha)
        seguimiento = calcular_seguimiento(
            ap_lista,
            j_lista,
            calendario['inicio_lectiva'],
            calendario['fin_lectiva'],
            hoy_fecha,
        )
        res = {**seguimiento, 'calendario': calendario}
        resultados[fid] = res
        _guardar_snapshot_tyt(ficha, res, hoy_fecha)

    return resultados
