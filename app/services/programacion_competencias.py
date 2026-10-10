"""Cálculo y programación de fechas para competencias y distribución temporal de RAPs."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import joinedload

from app import db
from app.helpers import utc_now
from app.models.archivo_ficha import ArchivoFichaVersion, TIPO_PLANEACION
from app.models.juicio import FichaCompetenciaProgramacion, JuicioEvaluativo
from app.services.emparejamiento_juicios import (
    indexar_juicios,
    juicios_de,
)
from app.services.periodo_formacion import obtener_periodo_formacion
from app.services.planeacion import calcular_fechas_estimadas


def _parsear_fecha(valor: Any) -> date | None:
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def distribuir_raps_en_periodo(
    raps: list[str],
    fecha_inicio: date | str | None,
    fecha_fin: date | str | None,
    pesos_horas: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Distribuye secuencialmente los RAPs cubriendo todo el periodo de la competencia."""
    f_ini = _parsear_fecha(fecha_inicio)
    f_fin = _parsear_fecha(fecha_fin)
    pesos = pesos_horas or {}
    resultado = []
    if not raps:
        return resultado

    if not f_ini or not f_fin or f_fin < f_ini:
        for rap in raps:
            horas = float(pesos.get(rap, 0.0) or 0.0)
            resultado.append({
                'rap': rap, 'fecha_inicio': None, 'fecha_fin': None,
                'fecha_inicio_texto': None, 'fecha_fin_texto': None,
                'fecha_inicio_iso': None, 'fecha_fin_iso': None,
                'dias': None, 'semanas': None, 'horas': horas if horas > 0 else None,
            })
        return resultado

    dias_totales = (f_fin - f_ini).days + 1
    lista_pesos = [max(float(pesos.get(r, 0.0) or 1.0), 1.0) for r in raps]
    total_peso = sum(lista_pesos) or float(len(raps))

    acumulado = 0.0
    for idx, rap in enumerate(raps):
        offset_ini = math.floor(acumulado / total_peso * dias_totales)
        acumulado += lista_pesos[idx]
        offset_fin = math.floor(acumulado / total_peso * dias_totales) - 1
        offset_ini = min(max(offset_ini, 0), dias_totales - 1)
        offset_fin = min(max(offset_fin, offset_ini), dias_totales - 1)
        r_ini = f_ini + timedelta(days=offset_ini)
        r_fin = f_ini + timedelta(days=offset_fin)
        dias_rap = (r_fin - r_ini).days + 1
        horas = float(pesos.get(rap, 0.0) or 0.0)
        resultado.append({
            'rap': rap, 'fecha_inicio': r_ini, 'fecha_fin': r_fin,
            'fecha_inicio_texto': r_ini.strftime('%d/%m/%Y'),
            'fecha_fin_texto': r_fin.strftime('%d/%m/%Y'),
            'fecha_inicio_iso': r_ini.isoformat(),
            'fecha_fin_iso': r_fin.isoformat(),
            'dias': dias_rap, 'semanas': round(dias_rap / 7.0, 1),
            'horas': horas if horas > 0 else None,
        })
    return resultado


def obtener_programacion_competencias(ficha_id: int) -> dict[str, dict[str, Any]]:
    """Devuelve las fechas programadas manualmente por el instructor para una ficha."""
    programadas = (
        FichaCompetenciaProgramacion.query
        .options(joinedload(FichaCompetenciaProgramacion.instructor))
        .filter_by(ficha_id=ficha_id).all()
    )
    return {
        p.competencia: {
            'fecha_inicio': p.fecha_inicio, 'fecha_fin': p.fecha_fin,
            'instructor_id': p.instructor_id,
            'instructor_nombre': p.instructor.nombre if p.instructor else 'Instructor',
            'actualizado_en': p.actualizado_en,
        }
        for p in programadas
    }


def guardar_programacion_competencia(
    ficha_id: int,
    competencia_nombre: str,
    fecha_inicio: date | str | None,
    fecha_fin: date | str | None,
    instructor_id: int | None = None,
) -> FichaCompetenciaProgramacion:
    """Crea o actualiza la programación de fechas de una competencia."""
    f_ini = _parsear_fecha(fecha_inicio)
    f_fin = _parsear_fecha(fecha_fin)
    if f_ini and f_fin and f_fin < f_ini:
        raise ValueError('La fecha de finalización no puede ser anterior a la fecha de inicio.')

    prog = FichaCompetenciaProgramacion.query.filter_by(
        ficha_id=ficha_id, competencia=competencia_nombre.strip(),
    ).first()

    if not prog:
        prog = FichaCompetenciaProgramacion(
            ficha_id=ficha_id, competencia=competencia_nombre.strip(),
            fecha_inicio=f_ini, fecha_fin=f_fin, instructor_id=instructor_id,
        )
        db.session.add(prog)
    else:
        prog.fecha_inicio = f_ini
        prog.fecha_fin = f_fin
        prog.instructor_id = instructor_id
        prog.actualizado_en = utc_now()

    db.session.commit()
    return prog


def limpiar_programacion_competencia(ficha_id: int, competencia_nombre: str) -> bool:
    """Elimina la programación manual para restaurar el cálculo automático."""
    prog = FichaCompetenciaProgramacion.query.filter_by(
        ficha_id=ficha_id, competencia=competencia_nombre.strip(),
    ).first()
    if prog:
        db.session.delete(prog)
        db.session.commit()
        return True
    return False


