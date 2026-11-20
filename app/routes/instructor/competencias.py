"""Selección y programación de competencias de la ficha."""

from app import db
from app.models.ficha import Ficha
from app.models.juicio import FichaCompetenciaSeleccionada, JuicioEvaluativo
from app.services.permisos import puede_gestionar_ficha
from datetime import datetime
from flask import jsonify, request
from flask_login import current_user, login_required

from . import (  # noqa: E402
    instructor_bp,
)


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
