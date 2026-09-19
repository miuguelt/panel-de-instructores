"""Consolida la planeación pedagógica con los juicios vigentes de una ficha."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime

from app.models.aprendiz import (
    ESTADOS_PLANEACION,
    ESTADOS_PLANEACION_ACTIVOS,
    Aprendiz,
    etiqueta_estado,
    tono_estado,
)
from app.models.juicio import JuicioEvaluativo
from app.services.emparejamiento_juicios import (
    clave_resultado as _clave,
    es_aprobado as _aprobado,
    indexar_juicios,
    juicios_de,
    texto_limpio as _texto,
)
from app.services.planeacion import calcular_fechas_estimadas, comparar_fuentes


def _fecha_texto(valor):
    return valor.strftime('%d/%m/%Y') if hasattr(valor, 'strftime') else ''


def _metadata_version(version):
    if not version or not version.metadata_json:
        return {}
    try:
        return json.loads(version.metadata_json)
    except (TypeError, ValueError):
        return {}


def _fecha_metadata(valor):
    if isinstance(valor, date):
        return valor
    texto = _texto(valor)
    for formato in ('%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _fecha_corte(version_reporte, juicios):
    metadata = _metadata_version(version_reporte)
    fecha_reporte = _fecha_metadata(metadata.get('fecha_reporte'))
    if fecha_reporte:
        return fecha_reporte
    return max(
        (
            juicio.fecha_juicio.date()
            if hasattr(juicio.fecha_juicio, 'date')
            else juicio.fecha_juicio
            for juicio in juicios
            if juicio.fecha_juicio
        ),
        default=None,
    )


def _avance_esperado_por_horas(items, fecha_corte):
    """Estima el avance de la planeación usando horas y fechas aproximadas."""
    horas_totales = sum(max(float(item.get('horas_total') or 0), 0) for item in items)
    if not horas_totales or not fecha_corte:
        return 0

    horas_transcurridas = 0.0
    for item in items:
        horas = max(float(item.get('horas_total') or 0), 0)
        inicio = item.get('fecha_inicio_estimada')
        fin = item.get('fecha_fin_estimada')
        if not horas or not inicio or not fin:
            continue
        if fecha_corte >= fin:
            horas_transcurridas += horas
        elif fecha_corte >= inicio:
            dias = max((fin - inicio).days + 1, 1)
            dias_transcurridos = min(max((fecha_corte - inicio).days + 1, 0), dias)
            horas_transcurridas += horas * dias_transcurridos / dias
    return round(min(horas_transcurridas / horas_totales * 100, 100))


def _detalle_sin_planeacion(juicios):
    detalles = []
    vistos = set()
    for juicio in sorted(juicios, key=lambda registro: registro.fecha_juicio or datetime.min, reverse=True):
        clave = (
            _texto(juicio.resultado_aprendizaje),
            _texto(juicio.competencia),
            _texto(juicio.funcionario_registro),
        )
        if not clave[0] or clave in vistos:
            continue
        vistos.add(clave)
        detalles.append({
            'resultado': clave[0],
            'competencia': clave[1],
            'funcionario': clave[2] or 'Sin funcionario registrado',
            'juicio': _texto(juicio.juicio) or 'Sin juicio',
            'fecha': juicio.fecha_juicio,
        })
    return detalles[:12]

def _aprobaciones_previas(juicios, inicio_ficha):
    """Aprobaciones fechadas antes de que la ficha existiera (homologaciones)."""
    if not inicio_ficha:
        return 0
    total = 0
    for juicio in juicios:
        if not juicio.fecha_juicio or not _aprobado(juicio.juicio):
            continue
        fecha = juicio.fecha_juicio.date() if hasattr(juicio.fecha_juicio, 'date') else juicio.fecha_juicio
        if fecha < inicio_ficha:
            total += 1
    return total


def _es_juicio_evaluado(valor):
    """Distingue un juicio emitido de una fila administrativa POR EVALUAR."""
    clave = _clave(valor)
    return bool(clave) and clave not in {'por evaluar', 'pendiente', 'sin evaluar'}


def _fechas_aprobacion(relacionados, activo_ids):
    """Primera aprobación de cada aprendiz, que es la marca de tiempo real.

    Los registros ``POR EVALUAR`` llegan sin fecha, así que las aprobaciones
    son la única evidencia de cuándo se ejecutó el resultado de aprendizaje.
    """
    por_aprendiz = {}
    for juicio in relacionados:
        if not juicio.fecha_juicio or not _aprobado(juicio.juicio):
            continue
        if activo_ids and juicio.aprendiz_id not in activo_ids:
            continue
        fecha = juicio.fecha_juicio.date() if hasattr(juicio.fecha_juicio, 'date') else juicio.fecha_juicio
        actual = por_aprendiz.get(juicio.aprendiz_id)
        if actual is None or fecha < actual:
            por_aprendiz[juicio.aprendiz_id] = fecha
    return sorted(por_aprendiz.values())


def construir_analisis(ficha, contenido_planeacion, version_planeacion=None, version_reporte=None, hoy=None):
    """Devuelve los datos de la vista ejecutiva de planeación."""
    fecha_corte = hoy
    aprendices = Aprendiz.query.filter_by(ficha_id=ficha.id).all()
    aprendices_activos = [
        aprendiz for aprendiz in aprendices
        if aprendiz.estado_normalizado in ESTADOS_PLANEACION_ACTIVOS
    ]
    aprendices_para_avance = [
        aprendiz for aprendiz in aprendices
        if aprendiz.estado_normalizado in ESTADOS_PLANEACION
    ]
    # ``activo_ids`` conserva el nombre histórico, pero ahora representa a
    # todos los estados válidos para el avance de Planeación. Así no se pierde
    # Condicionado, Inducción, Por certificar, Certificado ni Aplazado por
    # depender de query_en_formacion().
    activo_ids = {aprendiz.id for aprendiz in aprendices_para_avance}
    estados_ficha = Counter(aprendiz.estado_normalizado for aprendiz in aprendices)
    estados_aprendices = [
        {
            'codigo': codigo,
            'etiqueta': etiqueta_estado(codigo),
            'cantidad': estados_ficha.get(codigo, 0),
            'activo': codigo in ESTADOS_PLANEACION_ACTIVOS,
            'incluido': codigo in ESTADOS_PLANEACION,
            'tono': tono_estado(codigo),
        }
        for codigo in ESTADOS_PLANEACION
    ]
    for codigo in sorted(set(estados_ficha) - set(ESTADOS_PLANEACION)):
        estados_aprendices.append({
            'codigo': codigo,
            'etiqueta': etiqueta_estado(codigo),
            'cantidad': estados_ficha[codigo],
            'activo': False,
            'incluido': False,
            'tono': tono_estado(codigo),
        })
    juicios = JuicioEvaluativo.query.filter_by(ficha_id=ficha.id).all()
    if fecha_corte is None:
        fecha_corte = _fecha_corte(version_reporte, juicios) or date.today()
    por_clave, por_codigo = indexar_juicios(juicios)
    unidades = calcular_fechas_estimadas(
        contenido_planeacion.get('unidades', []),
        ficha.fecha_inicio,
        ficha.fecha_fin,
    )
    items = []
    juicios_coincidentes = set()
    for unidad in unidades:
        relacionados = juicios_de(unidad, por_clave, por_codigo)
        juicios_coincidentes.update(juicio.id for juicio in relacionados)
        aprendices_evaluados = {juicio.aprendiz_id for juicio in relacionados}
        aprendices_aprobados = {juicio.aprendiz_id for juicio in relacionados if _aprobado(juicio.juicio)}
        juicios_emitidos = [
            juicio for juicio in relacionados
            if _es_juicio_evaluado(juicio.juicio)
            and (not activo_ids or juicio.aprendiz_id in activo_ids)
        ]
        aprendices_con_juicio = {juicio.aprendiz_id for juicio in juicios_emitidos}
        evaluadores = {}
        for juicio in relacionados:
            nombre = _texto(juicio.funcionario_registro) or 'Sin funcionario registrado'
            dato = evaluadores.setdefault(nombre, {'nombre': nombre, 'total': 0, 'aprobados': 0})
            dato['total'] += 1
            if _aprobado(juicio.juicio):
                dato['aprobados'] += 1
        total = len(relacionados)
        aprobados = sum(1 for juicio in relacionados if _aprobado(juicio.juicio))
        if activo_ids:
            pct_avance = round(len(aprendices_aprobados & activo_ids) / len(activo_ids) * 100)
            completo = len(aprendices_aprobados & activo_ids) >= len(activo_ids)
            pct_cobertura = round(len(aprendices_evaluados & activo_ids) / len(activo_ids) * 100)
        else:
            pct_avance = round(aprobados / total * 100) if total else 0
            completo = bool(total and aprobados == total)
            pct_cobertura = 0
        unidad = dict(unidad)
        unidad.update({
            'total_juicios': total,
            'aprobados': aprobados,
            'pendientes': total - aprobados,
            'aprendices_evaluados': len(aprendices_evaluados & activo_ids) if activo_ids else len(aprendices_evaluados),
            'aprendices_aprobados': len(aprendices_aprobados & activo_ids) if activo_ids else len(aprendices_aprobados),
            'porcentaje_avance': pct_avance,
            'porcentaje_aprobacion': round(aprobados / total * 100) if total else 0,
            'porcentaje_cobertura': pct_cobertura,
            'estado': 'completado' if completo else ('en_progreso' if total else 'pendiente'),
            'evaluadores': sorted(evaluadores.values(), key=lambda dato: (-dato['total'], dato['nombre'])),
            'ultima_evaluacion': max((juicio.fecha_juicio for juicio in juicios_emitidos if juicio.fecha_juicio), default=None),
            'total_juicios_evaluados': len(juicios_emitidos),
            'aprendices_con_juicio': len(aprendices_con_juicio),
            'fechas_aprobacion': _fechas_aprobacion(relacionados, activo_ids),
        })
        items.append(unidad)

    plan_ids = set(juicio.id for juicio in juicios)
    juicios_sin_plan = [juicio for juicio in juicios if juicio.id not in juicios_coincidentes]
    total_plan = len(items)
    total_juicios = sum(item['total_juicios'] for item in items)
    aprobados = sum(item['aprobados'] for item in items)
    completos = sum(1 for item in items if item['estado'] == 'completado')
    resultados_con_avance = sum(1 for item in items if item['total_juicios'])
    aprendices_total = len(aprendices)
    aprendices_inactivos = max(aprendices_total - len(aprendices_activos), 0)
    denominador = total_plan * len(activo_ids)
    avance_global = round(sum(item['aprendices_aprobados'] for item in items) / denominador * 100) if denominador else (round(aprobados / total_juicios * 100) if total_juicios else 0)
    cobertura_global = round(resultados_con_avance / total_plan * 100) if total_plan else 0
    avance_esperado = _avance_esperado_por_horas(items, fecha_corte)
    metadatos = contenido_planeacion.get('metadata', {})
    alineacion = comparar_fuentes(metadatos, {
        'codigo_programa': ficha.codigo_programa,
        'nombre_programa': ficha.nombre_programa,
    })
    return {
        'resumen': {
            'resultados_planeados': total_plan,
            'resultados_con_avance': resultados_con_avance,
            'resultados_completos': completos,
            'total_juicios': total_juicios,
            'aprobados': aprobados,
            'pendientes': total_juicios - aprobados,
            'aprendices_activos': len(aprendices_activos),
            'aprendices_analizados': len(aprendices_para_avance),
            'aprendices_total': aprendices_total,
            'aprendices_inactivos': aprendices_inactivos,
            'avance_global': avance_global,
            'avance_esperado': avance_esperado,
            'brecha_vs_esperado': avance_global - avance_esperado,
            'cobertura_global': cobertura_global,
            'horas_total': contenido_planeacion.get('resumen', {}).get('horas_total', 0),
            'horas_directas': contenido_planeacion.get('resumen', {}).get('horas_directas', 0),
            'horas_independientes': contenido_planeacion.get('resumen', {}).get('horas_independientes', 0),
            'resultados_sin_planeacion': len({
                _clave(juicio.resultado_aprendizaje) for juicio in juicios_sin_plan if _clave(juicio.resultado_aprendizaje)
            }),
            'aprobaciones_previas': _aprobaciones_previas(juicios, ficha.fecha_inicio),
        },
        'items': items,
        'estados_aprendices': estados_aprendices,
        'alineacion': alineacion,
        'juicios_sin_planeacion': sorted({
            _texto(juicio.resultado_aprendizaje) for juicio in juicios_sin_plan if juicio.resultado_aprendizaje
        })[:12],
        'juicios_sin_planeacion_detalle': _detalle_sin_planeacion(juicios_sin_plan),
        'version_planeacion': version_planeacion,
        'version_reporte': version_reporte,
        'fecha_corte': fecha_corte,
        'ficha_sincronizada': bool(plan_ids and not juicios_sin_plan),
    }
