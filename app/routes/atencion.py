from flask import Blueprint, render_template, request, flash, redirect, url_for, abort, jsonify, current_app
from flask_login import current_user, login_required
from app import db
from app.models.ficha import Ficha
from app.models.aprendiz import Aprendiz
from app.models.atencion import TurnoAtencion
from app.services.atencion_service import AtencionService
from app.models.observador import NotaObservador, TIPO_POSITIVA
from app.helpers import utc_now
from sqlalchemy.exc import SQLAlchemyError
from datetime import date

from app.services.permisos import puede_gestionar_ficha

atencion_bp = Blueprint('atencion', __name__, template_folder='../templates/instructor')

def _verificar_acceso(ficha_id):
    if not current_user.is_authenticated:
        abort(401)
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        abort(404)
    if not puede_gestionar_ficha(ficha):
        abort(403)
    return ficha

@atencion_bp.route('/fichas/<int:ficha_id>/fila-atencion', methods=['GET'])
@login_required
def fila_atencion(ficha_id):
    ficha = _verificar_acceso(ficha_id)
    turnos = AtencionService.obtener_fila(ficha_id)
    return render_template('fila_atencion.html', ficha=ficha, turnos=turnos)

@atencion_bp.route('/fichas/<int:ficha_id>/fila-atencion/<int:turno_id>/estado', methods=['POST'])
@login_required
def cambiar_estado(ficha_id, turno_id):
    ficha = _verificar_acceso(ficha_id)
    nuevo_estado = request.form.get('estado')
    
    if nuevo_estado not in ['en_atencion', 'atendido', 'cancelado', 'ausente']:
        flash('Estado no válido.', 'error')
        return redirect(url_for('atencion.fila_atencion', ficha_id=ficha_id))
        
    turno = TurnoAtencion.query.filter_by(id=turno_id, ficha_id=ficha_id).first()
    if not turno:
        flash('Turno no encontrado.', 'error')
        return redirect(url_for('atencion.fila_atencion', ficha_id=ficha_id))
    try:
        turno = AtencionService.cambiar_estado(turno.id, nuevo_estado, confirmar=False)
        if nuevo_estado == 'atendido':
            minutos = 0
            if turno.atendido_en and turno.completado_en:
                minutos = int((turno.completado_en - turno.atendido_en).total_seconds() / 60)
            descripcion = 'Atención personalizada brindada al aprendiz.'
            if turno.motivo:
                descripcion += f' Motivo reportado: {turno.motivo}.'
            if minutos > 0:
                descripcion += f' Duración aproximada: {minutos} minutos.'
            db.session.add(NotaObservador(
                ficha_id=ficha.id, aprendiz_id=turno.aprendiz_id,
                instructor_id=current_user.id, tipo=TIPO_POSITIVA,
                categoria='compromiso', descripcion=descripcion,
                fecha=date.today(), creada_en=utc_now(),
            ))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('No fue posible actualizar el turno de atención %s.', turno_id)
        flash('No fue posible actualizar el turno. Se conserva el estado anterior; vuelva a intentarlo.', 'error')
        return redirect(url_for('atencion.fila_atencion', ficha_id=ficha_id))

    if nuevo_estado == 'atendido':
        flash('Atención finalizada y registrada en el observador del aprendiz.', 'success')
    else:
        flash(f'Estado del turno cambiado a {nuevo_estado}.', 'success')
        
    return redirect(url_for('atencion.fila_atencion', ficha_id=ficha_id))

@atencion_bp.route('/fichas/<int:ficha_id>/fila-atencion/estado-actual', methods=['GET'])
@login_required
def estado_actual(ficha_id):
    ficha = _verificar_acceso(ficha_id)
    turnos = AtencionService.obtener_fila(ficha_id)
    return jsonify({
        'total': len(turnos),
        'esperando': sum(1 for t in turnos if t.estado == 'esperando'),
        'en_atencion': sum(1 for t in turnos if t.estado == 'en_atencion'),
        'turnos': [
            {
                'id': t.id,
                'aprendiz_id': t.aprendiz_id,
                'nombre': t.aprendiz.nombre_completo,
                'documento': t.aprendiz.documento,
                'hora': t.creado_en.strftime('%I:%M %p'),
                'motivo': t.motivo or '',
                'estado': t.estado
            }
            for t in turnos
        ]
    })
