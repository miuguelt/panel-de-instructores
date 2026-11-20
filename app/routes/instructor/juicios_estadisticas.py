"""Juicios evaluativos, competencias seleccionadas y estadísticas."""

from app import db
from app.models.aprendiz import Aprendiz, ESTADOS_EN_FORMACION
from app.models.ficha import Ficha
from app.models.juicio import FichaCompetenciaSeleccionada, JuicioEvaluativo
from app.services.cronograma import obtener_cronograma
from app.services.permisos import puede_gestionar_ficha
from datetime import datetime
from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from . import (  # noqa: E402
    instructor_bp,
)


@instructor_bp.route('/fichas/<int:ficha_id>/juicios')
@login_required
def juicios(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    # Estadísticas globales. La vista recorre `todos` varias veces leyendo
    # `j.aprendiz`, asi que se carga la relacion de una vez: sin joinedload
    # cada aprendiz distinto dispara un SELECT extra al construir la tabla.
    todos = (
        JuicioEvaluativo.query
        .options(joinedload(JuicioEvaluativo.aprendiz))
        .join(Aprendiz, JuicioEvaluativo.aprendiz_id == Aprendiz.id)
        .filter(
            JuicioEvaluativo.ficha_id == ficha_id,
            Aprendiz.estado.in_(ESTADOS_EN_FORMACION),
        )
        .all()
    )

    _tipo_prioridad = {'tecnica': 0, 'transversal': 1, 'ingles': 2}
    estadisticas = {
        'total': 0, 'aprobados': 0, 'por_evaluar': 0,
        'tecnica': 0, 'transversal': 0, 'ingles': 0,
    }
    aprendices_dict = {}
    competencias_summary = {}
    instructores_resumen = {}
    rango_aprobacion = {'100%': 0, '75-99%': 0, '50-74%': 0, '25-49%': 0, '0-24%': 0}
    primera_evaluacion = None
    ultima_evaluacion = None

    for j in todos:
        juicio_upper = j.juicio.upper() if j.juicio else ''
        es_aprobado_global = bool(j.juicio and 'APROBADO' in juicio_upper)
        es_aprobado_comp = es_aprobado_global and 'AUN NO' not in juicio_upper
        tipo = j.tipo_competencia or 'tecnica'
        func = j.funcionario_registro or 'Sin registro'

        estadisticas['total'] += 1
        if es_aprobado_global:
            estadisticas['aprobados'] += 1
        if not j.juicio or 'EVALUAR' in juicio_upper:
            estadisticas['por_evaluar'] += 1
        if tipo in estadisticas:
            estadisticas[tipo] += 1

        if j.aprendiz_id not in aprendices_dict:
            aprendices_dict[j.aprendiz_id] = {
                'aprendiz': j.aprendiz,
                'total': 0, 'aprobados': 0,
                'tecnica': 0, 'tecnica_aprobada': 0,
                'transversal': 0, 'transversal_aprobada': 0,
                'ingles': 0, 'ingles_aprobada': 0,
            }
        datos = aprendices_dict[j.aprendiz_id]
        datos['total'] += 1
        if es_aprobado_global:
            datos['aprobados'] += 1
        datos[tipo] += 1
        if es_aprobado_global:
            datos[f"{tipo}_aprobada"] += 1
        if j.funcionario_registro:
            datos.setdefault('evaluadores', set()).add(j.funcionario_registro)

        comp = j.competencia or 'Sin nombre'
        if comp not in competencias_summary:
            competencias_summary[comp] = {
                'nombre': comp, 'tipo': tipo,
                'total': 0, 'aprobados': 0, 'pendientes': 0,
                'detalles': [],
            }
        competencias_summary[comp]['total'] += 1
        if es_aprobado_comp:
            competencias_summary[comp]['aprobados'] += 1
        else:
            competencias_summary[comp]['pendientes'] += 1
        competencias_summary[comp]['detalles'].append({
            'documento': j.aprendiz.documento if j.aprendiz else '-',
            'nombre': f"{j.aprendiz.apellidos} {j.aprendiz.nombre}" if j.aprendiz else '-',
            'rap': j.resultado_aprendizaje or '-',
            'estado': 'APROBADO' if es_aprobado_comp else 'POR EVALUAR',
            'fecha': j.fecha_juicio.strftime('%d/%m/%Y') if j.fecha_juicio else '-',
            'evaluador': j.funcionario_registro or '-',
        })

        if func not in instructores_resumen:
            instructores_resumen[func] = {'total': 0, 'aprobados': 0, 'pendientes': 0}
        instructores_resumen[func]['total'] += 1
        if es_aprobado_comp:
            instructores_resumen[func]['aprobados'] += 1
        else:
            instructores_resumen[func]['pendientes'] += 1

        if j.fecha_juicio:
            if primera_evaluacion is None or j.fecha_juicio < primera_evaluacion:
                primera_evaluacion = j.fecha_juicio
            if ultima_evaluacion is None or j.fecha_juicio > ultima_evaluacion:
                ultima_evaluacion = j.fecha_juicio

    for d in aprendices_dict.values():
        d['pct_total'] = round((d['aprobados'] / d['total'] * 100)) if d['total'] > 0 else 0
        d['pct_tecnica'] = round((d['tecnica_aprobada'] / d['tecnica'] * 100)) if d['tecnica'] > 0 else 0
        d['pct_transversal'] = round((d['transversal_aprobada'] / d['transversal'] * 100)) if d['transversal'] > 0 else 0
        d['pct_ingles'] = round((d['ingles_aprobada'] / d['ingles'] * 100)) if d['ingles'] > 0 else 0
        if 'evaluadores' in d:
            d['evaluadores'] = sorted(d['evaluadores'])
        pct = d['pct_total']
        if pct == 100:
            rango_aprobacion['100%'] += 1
        elif pct >= 75:
            rango_aprobacion['75-99%'] += 1
        elif pct >= 50:
            rango_aprobacion['50-74%'] += 1
        elif pct >= 25:
            rango_aprobacion['25-49%'] += 1
        else:
            rango_aprobacion['0-24%'] += 1

    aprendices_stats = sorted(aprendices_dict.values(), key=lambda x: x['aprendiz'].apellidos)
    pct_global_juicios = round((estadisticas['aprobados'] / estadisticas['total'] * 100)) if estadisticas['total'] > 0 else 0

    # Cargar competencias seleccionadas por instructores
    seleccionadas_list = FichaCompetenciaSeleccionada.query.options(
        joinedload(FichaCompetenciaSeleccionada.instructor)
    ).filter_by(ficha_id=ficha_id).all()

    seleccionadas_map = {
        s.competencia: {
            'instructor_id': s.instructor_id,
            'nombre': s.instructor.nombre if s.instructor else 'Instructor',
            'es_propia': (s.instructor_id == current_user.id),
            'fecha_seleccion': s.fecha_seleccion.strftime('%d/%m/%Y %H:%M') if s.fecha_seleccion else None
        }
        for s in seleccionadas_list
    }

    for comp in competencias_summary.values():
        comp['pct'] = round((comp['aprobados'] / comp['total'] * 100)) if comp['total'] > 0 else 0
        comp['detalles'] = sorted(comp['detalles'], key=lambda x: x['nombre'])
        comp['seleccionada_por'] = seleccionadas_map.get(comp['nombre'])
        comp['esta_seleccionada'] = comp['seleccionada_por'] is not None

    competencias_ordenadas_juicios = sorted(
        competencias_summary.values(),
        key=lambda x: (
            0 if x['aprobados'] > 0 else 1,
            -x['pct'],
            -x['aprobados'],
            _tipo_prioridad.get(x.get('tipo') or 'tecnica', 99),
            -x['total'],
        ),
    )

    for func in instructores_resumen.values():
        func['pct'] = round((func['aprobados'] / func['total'] * 100)) if func['total'] > 0 else 0

    instructores_ordenados = sorted(instructores_resumen.items(), key=lambda x: x[1]['total'], reverse=True)

    from app.services.recomendaciones import obtener_recomendaciones_ficha, CAT_JUICIOS
    recomendaciones_juicios = obtener_recomendaciones_ficha(
        ficha_id, instructor_id=current_user.id, categorias={CAT_JUICIOS},
    )

    from app.services.programacion_competencias import (
        calcular_fechas_competencias_y_raps,
        auditar_duracion_programa,
    )
    competencias_ordenadas_juicios = calcular_fechas_competencias_y_raps(ficha, competencias_ordenadas_juicios)
    auditoria_duracion = auditar_duracion_programa(ficha)

    return render_template('juicios.html', ficha=ficha, estadisticas=estadisticas, 
                           aprendices_stats=aprendices_stats, cronograma=obtener_cronograma(ficha),
                           pct_global_juicios=pct_global_juicios,
                           competencias_summary=competencias_ordenadas_juicios,
                           instructores_resumen=instructores_ordenados,
                           rango_aprobacion=rango_aprobacion,
                           primera_evaluacion=primera_evaluacion,
                           ultima_evaluacion=ultima_evaluacion,
                           recomendaciones_juicios=recomendaciones_juicios,
                           auditoria_duracion=auditoria_duracion)


@instructor_bp.route('/fichas/<int:ficha_id>/competencias/toggle', methods=['POST'])
@login_required
def toggle_competencia_seleccionada(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        return jsonify({'success': False, 'error': 'No tienes permisos en esta ficha.'}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('competencia', ''), str):
        return jsonify(success=False, error='Envíe la competencia como texto dentro de un objeto JSON.'), 400
    competencia_nombre = data.get('competencia', '').strip()
    if not competencia_nombre:
        return jsonify({'success': False, 'error': 'Nombre de competencia requerido.'}), 400

    sel = FichaCompetenciaSeleccionada.query.filter_by(
        ficha_id=ficha_id,
        competencia=competencia_nombre
    ).first()

    if sel:
        if sel.instructor_id == current_user.id:
            # Deseleccionar si es del mismo instructor
            db.session.delete(sel)
            db.session.commit()
            return jsonify({
                'success': True,
                'action': 'deselected',
                'competencia': competencia_nombre,
                'esta_seleccionada': False,
                'seleccionada_por': None
            })
        else:
            # Reasignar a este instructor
            sel.instructor_id = current_user.id
            sel.fecha_seleccion = datetime.utcnow()
            db.session.commit()
            return jsonify({
                'success': True,
                'action': 'selected',
                'competencia': competencia_nombre,
                'esta_seleccionada': True,
                'seleccionada_por': {
                    'instructor_id': current_user.id,
                    'nombre': current_user.nombre,
                    'es_propia': True,
                    'fecha_seleccion': sel.fecha_seleccion.strftime('%d/%m/%Y %H:%M')
                }
            })
    else:
        # Crear nueva selección
        nueva_sel = FichaCompetenciaSeleccionada(
            ficha_id=ficha_id,
            competencia=competencia_nombre,
            instructor_id=current_user.id
        )
        db.session.add(nueva_sel)
        db.session.commit()
        return jsonify({
            'success': True,
            'action': 'selected',
            'competencia': competencia_nombre,
            'esta_seleccionada': True,
            'seleccionada_por': {
                'instructor_id': current_user.id,
                'nombre': current_user.nombre,
                'es_propia': True,
                'fecha_seleccion': nueva_sel.fecha_seleccion.strftime('%d/%m/%Y %H:%M')
            }
        })


@instructor_bp.route('/fichas/<int:ficha_id>/competencias/programar', methods=['POST'])
@login_required
def programar_competencia(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        return jsonify({'success': False, 'error': 'No tienes permisos en esta ficha.'}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('competencia', ''), str):
        return jsonify(success=False, error='Envíe la competencia como texto dentro de un objeto JSON.'), 400
    competencia_nombre = data.get('competencia', '').strip()
    if not competencia_nombre:
        return jsonify({'success': False, 'error': 'Nombre de competencia requerido.'}), 400

    limpiar = data.get('limpiar', False)
    if type(limpiar) is not bool:
        return jsonify(success=False, error='La opción de restablecer la programación debe ser verdadera o falsa.'), 400
    from app.services.programacion_competencias import (
        guardar_programacion_competencia,
        limpiar_programacion_competencia,
        calcular_fechas_competencias_y_raps,
        _parsear_fecha,
    )

    if limpiar:
        limpiar_programacion_competencia(ficha_id, competencia_nombre)
    else:
        f_ini_str = data.get('fecha_inicio')
        f_fin_str = data.get('fecha_fin')
        f_ini = _parsear_fecha(f_ini_str)
        f_fin = _parsear_fecha(f_fin_str)
        if ((f_ini_str not in (None, '') and not f_ini)
                or (f_fin_str not in (None, '') and not f_fin)):
            return jsonify(success=False, error='Ingrese fechas válidas para programar la competencia.'), 400
        if f_ini and f_fin and f_fin < f_ini:
            return jsonify({'success': False, 'error': 'La fecha de finalización no puede ser anterior a la de inicio.'}), 400

        try:
            guardar_programacion_competencia(
                ficha_id=ficha_id,
                competencia_nombre=competencia_nombre,
                fecha_inicio=f_ini,
                fecha_fin=f_fin,
                instructor_id=current_user.id,
            )
        except ValueError:
            return jsonify({'success': False, 'error': 'Los parámetros de fechas para la competencia no son válidos.'}), 400

    juicios_comp = JuicioEvaluativo.query.filter_by(ficha_id=ficha_id, competencia=competencia_nombre).all()
    raps_unicos = []
    for j in juicios_comp:
        if j.resultado_aprendizaje and j.resultado_aprendizaje not in raps_unicos:
            raps_unicos.append(j.resultado_aprendizaje)

    dummy_summary = [{
        'nombre': competencia_nombre,
        'detalles': [{'rap': r} for r in raps_unicos],
    }]
    recalculado = calcular_fechas_competencias_y_raps(ficha, dummy_summary)[0]

    return jsonify({
        'success': True,
        'competencia': competencia_nombre,
        'fecha_inicio': recalculado.get('fecha_inicio'),
        'fecha_fin': recalculado.get('fecha_fin'),
        'fecha_inicio_texto': recalculado.get('fecha_inicio_texto'),
        'fecha_fin_texto': recalculado.get('fecha_fin_texto'),
        'fecha_inicio_estimada_texto': recalculado.get('fecha_inicio_estimada_texto'),
        'fecha_fin_estimada_texto': recalculado.get('fecha_fin_estimada_texto'),
        'es_manual': recalculado.get('es_programacion_manual'),
        'instructor_programo': recalculado.get('instructor_programo'),
        'horas': recalculado.get('horas'),
        'horas_programa': recalculado.get('horas_programa'),
        'horas_planeadas': recalculado.get('horas_planeadas'),
        'raps_distribucion': recalculado.get('raps_distribucion', []),
        'raps_tiempo': recalculado.get('raps_distribucion', []),
    })


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
