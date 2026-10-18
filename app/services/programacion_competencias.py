"""Cálculo y programación de fechas para competencias y distribución temporal de RAPs."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import joinedload

from app import db
from app.helpers import utc_now
from app.models.archivo_ficha import ArchivoFichaVersion, TIPO_PLANEACION, TIPO_PROGRAMA
from app.models.juicio import FichaCompetenciaProgramacion, JuicioEvaluativo
from app.services.contraste_programa import contrastar_con_programa
from app.services.emparejamiento_juicios import (
    clave_resultado,
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


def auditar_duracion_programa(ficha: Any) -> dict[str, Any]:
    """Audita la duración del programa formativo (etapa lectiva y productiva).

    Para el programa ADSO y la formación titulada del SENA, la etapa lectiva
    comprende 21 meses (aproximadamente 638 días y 3.120 - 3.360 horas), mientras
    que la etapa productiva comprende 6 meses (aproximadamente 184 días y 864 horas),
    totalizando 27 meses de duración global.
    """
    periodo = obtener_periodo_formacion(ficha)
    ini_lectiva = periodo.get('inicio_lectiva') or ficha.fecha_inicio
    fin_lectiva = periodo.get('fin_lectiva')
    ini_prod = periodo.get('inicio_productiva')
    fin_prod = periodo.get('fin_productiva') or ficha.fecha_fin

    if not ini_lectiva or not fin_lectiva or fin_lectiva < ini_lectiva:
        return {
            'configurado': False,
            'meses_lectivos': 0.0,
            'meses_productivos': 0.0,
            'meses_totales': 0.0,
            'dias_lectivos': 0,
            'dias_productivos': 0,
            'dias_totales': 0,
            'cumple_21_meses': False,
            'inicio_lectiva': None,
            'fin_lectiva': None,
            'inicio_productiva': None,
            'fin_productiva': None,
            'inicio_lectiva_texto': None,
            'fin_lectiva_texto': None,
            'inicio_productiva_texto': None,
            'fin_productiva_texto': None,
            'resumen_texto': 'Fechas de formación incompletas o no configuradas.',
        }

    dias_lectivos = (fin_lectiva - ini_lectiva).days + 1
    meses_lectivos = round(dias_lectivos / 30.4375, 1)

    dias_prod = ((fin_prod - ini_prod).days + 1) if (ini_prod and fin_prod and fin_prod >= ini_prod) else 0
    meses_prod = round(dias_prod / 30.4375, 1) if dias_prod > 0 else 0.0

    dias_totales = ((fin_prod - ini_lectiva).days + 1) if (fin_prod and fin_prod >= ini_lectiva) else dias_lectivos
    meses_totales = round(dias_totales / 30.4375, 1)

    cumple_21 = bool(19.5 <= meses_lectivos <= 22.0)

    f_ini_l_str = ini_lectiva.strftime('%d/%m/%Y')
    f_fin_l_str = fin_lectiva.strftime('%d/%m/%Y')
    f_ini_p_str = ini_prod.strftime('%d/%m/%Y') if ini_prod else 'N/A'
    f_fin_p_str = fin_prod.strftime('%d/%m/%Y') if fin_prod else 'N/A'

    resumen = (
        f'Etapa lectiva de {meses_lectivos} meses ({f_ini_l_str} – {f_fin_l_str}) '
        f'y etapa productiva de {meses_prod} meses ({f_ini_p_str} – {f_fin_p_str}), '
        f'totalizando {meses_totales} meses de formación.'
    )

    return {
        'configurado': True,
        'meses_lectivos': meses_lectivos,
        'meses_productivos': meses_prod,
        'meses_totales': meses_totales,
        'dias_lectivos': dias_lectivos,
        'dias_productivos': dias_prod,
        'dias_totales': dias_totales,
        'cumple_21_meses': cumple_21,
        'inicio_lectiva': ini_lectiva,
        'fin_lectiva': fin_lectiva,
        'inicio_productiva': ini_prod,
        'fin_productiva': fin_prod,
        'inicio_lectiva_texto': f_ini_l_str,
        'fin_lectiva_texto': f_fin_l_str,
        'inicio_productiva_texto': f_ini_p_str,
        'fin_productiva_texto': f_fin_p_str,
        'resumen_texto': resumen,
    }


def calcular_fechas_competencias_y_raps(
    ficha: Any,
    competencias_summary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enriquece las competencias con sus fechas estimadas/programadas, horas y RAPs distribuidos.

    Garantiza que la etapa lectiva se distribuya estrictamente dentro de los 21 meses
    calendario reglamentarios y que cada competencia y RAP exponga su carga horaria.
    """
    if not competencias_summary:
        return competencias_summary

    programadas_map = obtener_programacion_competencias(ficha.id)
    periodo = obtener_periodo_formacion(ficha)
    ini_lectiva = periodo.get('inicio_lectiva') or ficha.fecha_inicio
    fin_lectiva = periodo.get('fin_lectiva') or ficha.fecha_fin
    ini_prod = periodo.get('inicio_productiva')
    fin_prod = periodo.get('fin_productiva') or ficha.fecha_fin

    version_plan = ArchivoFichaVersion.obtener_version_activa(ficha.id, TIPO_PLANEACION)
    version_prog = ArchivoFichaVersion.obtener_version_activa(ficha.id, TIPO_PROGRAMA)

    unidades_plan = []
    raw_unidades = []
    if version_plan and version_plan.contenido_extraido_json:
        raw_unidades = version_plan.contenido_extraido_json.get('unidades', [])
        # DISTRIBUCIÓN ESTRICTAMENTE EN ETAPA LECTIVA (21 MESES):
        unidades_plan = calcular_fechas_estimadas(raw_unidades, ini_lectiva, fin_lectiva)

    prog_data = version_prog.contenido_extraido_json if (version_prog and version_prog.contenido_extraido_json) else {}
    contraste: dict[str, Any] = {}
    mapa_comps: dict[str, Any] = {}
    dicc_pedagogico: dict[str, Any] = {}
    comparadas_map: dict[str, Any] = {}
    if prog_data and raw_unidades:
        contraste = contrastar_con_programa(raw_unidades, prog_data, meses_lectivos=21)
        mapa_comps = contraste.get('mapa_competencias', {})
        dicc_pedagogico = contraste.get('diccionario_pedagogico', {})
        for c in contraste.get('competencias', []):
            if c.get('codigo_norma'):
                comparadas_map[str(c['codigo_norma'])] = c

    juicios = JuicioEvaluativo.query.filter_by(ficha_id=ficha.id).all()
    por_clave_juicios, por_codigo_juicios = indexar_juicios(juicios)

    fechas_planeacion_por_comp: dict[str, dict[str, Any]] = {}
    for u in unidades_plan:
        rel = juicios_de(u, por_clave_juicios, por_codigo_juicios)
        ini, fin = u.get('fecha_inicio_estimada'), u.get('fecha_fin_estimada')
        horas = float(u.get('horas_total') or 0.0)
        pares = [(j.competencia or '', j.resultado_aprendizaje or '') for j in rel if j.competencia]
        if not pares:
            c_u = u.get('competencia') or ''
            r_u = u.get('rap') or ''
            if c_u:
                pares = [(c_u, r_u)]

        for comp_n, rap_n in pares:
            if not comp_n:
                continue
            entry = fechas_planeacion_por_comp.setdefault(comp_n, {
                'inicio': ini, 'fin': fin, 'raps': {}, 'horas_raps': {}
            })
            if ini:
                entry['inicio'] = min(entry['inicio'], ini) if entry['inicio'] else ini
            if fin:
                entry['fin'] = max(entry['fin'], fin) if entry['fin'] else fin
            if rap_n:
                entry['raps'][rap_n] = {
                    'inicio': ini,
                    'fin': fin,
                    'horas': horas,
                    'horas_directas': float(u.get('horas_directas') or 0.0),
                    'horas_independientes': float(u.get('horas_independientes') or 0.0),
                }
                entry['horas_raps'][rap_n] = max(entry['horas_raps'].get(rap_n, 0.0), horas)

    total_comps = len(competencias_summary)
    dias_lectivos = ((fin_lectiva - ini_lectiva).days + 1) if (ini_lectiva and fin_lectiva and fin_lectiva >= ini_lectiva) else 0

    for idx, comp in enumerate(competencias_summary):
        nombre_comp = comp['nombre']
        detalles = comp.get('detalles', [])
        raps_unicos = [d['rap'] for d in detalles if d.get('rap')]
        raps_unicos = list(dict.fromkeys(raps_unicos))

        # Determinar si es competencia de etapa productiva / práctica
        nombre_lower = (nombre_comp or '').lower()
        es_productiva = bool(
            comp.get('tipo') == 'productiva'
            or 'etapa practica' in nombre_lower
            or 'etapa práctica' in nombre_lower
            or 'etapa productiva' in nombre_lower
            or 'resultados de aprendizaje etapa practica' in nombre_lower
        )

        datos_plan = fechas_planeacion_por_comp.get(nombre_comp)

        # ── 1. Resolver Horas oficiales y planeadas ──
        horas_oficial: float | None = None
        horas_plan: float | None = None
        cod_match = re.search(r'\b(\d{7,10})\b', nombre_comp)
        cod_norma = cod_match.group(1) if cod_match else ''
        info_prog = None

        if es_productiva:
            meta_prod_h = float(prog_data.get('metadata', {}).get('horas_productiva') or 864.0)
            horas_oficial = meta_prod_h
            horas_plan = meta_prod_h
        else:
            if cod_norma and cod_norma in dicc_pedagogico:
                info_prog = dicc_pedagogico[cod_norma]
            elif nombre_comp in mapa_comps:
                info_prog = mapa_comps[nombre_comp]
            elif clave_resultado(nombre_comp) in mapa_comps:
                info_prog = mapa_comps[clave_resultado(nombre_comp)]
            elif clave_resultado(nombre_comp) in dicc_pedagogico:
                info_prog = dicc_pedagogico[clave_resultado(nombre_comp)]
            else:
                for k, comp_item in dicc_pedagogico.items():
                    if k and (k in clave_resultado(nombre_comp) or clave_resultado(nombre_comp) in k):
                        info_prog = comp_item
                        break

            if info_prog:
                horas_oficial = float(info_prog.get('horas') or 0.0) or None
                comp_comp = comparadas_map.get(str(info_prog.get('codigo_norma') or ''))
                if comp_comp and comp_comp.get('horas_planeacion') is not None:
                    horas_plan = float(comp_comp['horas_planeacion'])

            if horas_plan is None and datos_plan and datos_plan.get('horas_raps'):
                horas_plan = float(sum(datos_plan['horas_raps'].values()))

        # Priorizar horas del programa curricular, luego planeación
        horas_totales_comp = horas_oficial if horas_oficial is not None else horas_plan
        if horas_totales_comp is None and datos_plan and datos_plan.get('horas_raps'):
            horas_totales_comp = float(sum(datos_plan['horas_raps'].values()))

        # ── 2. Fechas estimadas ──
        if es_productiva:
            f_ini_est = ini_prod or (fin_lectiva + timedelta(days=1) if fin_lectiva else None)
            f_fin_est = fin_prod or ficha.fecha_fin
            pesos_horas = {r: (horas_totales_comp or 864.0) for r in raps_unicos}
        elif datos_plan and datos_plan.get('inicio') and datos_plan.get('fin'):
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

        # ── 3. Programación manual del instructor ──
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

        # ── 4. Distribución de RAPs y sus horas ──
        raps_distribuidos = []
        todos_tienen_fecha_directa = (
            not es_manual and datos_plan and datos_plan.get('raps')
            and all(r in datos_plan['raps'] and datos_plan['raps'][r].get('inicio') and datos_plan['raps'][r].get('fin') for r in raps_unicos)
        )

        if todos_tienen_fecha_directa:
            for rap in raps_unicos:
                r_info = datos_plan['raps'][rap]
                r_ini = r_info['inicio']
                r_fin = r_info['fin']
                dias_rap = (r_fin - r_ini).days + 1 if (r_ini and r_fin) else None
                h_rap = r_info.get('horas')
                if not h_rap or h_rap <= 0:
                    h_rap = pesos_horas.get(rap, 0.0)
                raps_distribuidos.append({
                    'rap': rap,
                    'fecha_inicio': r_ini,
                    'fecha_fin': r_fin,
                    'fecha_inicio_texto': r_ini.strftime('%d/%m/%Y') if r_ini else None,
                    'fecha_fin_texto': r_fin.strftime('%d/%m/%Y') if r_fin else None,
                    'fecha_inicio_iso': r_ini.isoformat() if r_ini else None,
                    'fecha_fin_iso': r_fin.isoformat() if r_fin else None,
                    'dias': dias_rap,
                    'semanas': round(dias_rap / 7.0, 1) if dias_rap is not None else None,
                    'horas': float(h_rap) if h_rap and float(h_rap) > 0 else (round(horas_totales_comp / len(raps_unicos), 1) if horas_totales_comp and len(raps_unicos) > 0 else None),
                })
        else:
            raps_distribuidos = distribuir_raps_en_periodo(raps_unicos, f_ini, f_fin, pesos_horas)
            if horas_totales_comp and raps_unicos:
                promedio_h = round(horas_totales_comp / len(raps_unicos), 1)
                for r_item in raps_distribuidos:
                    if not r_item.get('horas'):
                        r_item['horas'] = promedio_h

        if horas_totales_comp is None and raps_distribuidos:
            suma_raps = sum(r.get('horas') or 0.0 for r in raps_distribuidos)
            if suma_raps > 0:
                horas_totales_comp = suma_raps

        comp.update({
            'horas': round(horas_totales_comp, 1) if horas_totales_comp is not None else None,
            'horas_programa': round(horas_oficial, 1) if horas_oficial is not None else None,
            'horas_planeadas': round(horas_plan, 1) if horas_plan is not None else None,
            'diferencia_horas': round(horas_plan - horas_oficial, 1) if (horas_plan is not None and horas_oficial is not None) else None,
            'es_productiva': es_productiva,
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
