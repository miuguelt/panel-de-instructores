"""Juicios evaluativos por aprendiz y competencia."""

from app import db
from app.models.aprendiz import Aprendiz, ESTADOS_EN_FORMACION
from app.models.ficha import Ficha
from app.models.juicio import FichaCompetenciaSeleccionada, JuicioEvaluativo
from app.services.cronograma import obtener_cronograma
from app.services.permisos import puede_gestionar_ficha
from flask import (
    flash,
    redirect,
    render_template,
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
    total_competencias_curso = len(competencias_ordenadas_juicios)
    competencias_aprobadas_curso = sum(1 for c in competencias_ordenadas_juicios if c.get('pct') == 100)
    pct_competencias_curso = (round(competencias_aprobadas_curso / total_competencias_curso * 100, 1)
                              if total_competencias_curso else 0.0)

    return render_template('juicios.html', ficha=ficha, estadisticas=estadisticas, 
                           aprendices_stats=aprendices_stats, cronograma=obtener_cronograma(ficha),
                           pct_global_juicios=pct_global_juicios,
                           competencias_summary=competencias_ordenadas_juicios,
                           total_competencias_curso=total_competencias_curso,
                           competencias_aprobadas_curso=competencias_aprobadas_curso,
                           pct_competencias_curso=pct_competencias_curso,
                           instructores_resumen=instructores_ordenados,
                           rango_aprobacion=rango_aprobacion,
                           primera_evaluacion=primera_evaluacion,
                           ultima_evaluacion=ultima_evaluacion,
                           recomendaciones_juicios=recomendaciones_juicios,
                           auditoria_duracion=auditoria_duracion)
