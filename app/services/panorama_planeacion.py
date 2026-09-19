"""Compone la visión panorámica de una ficha para la vista de planeación.

Une cinco piezas independientes: el contraste planeación/juicios, el
calendario por trimestres, la ubicación temporal de cada resultado, la
proyección de cierre y el contraste contra el diseño curricular oficial.
La vista solo consume el resultado.
"""

from __future__ import annotations

from datetime import date


from app.services.analisis_planeacion import construir_analisis
from app.services.calendario_formacion import construir_calendario
from app.services.catalogo_pedagogico import construir_catalogo, enriquecer_con_pedagogia
from app.services.contraste_programa import contrastar_con_programa
from app.services.diagnostico_planeacion import revisar_datos_planeacion
from app.services.graficos_planeacion import (
    construir_curva_svg,
    construir_fases_progreso,
    construir_heatmap_docente,
    construir_radar,
)
from app.services.linea_tiempo import construir_linea_tiempo
from app.services.proyeccion_ficha import construir_proyeccion
from app.services.seguimiento_fases import construir_seguimiento_fases


def _texto_proyeccion(proyeccion, calendario):
    if proyeccion['estado'] == 'sin_datos':
        return ('Todavía no hay aprobaciones fechadas suficientes para estimar el ritmo '
                'de cierre de la etapa lectiva.')
    fin = calendario['fin_lectiva'].strftime('%d/%m/%Y')
    proyectada = proyeccion['fecha_proyectada'].strftime('%d/%m/%Y')
    diferencia = abs(proyeccion['dias_vs_fin_lectiva'])
    ritmo = f"{proyeccion['ritmo_mensual']:g} aprobaciones por mes"
    if proyeccion['estado'] == 'completado':
        return f'Los resultados de la etapa lectiva ya están cerrados. La etapa termina el {fin}.'
    if proyeccion['dias_vs_fin_lectiva'] > 0:
        return (f'Al ritmo actual de {ritmo}, lo que falta se cerraría el {proyectada}: '
                f'{diferencia} días después de que termine la etapa lectiva, el {fin}.')
    return (f'Al ritmo actual de {ritmo}, lo que falta se cerraría el {proyectada}, '
            f'{diferencia} días antes de que termine la etapa lectiva, el {fin}.')


def _veredicto(linea, proyeccion, calendario):
    """Resume en una frase si la ficha va bien de tiempo o está quedada."""
    if not calendario['configurado']:
        return {
            'tono': 'danger', 'icono': '📅',
            'titulo': 'La ficha no tiene calendario',
            'detalle': calendario['mensaje'],
        }
    atrasadas = linea['resumen']['competencias_atrasadas']
    criticas = linea['resumen']['competencias_criticas']
    total = linea['resumen']['competencias_exigibles']
    cola = _texto_proyeccion(proyeccion, calendario)
    if criticas or proyeccion['estado'] == 'en_riesgo':
        return {
            'tono': 'danger', 'icono': '⏰',
            'titulo': f'La ficha está quedada en {atrasadas} de {total} competencias técnicas',
            'detalle': (f'{criticas} llevan más de un trimestre vencidas sin cerrar. ' if criticas else '') + cola,
        }
    if atrasadas:
        return {
            'tono': 'warning', 'icono': '⚠️',
            'titulo': f'{atrasadas} de {total} competencias técnicas van con retraso',
            'detalle': f'El retraso equivale a {linea["resumen"]["trimestres_desfase"]:g} trimestres. ' + cola,
        }
    return {
        'tono': 'success', 'icono': '✅',
        'titulo': 'La ficha va al día con el calendario',
        'detalle': f'Ninguna competencia técnica superó el trimestre en que estaba planeada. {cola}',
    }




