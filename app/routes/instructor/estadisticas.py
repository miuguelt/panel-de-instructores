"""Estadísticas de aprobación de la ficha."""

from app import db
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.juicio import JuicioEvaluativo
from app.services.cronograma import obtener_cronograma
from app.services.permisos import puede_gestionar_ficha
from flask import (
    flash,
    redirect,
    render_template,
    url_for,
)
from flask_login import login_required

from . import (  # noqa: E402
    instructor_bp,
)


@instructor_bp.route('/fichas/<int:ficha_id>/estadisticas')
@login_required
def estadisticas(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    # 1. Estadísticas de estado de los aprendices (el desglose incluye a todos
    # porque su propósito es mostrar cuántos siguen o salieron de la formación).
    todos_los_aprendices = Aprendiz.query.filter_by(ficha_id=ficha_id).all()
    estados = {}
    total_aprendices = len(todos_los_aprendices)
    for a in todos_los_aprendices:
        estados[a.estado] = estados.get(a.estado, 0) + 1

    # El resto de métricas académicas solo considera a quienes están en formación.
    aprendices = [a for a in todos_los_aprendices if a.en_formacion]
    ids_en_formacion = {a.id for a in aprendices}

    # 2. Historial de juicios por instructor
    # Traemos todos los juicios y relacionamos con instructores si es posible.
    # Dado que un juicio puede tener varios instructores que lo importaron (en JuicioEvaluativoInstructor),
    # o usamos el funcionario_registro de JuicioEvaluativo.
    juicios = [
        j for j in JuicioEvaluativo.query.filter_by(ficha_id=ficha_id).all()
        if j.aprendiz_id in ids_en_formacion
    ]

    # Agrupar por funcionario_registro que viene en el excel
    instructores_stats = {}
    aprendices_riesgo_dict = {}
    resultados_criticos_dict = {}
    
    total_juicios_ficha = len(juicios)
    total_aprobados_ficha = 0

    for j in juicios:
        func = j.funcionario_registro or 'Sin Registro'
        if func not in instructores_stats:
            instructores_stats[func] = {
                'total': 0, 'aprobados': 0, 'no_aprobados': 0,
                'tecnica': 0, 'transversal': 0, 'ingles': 0,
                'aprendices_evaluados': set(),
                'aprendices_aprobados': set(),
            }
        
        instructores_stats[func]['total'] += 1
        instructores_stats[func]['aprendices_evaluados'].add(j.aprendiz_id)
        es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
        if es_aprobado:
            instructores_stats[func]['aprobados'] += 1
            instructores_stats[func]['aprendices_aprobados'].add(j.aprendiz_id)
            total_aprobados_ficha += 1
        else:
            instructores_stats[func]['no_aprobados'] += 1
            
            # Contabilizar para aprendices en riesgo
            if j.aprendiz_id not in aprendices_riesgo_dict:
                aprendices_riesgo_dict[j.aprendiz_id] = 0
            aprendices_riesgo_dict[j.aprendiz_id] += 1
            
            # Contabilizar para resultados críticos
            res = j.resultado_aprendizaje
            if res not in resultados_criticos_dict:
                resultados_criticos_dict[res] = 0
            resultados_criticos_dict[res] += 1
            
        tipo = j.tipo_competencia or 'tecnica'
        instructores_stats[func][tipo] += 1
        
    # Convertir sets a conteos para serialización en template
    for func, stats in instructores_stats.items():
        stats['total_aprendices'] = len(stats['aprendices_evaluados'])
        stats['total_aprendices_aprobados'] = len(stats['aprendices_aprobados'])
        del stats['aprendices_evaluados']
        del stats['aprendices_aprobados']
        
    # Obtener los top 5 aprendices en riesgo
    aprendices_dict = {a.id: a for a in aprendices}
    top_aprendices_riesgo = []
    for a_id, count in sorted(aprendices_riesgo_dict.items(), key=lambda x: x[1], reverse=True)[:10]:
        ap = aprendices_dict.get(a_id)
        if ap:
            top_aprendices_riesgo.append({
                'aprendiz': ap,
                'pendientes': count
            })
            
    # Obtener los top 5 resultados críticos
    top_resultados = sorted(resultados_criticos_dict.items(), key=lambda x: x[1], reverse=True)[:5]
    
    pct_aprobacion_global = round((total_aprobados_ficha / total_juicios_ficha * 100) if total_juicios_ficha > 0 else 0)

    # ---- NUEVAS ESTADÍSTICAS ----

    # 3. Estadísticas por competencia
    competencias_stats = {}
    
    for j in juicios:
        comp = j.competencia or 'Sin nombre'
        if comp not in competencias_stats:
            competencias_stats[comp] = {
                'nombre': comp,
                'tipo': j.tipo_competencia or 'tecnica',
                'total': 0, 'aprobados': 0, 'aprendices': set(),
                'resultados': set(),
                'aprendices_aprobados_ids': set()
            }
        competencias_stats[comp]['total'] += 1
        competencias_stats[comp]['aprendices'].add(j.aprendiz_id)
        if j.resultado_aprendizaje:
            competencias_stats[comp]['resultados'].add(j.resultado_aprendizaje)
            
        if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper():
            competencias_stats[comp]['aprobados'] += 1
            competencias_stats[comp]['aprendices_aprobados_ids'].add(j.aprendiz_id)

    for comp in competencias_stats.values():
        comp['pct'] = round((comp['aprobados'] / comp['total'] * 100)) if comp['total'] > 0 else 0
        comp['num_aprendices'] = len(comp['aprendices'])
        comp['pendientes'] = comp['total'] - comp['aprobados']
        
        comp['resultados_lista'] = sorted(list(comp['resultados']))
        
        aprendices_aprob_objs = []
        for a_id in comp['aprendices_aprobados_ids']:
            ap = aprendices_dict.get(a_id)
            if ap:
                aprendices_aprob_objs.append({
                    'id': ap.id,
                    'nombre_completo': f"{ap.nombre} {ap.apellidos}",
                    'documento': ap.documento
                })
        comp['aprendices_aprobados_lista'] = sorted(aprendices_aprob_objs, key=lambda x: x['nombre_completo'])
        
        del comp['aprendices']
        del comp['resultados']
        del comp['aprendices_aprobados_ids']

    competencias_ordenadas = sorted(competencias_stats.values(), key=lambda x: (-x['pendientes'], x['pct']))

    # 4. Timeline de evaluaciones por mes
    timeline = {}
    for j in juicios:
        if j.fecha_juicio:
            mes = j.fecha_juicio.strftime('%Y-%m')
            if mes not in timeline:
                timeline[mes] = {'total': 0, 'aprobados': 0}
            timeline[mes]['total'] += 1
            if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper():
                timeline[mes]['aprobados'] += 1
    timeline_ordenado = sorted(timeline.items())

    # 5. Resumen general
    aprendices_ids = {j.aprendiz_id for j in juicios}
    aprendices_con_todos = 0
    aprendices_sin_ninguno = 0
    for a_id in aprendices_ids:
        juicios_ap = [j for j in juicios if j.aprendiz_id == a_id]
        total_ap = len(juicios_ap)
        aprobados_ap = sum(1 for j in juicios_ap if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
        if aprobados_ap == total_ap:
            aprendices_con_todos += 1
        elif aprobados_ap == 0:
            aprendices_sin_ninguno += 1

    juicios_transversales = [j for j in juicios if j.tipo_competencia == 'transversal']
    transversales_aprobados = sum(1 for j in juicios_transversales if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
    transversales_faltantes = len(juicios_transversales) - transversales_aprobados

    juicios_ingles = [j for j in juicios if j.tipo_competencia == 'ingles']
    ingles_aprobados = sum(1 for j in juicios_ingles if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
    ingles_faltantes = len(juicios_ingles) - ingles_aprobados

    resumen = {
        'total_aprendices_con_juicios': len(aprendices_ids),
        'total_competencias': len(competencias_stats),
        'total_resultados': len({j.resultado_aprendizaje for j in juicios if j.resultado_aprendizaje}),
        'aprendices_con_todos': aprendices_con_todos,
        'aprendices_sin_ninguno': aprendices_sin_ninguno,
        'promedio_juicios_por_aprendiz': round(total_juicios_ficha / len(aprendices_ids), 1) if aprendices_ids else 0,
        'transversales_vistas': len(juicios_transversales),
        'transversales_faltantes': transversales_faltantes,
        'ingles_aprobados': ingles_aprobados,
        'ingles_faltantes': ingles_faltantes,
    }

    # 6. Distribución de aprobación entre aprendices
    distribucion_aprobacion = {'0-25': 0, '26-50': 0, '51-75': 0, '76-99': 0, '100': 0}
    for a_id in aprendices_ids:
        juicios_ap = [j for j in juicios if j.aprendiz_id == a_id]
        total_ap = len(juicios_ap)
        if total_ap == 0:
            continue
        aprobados_ap = sum(1 for j in juicios_ap if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
        pct_ap = round(aprobados_ap / total_ap * 100)
        if pct_ap == 100:
            distribucion_aprobacion['100'] += 1
        elif pct_ap >= 76:
            distribucion_aprobacion['76-99'] += 1
        elif pct_ap >= 51:
            distribucion_aprobacion['51-75'] += 1
        elif pct_ap >= 26:
            distribucion_aprobacion['26-50'] += 1
        else:
            distribucion_aprobacion['0-25'] += 1

    # 7. Top 3 mejores competencias (más aprobadas)
    mejores_competencias = sorted(competencias_stats.values(), key=lambda x: x['pct'], reverse=True)[:5]
    peores_competencias = sorted(competencias_stats.values(), key=lambda x: x['pct'])[:5]

    return render_template(
        'estadisticas.html', 
        ficha=ficha, 
        cronograma=obtener_cronograma(ficha),
        estados=estados,
        total_aprendices=total_aprendices,
        instructores_stats=instructores_stats,
        top_aprendices=top_aprendices_riesgo,
        top_resultados=top_resultados,
        pct_global=pct_aprobacion_global,
        competencias_stats=competencias_ordenadas,
        timeline=timeline_ordenado,
        resumen=resumen,
        distribucion_aprobacion=distribucion_aprobacion,
        mejores_competencias=mejores_competencias,
        peores_competencias=peores_competencias,
    )
