"""Estadísticas de aprobación de la ficha."""

from flask import flash, redirect, render_template, url_for
from flask_login import login_required

from app import db
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.juicio import JuicioEvaluativo
from app.services.analisis_juicios_ficha import analizar_juicios_ficha
from app.services.cronograma import obtener_cronograma
from app.services.permisos import puede_gestionar_ficha

from . import instructor_bp


@instructor_bp.route('/fichas/<int:ficha_id>/estadisticas')
@login_required
def estadisticas(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    aprendices = Aprendiz.query.filter_by(ficha_id=ficha_id).all()
    juicios = JuicioEvaluativo.query.filter_by(ficha_id=ficha_id).all()
    return render_template('estadisticas.html', ficha=ficha, cronograma=obtener_cronograma(ficha),
                           **analizar_juicios_ficha(juicios, aprendices))