def _calcular_desempeno_ficha(analisis, linea, proyeccion, contraste, catalogo_ped):
    """Calcula las métricas estratégicas derivadas del cruce de los tres documentos."""
    total_saberes = 0
    saberes_cubiertos = 0
    total_criterios = 0
    criterios_cubiertos = 0

    competencias_vistas = set()
    for item in (catalogo_ped or {}).values():
        cod = item.get('codigo_norma') or item.get('nombre')
        if not cod or cod in competencias_vistas:
            continue
        competencias_vistas.add(cod)

        n_sab = len(item.get('conocimientos_saber', [])) + len(item.get('conocimientos_proceso', []))
        n_crit = len(item.get('criterios_evaluacion', []))
        total_saberes += n_sab
        total_criterios += n_crit

        if (item.get('porcentaje_avance') or 0) >= 80:
            saberes_cubiertos += n_sab
            criterios_cubiertos += n_crit

    items_analisis = (analisis or {}).get('items', [])
    evaluadores_distintos = set()
    instructores_planeados = set()
    for item in items_analisis:
        for inst in item.get('instructores') or []:
            instructores_planeados.add(inst)
        for ev in item.get('evaluadores') or []:
            evaluadores_distintos.add(ev.get('nombre'))

    evm = (proyeccion or {}).get('evm') or {}
    spi = evm.get('spi') or 1.0

    return {
        'total_saberes': total_saberes,
        'saberes_cubiertos': saberes_cubiertos,
        'pct_saberes_cubiertos': round((saberes_cubiertos / total_saberes * 100)) if total_saberes else 0,
        'total_criterios': total_criterios,
        'criterios_cubiertos': criterios_cubiertos,
        'pct_criterios_cubiertos': round((criterios_cubiertos / total_criterios * 100)) if total_criterios else 0,
        'evaluadores_sofia_count': len(evaluadores_distintos),
        'instructores_planeados_count': len(instructores_planeados),
        'spi': spi,
        'spi_label': evm.get('label', 'Normal'),
        'desfase_horas': evm.get('sv_horas', 0),
    }


def construir_panorama(ficha, contenido_planeacion, version_planeacion=None,
                       version_reporte=None, programa=None, hoy=None):
    """Devuelve el análisis y su lectura temporal lista para la plantilla."""
    hoy = hoy or date.today()
    analisis = construir_analisis(
        ficha,
        contenido_planeacion,
        version_planeacion=version_planeacion,
        version_reporte=version_reporte,
    )
    calendario = construir_calendario(ficha, hoy=hoy)
    aprendices_meta = analisis['resumen']['aprendices_analizados']
    linea = construir_linea_tiempo(
        analisis['items'], calendario, aprendices_meta=aprendices_meta, hoy=hoy,
    )
    seguimiento_fases = construir_seguimiento_fases(linea, calendario, hoy=hoy)
    proyeccion = construir_proyeccion(
        linea['resultados'], calendario, aprendices_meta=aprendices_meta, hoy=hoy,
    )
    contraste = contrastar_con_programa(
        contenido_planeacion.get('unidades', []),
        programa,
        meses_lectivos=calendario.get('meses_lectiva', 0),
    )
    enriquecer_con_pedagogia(linea, contraste)
    catalogo_ped = construir_catalogo(linea, contraste)
    diagnostico = revisar_datos_planeacion(
        linea['resultados'],
        calendario,
        resumen=analisis['resumen'],
        aprobaciones_previas=analisis['resumen'].get('aprobaciones_previas', 0),
        contraste=contraste,
    )
    radar = construir_radar(linea, contraste, programa)
    heatmap_docente = construir_heatmap_docente(linea, calendario)
    curva_svg = construir_curva_svg(proyeccion, calendario, hoy=hoy)
    fases_progreso = construir_fases_progreso(linea, seguimiento=seguimiento_fases)
    desempeno = _calcular_desempeno_ficha(analisis, linea, proyeccion, contraste, catalogo_ped)

    return {
        'analisis': analisis,
        'calendario': calendario,
        'linea': linea,
        'seguimiento_fases': seguimiento_fases,
        'proyeccion': proyeccion,
        'diagnostico': diagnostico,
        'contraste': contraste,
        'catalogo_pedagogico': catalogo_ped,
        'desempeno_ficha': desempeno,
        'radar': radar,
        'heatmap_docente': heatmap_docente,
        'curva_svg': curva_svg,
        'fases_progreso': fases_progreso,
        'veredicto': _veredicto(linea, proyeccion, calendario),
        'hoy': hoy,
    }