def calcular_fechas_competencias_y_raps(
    ficha: Any,
    competencias_summary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enriquece las competencias con sus fechas estimadas/programadas y RAPs distribuidos."""
    if not competencias_summary:
        return competencias_summary

    programadas_map = obtener_programacion_competencias(ficha.id)
    version_plan = (
        ArchivoFichaVersion.query
        .filter_by(ficha_id=ficha.id, tipo=TIPO_PLANEACION, estado='procesado')
        .order_by(ArchivoFichaVersion.version.desc()).first()
    )

    unidades_plan = []
    if version_plan and version_plan.contenido_extraido_json:
        raw_unidades = version_plan.contenido_extraido_json.get('unidades', [])
        unidades_plan = calcular_fechas_estimadas(raw_unidades, ficha.fecha_inicio, ficha.fecha_fin)

    juicios = JuicioEvaluativo.query.filter_by(ficha_id=ficha.id).all()
    por_clave_juicios, por_codigo_juicios = indexar_juicios(juicios)

    fechas_planeacion_por_comp: dict[str, dict[str, Any]] = {}
    for u in unidades_plan:
        rel = juicios_de(u, por_clave_juicios, por_codigo_juicios)
        ini, fin = u.get('fecha_inicio_estimada'), u.get('fecha_fin_estimada')
        horas = float(u.get('horas_total') or 0.0)
        for j in rel:
            comp_n = j.competencia or ''
            if not comp_n:
                continue
            entry = fechas_planeacion_por_comp.setdefault(comp_n, {
                'inicio': ini, 'fin': fin, 'raps': {}, 'horas_raps': {}
            })
            if ini:
                entry['inicio'] = min(entry['inicio'], ini) if entry['inicio'] else ini
            if fin:
                entry['fin'] = max(entry['fin'], fin) if entry['fin'] else fin
            rap_n = j.resultado_aprendizaje or ''
            if rap_n:
                entry['raps'][rap_n] = {'inicio': ini, 'fin': fin}
                entry['horas_raps'][rap_n] = max(entry['horas_raps'].get(rap_n, 0.0), horas)

    periodo = obtener_periodo_formacion(ficha)
    ini_lectiva = periodo.get('inicio_lectiva') or ficha.fecha_inicio
    fin_lectiva = periodo.get('fin_lectiva') or ficha.fecha_fin
    total_comps = len(competencias_summary)
    dias_lectivos = ((fin_lectiva - ini_lectiva).days + 1) if (ini_lectiva and fin_lectiva and fin_lectiva >= ini_lectiva) else 0

    for idx, comp in enumerate(competencias_summary):
        nombre_comp = comp['nombre']
        detalles = comp.get('detalles', [])
        raps_unicos = [d['rap'] for d in detalles if d.get('rap')]
        raps_unicos = list(dict.fromkeys(raps_unicos))

        datos_plan = fechas_planeacion_por_comp.get(nombre_comp)
        if datos_plan and datos_plan.get('inicio') and datos_plan.get('fin'):
            f_ini_est, f_fin_est = datos_plan['inicio'], datos_plan['fin']
            pesos_horas = datos_plan.get('horas_raps', {})
        elif dias_lectivos > 0 and total_comps > 0:
            off_ini = min(max(math.floor(idx / total_comps * dias_lectivos), 0), dias_lectivos - 1)
            off_fin = min(max(math.floor((idx + 1) / total_comps * dias_lectivos) - 1, off_ini), dias_lectivos - 1)
            f_ini_est = ini_lectiva + timedelta(days=off_ini)
            f_fin_est = ini_lectiva + timedelta(days=off_fin)
            pesos_horas = {}
        else:
            f_ini_est, f_fin_est, pesos_horas = None, None, {}

        prog_manual = programadas_map.get(nombre_comp)
        if prog_manual and (prog_manual.get('fecha_inicio') or prog_manual.get('fecha_fin')):
            es_manual = True
            f_ini = prog_manual.get('fecha_inicio') or f_ini_est
            f_fin = prog_manual.get('fecha_fin') or f_fin_est
            inst_prog = prog_manual.get('instructor_nombre')
        else:
            es_manual = False
            f_ini, f_fin = f_ini_est, f_fin_est
            inst_prog = None

        raps_distribuidos = distribuir_raps_en_periodo(raps_unicos, f_ini, f_fin, pesos_horas)

        comp.update({
            'fecha_inicio': f_ini.isoformat() if f_ini else None,
            'fecha_fin': f_fin.isoformat() if f_fin else None,
            'fecha_inicio_texto': f_ini.strftime('%d/%m/%Y') if f_ini else None,
            'fecha_fin_texto': f_fin.strftime('%d/%m/%Y') if f_fin else None,
            'fecha_inicio_estimada': f_ini_est.isoformat() if f_ini_est else None,
            'fecha_fin_estimada': f_fin_est.isoformat() if f_fin_est else None,
            'fecha_inicio_estimada_texto': f_ini_est.strftime('%d/%m/%Y') if f_ini_est else None,
            'fecha_fin_estimada_texto': f_fin_est.strftime('%d/%m/%Y') if f_fin_est else None,
            'es_programacion_manual': es_manual,
            'instructor_programo': inst_prog,
            'raps_distribucion': raps_distribuidos,
            'raps_distribucion_mapa': {r['rap']: r for r in raps_distribuidos},
        })

    return competencias_summary
