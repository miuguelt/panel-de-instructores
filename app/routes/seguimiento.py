from datetime import datetime, timedelta
import io

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for, session
from flask_login import current_user, login_required

from app import db
from app.models.alertas import (
    Alerta,
    ConfiguracionAlertas,
    ConfiguracionAlertasComite,
    Notificacion,
)
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.services.alertas import (
    actualizar_alertas_ficha,
    asegurar_resumen_semanal,
    crear_plan_mejoramiento,
    cumplir_plan_mejoramiento,
    ejecutar_revision_automatica,
    obtener_casos,
    obtener_config_comite,
    obtener_indicadores_caso,
    obtener_linea_tiempo,
    registrar_notificacion,
    vencer_planes_pendientes,
)
from app.services.permisos import puede_gestionar_ficha
from app.models.alertas import PlanMejoramiento


seguimiento_bp = Blueprint('seguimiento', __name__, template_folder='../templates/instructor')
aprendiz_seguimiento_bp = Blueprint('aprendiz_seguimiento', __name__, template_folder='../templates/instructor')


def _ficha_autorizada(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        return None
    return ficha


def _notificacion_destino(url_fallback=None):
    return request.form.get('redirect_url') or request.args.get('redirect_url') or url_fallback


@seguimiento_bp.route('/notificaciones')
@login_required
def notificaciones_instructor():
    notificaciones = Notificacion.query.filter_by(
        destinatario_tipo='instructor', destinatario_id=current_user.id
    ).order_by(Notificacion.fecha_creada.desc()).limit(100).all()
    return render_template('notificaciones.html', notificaciones=notificaciones, aprendiz=False)


@seguimiento_bp.route('/notificaciones/<int:notificacion_id>/leer', methods=['POST'])
@login_required
def marcar_notificacion_instructor(notificacion_id):
    notificacion = db.session.get(Notificacion, notificacion_id)
    if not notificacion or not (
        notificacion.destinatario_tipo == 'instructor'
        and notificacion.destinatario_id == current_user.id
    ):
        flash('Notificación no encontrada.', 'error')
        return redirect(url_for('seguimiento.notificaciones_instructor'))
    notificacion.leida = True
    notificacion.leida_en = datetime.utcnow()
    db.session.commit()
    destino = _notificacion_destino(url_for('seguimiento.notificaciones_instructor'))
    return redirect(destino or url_for('seguimiento.notificaciones_instructor'))


@seguimiento_bp.route('/notificaciones/leer-todas', methods=['POST'])
@login_required
def marcar_todas_instructor():
    Notificacion.query.filter_by(
        destinatario_tipo='instructor', destinatario_id=current_user.id, leida=False
    ).update({'leida': True, 'leida_en': datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    return redirect(url_for('seguimiento.notificaciones_instructor'))


@seguimiento_bp.route('/fichas/<int:ficha_id>/casos-seguimiento')
@login_required
def casos_seguimiento(ficha_id):
    # Build the decision workspace from persisted alert, plan and evidence data.
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    actualizar_alertas_ficha(ficha_id)
    vencer_planes_pendientes()
    asegurar_resumen_semanal(ficha)
    ahora = datetime.utcnow()
    planes = PlanMejoramiento.query.filter_by(ficha_id=ficha_id).all()
    casos = []
    for alertas in obtener_casos(ficha_id):
        aprendiz = alertas[0].aprendiz
        indicadores = obtener_indicadores_caso(aprendiz.id, ficha_id, ahora)
        planes_aprendiz = [plan for plan in planes if plan.aprendiz_id == aprendiz.id]
        casos.append({
            'aprendiz': aprendiz,
            'alertas': alertas,
            'timeline': obtener_linea_tiempo(aprendiz.id, ficha_id),
            'indicadores': indicadores,
            'planes': planes_aprendiz,
            'prioridad': 'roja' if any(alerta.nivel == 'roja' for alerta in alertas) else 'amarilla',
            'estado': 'escalada_comite' if any(
                alerta.estado == 'escalada_comite' for alerta in alertas
            ) else 'activa',
        })
    alertas_abiertas = [alerta for caso in casos for alerta in caso['alertas']]
    resumen = {
        'casos': len(casos),
        'prioritarios': sum(caso['prioridad'] == 'roja' for caso in casos),
        'alertas_activas': sum(alerta.estado == 'activa' for alerta in alertas_abiertas),
        'escalados': sum(alerta.estado == 'escalada_comite' for alerta in alertas_abiertas),
        'planes_pendientes': sum(plan.estado == 'pendiente' for plan in planes),
        'planes_vencidos': sum(plan.estado == 'vencido' for plan in planes),
    }
    return render_template(
        'casos_seguimiento.html',
        ficha=ficha,
        casos=casos,
        config_comite=obtener_config_comite(ficha_id),
        resumen=resumen,
        ahora=ahora,
        ultima_evaluacion=ahora,
    )


@seguimiento_bp.route('/fichas/<int:ficha_id>/alertas/config-comite', methods=['POST'])
@login_required
def configurar_alertas_comite(ficha_id):
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    try:
        config = obtener_config_comite(ficha_id)
        config.umbral_fallas_consecutivas = max(1, int(request.form.get('umbral_fallas_consecutivas', 3)))
        config.umbral_fallas_acumuladas = max(1, int(request.form.get('umbral_fallas_acumuladas', 5)))
        config.umbral_fallas_esporadicas = max(1, int(request.form.get('umbral_fallas_esporadicas', 5)))
        config.periodo_dias_esporadicas = max(30, int(request.form.get('periodo_dias_esporadicas', 90)))
        config.umbral_tareas_incumplidas = max(1, int(request.form.get('umbral_tareas_incumplidas', 3)))
        config.dias_plazo_justificacion = max(1, int(request.form.get('dias_plazo_justificacion', 2)))
        config.porcentaje_minimo_asistencia = min(
            100, max(1, int(request.form.get('porcentaje_minimo_asistencia', 75)))
        )
        config.auto_escalar_dias = max(1, int(request.form.get('auto_escalar_dias', 15)))
        config.correo_habilitado = 'correo_habilitado' in request.form
        db.session.commit()
    except (TypeError, ValueError):
        db.session.rollback()
        flash('Revisa los umbrales ingresados.', 'error')
        return redirect(url_for('seguimiento.casos_seguimiento', ficha_id=ficha_id))
    flash('Umbrales de seguimiento actualizados. Se mantienen como parámetros editables del Centro.', 'success')
    return redirect(url_for('seguimiento.casos_seguimiento', ficha_id=ficha_id))


@seguimiento_bp.route('/fichas/<int:ficha_id>/alertas/<int:alerta_id>/observacion', methods=['POST'])
@login_required
def guardar_observacion(ficha_id, alerta_id):
    ficha = _ficha_autorizada(ficha_id)
    alerta = db.session.get(Alerta, alerta_id)
    if not ficha or not alerta or alerta.ficha_id != ficha_id:
        flash('Caso no encontrado.', 'error')
        return redirect(url_for('instructor.fichas'))
    alerta.observaciones = request.form.get('observaciones', '').strip() or None
    db.session.commit()
    flash('Observación guardada en el expediente del caso.', 'success')
    return redirect(url_for('seguimiento.casos_seguimiento', ficha_id=ficha_id))


@seguimiento_bp.route('/fichas/<int:ficha_id>/alertas/<int:alerta_id>/resolver', methods=['POST'])
@login_required
def resolver_alerta(ficha_id, alerta_id):
    ficha = _ficha_autorizada(ficha_id)
    alerta = db.session.get(Alerta, alerta_id)
    if not ficha or not alerta or alerta.ficha_id != ficha_id:
        flash('Caso no encontrado.', 'error')
        return redirect(url_for('instructor.fichas'))
    if alerta.estado not in ('activa', 'escalada_comite'):
        flash('Este caso ya fue cerrado.', 'warning')
        return redirect(url_for('seguimiento.casos_seguimiento', ficha_id=ficha_id))
    era_escalada = alerta.estado == 'escalada_comite'
    alerta.estado = 'resuelta'
    alerta.fecha_resuelta = datetime.utcnow()
    alerta.resuelta_por = current_user.id
    if alerta.aprendiz:
        registrar_notificacion(
            'aprendiz', alerta.aprendiz_id,
            'Tu instructor registró que este caso quedó revisado. Si necesitas aclarar algo, puedes conversar con él o ella.',
            'caso_resuelto', f'caso-resuelto:{alerta.id}', ficha_id,
            f'/aprendiz/{ficha_id}/panel?documento={alerta.aprendiz.documento}',
        )
    db.session.commit()
    mensaje = (
        'Caso escalado cerrado como revisado por el instructor.' if era_escalada else
        'Caso marcado como revisado y resuelto por el instructor.'
        if alerta.aprendiz
        else 'Alerta general de la ficha marcada como revisada.'
    )
    flash(mensaje, 'success')
    return redirect(url_for('seguimiento.casos_seguimiento', ficha_id=ficha_id))


@seguimiento_bp.route('/fichas/<int:ficha_id>/alertas/<int:alerta_id>/escalar', methods=['POST'])
@login_required
def escalar_alerta(ficha_id, alerta_id):
    ficha = _ficha_autorizada(ficha_id)
    alerta = db.session.get(Alerta, alerta_id)
    if not ficha or not alerta or alerta.ficha_id != ficha_id:
        flash('Caso no encontrado.', 'error')
        return redirect(url_for('instructor.fichas'))
    if alerta.estado != 'activa':
        flash('Solo se pueden escalar casos que siguen activos.', 'warning')
        return redirect(url_for('seguimiento.casos_seguimiento', ficha_id=ficha_id))
    alerta.estado = 'escalada_comite'
    alerta.fecha_escalada = datetime.utcnow()
    alerta.escalada_por = current_user.id
    db.session.commit()
    flash('El caso quedó preparado como escalado al comité. El envío formal debe seguir el debido proceso del Centro.', 'warning')
    return redirect(url_for('seguimiento.casos_seguimiento', ficha_id=ficha_id))


@seguimiento_bp.route('/fichas/<int:ficha_id>/planes-mejoramiento', methods=['GET', 'POST'])
@login_required
def gestionar_planes(ficha_id):
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    if request.method == 'POST':
        aprendiz_id = request.form.get('aprendiz_id', type=int)
        actividades = request.form.get('actividades', '').strip()
        fecha_limite_str = request.form.get('fecha_limite', '').strip()
        alerta_id = request.form.get('alerta_id', type=int)
        if not aprendiz_id or not actividades:
            flash('Debes seleccionar un aprendiz y describir las actividades.', 'error')
            return redirect(url_for('seguimiento.gestionar_planes', ficha_id=ficha_id))
        aprendiz = db.session.get(Aprendiz, aprendiz_id)
        if not aprendiz or aprendiz.ficha_id != ficha_id:
            flash('El aprendiz seleccionado no pertenece a esta ficha.', 'error')
            return redirect(url_for('seguimiento.gestionar_planes', ficha_id=ficha_id))
        if alerta_id:
            alerta = db.session.get(Alerta, alerta_id)
            if not alerta or alerta.ficha_id != ficha_id or (
                alerta.aprendiz_id and alerta.aprendiz_id != aprendiz_id
            ):
                flash('La alerta seleccionada no pertenece al aprendiz ni a la ficha.', 'error')
                return redirect(url_for('seguimiento.gestionar_planes', ficha_id=ficha_id))
        fecha_limite = None
        if fecha_limite_str:
            try:
                fecha_limite = datetime.strptime(fecha_limite_str, '%Y-%m-%d')
            except ValueError:
                flash('Fecha límite no válida.', 'error')
                return redirect(url_for('seguimiento.gestionar_planes', ficha_id=ficha_id))
        crear_plan_mejoramiento(aprendiz_id, ficha_id, current_user.id, actividades, fecha_limite, alerta_id)
        flash('Plan de mejoramiento creado. El aprendiz recibirá una notificación.', 'success')
        return redirect(url_for('seguimiento.casos_seguimiento', ficha_id=ficha_id))
    planes = PlanMejoramiento.query.filter_by(ficha_id=ficha_id).order_by(
        PlanMejoramiento.fecha_creacion.desc()
    ).all()
    aprendices = sorted(ficha.aprendices if ficha else [], key=lambda ap: ap.nombre_completo.lower())
    casos_activos = [
        {'aprendiz': alertas[0].aprendiz, 'alertas': alertas}
        for alertas in obtener_casos(ficha_id)
        if alertas and alertas[0].aprendiz
    ]
    fecha_limite_sugerida = (datetime.utcnow().date() + timedelta(days=15)).isoformat()
    return render_template('planes_mejoramiento.html', ficha=ficha, planes=planes,
                           aprendices=aprendices, casos_activos=casos_activos,
                           fecha_limite_sugerida=fecha_limite_sugerida)


@seguimiento_bp.route('/fichas/<int:ficha_id>/planes/<int:plan_id>/cumplir', methods=['POST'])
@login_required
def cumplir_plan(ficha_id, plan_id):
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    plan_existente = db.session.get(PlanMejoramiento, plan_id)
    if not plan_existente or plan_existente.ficha_id != ficha_id:
        flash('Plan no encontrado para esta ficha.', 'error')
        return redirect(url_for('seguimiento.gestionar_planes', ficha_id=ficha_id))
    plan = cumplir_plan_mejoramiento(plan_id)
    if plan:
        flash('Plan de mejoramiento marcado como cumplido.', 'success')
    else:
        flash('Plan no encontrado o ya fue cerrado.', 'error')
    return redirect(url_for('seguimiento.gestionar_planes', ficha_id=ficha_id))


@seguimiento_bp.route('/fichas/<int:ficha_id>/alertas/auto-evaluar', methods=['POST'])
@login_required
def auto_evaluar_ficha(ficha_id):
    ficha = _ficha_autorizada(ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    actualizar_alertas_ficha(ficha_id)
    flash('Revisión automática ejecutada. Alertas y casos actualizados según Resolución 009 de 2024.', 'success')
    return redirect(url_for('seguimiento.casos_seguimiento', ficha_id=ficha_id))


@seguimiento_bp.route('/fichas/<int:ficha_id>/casos/<int:aprendiz_id>/reporte-comite')
@login_required
def reporte_comite(ficha_id, aprendiz_id):
    ficha = _ficha_autorizada(ficha_id)
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not ficha or not aprendiz or aprendiz.ficha_id != ficha_id:
        flash('Caso no encontrado.', 'error')
        return redirect(url_for('instructor.fichas'))
    alertas = Alerta.query.filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz_id).order_by(
        Alerta.fecha_generada.asc()
    ).all()
    timeline = obtener_linea_tiempo(aprendiz_id, ficha_id)
    return _generar_reporte_comite(ficha, aprendiz, alertas, timeline)


def _generar_reporte_comite(ficha, aprendiz, alertas, timeline):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from reportlab.lib.enums import TA_CENTER

    salida = io.BytesIO()
    doc = SimpleDocTemplate(salida, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    estilos = getSampleStyleSheet()
    estilos['Title'].alignment = TA_CENTER
    estilos['Normal'].alignment = TA_CENTER
    estilos['Italic'].alignment = TA_CENTER
    estilos['Heading2'].alignment = TA_CENTER
    elementos = [
        Paragraph(f'Borrador para Comité de Evaluación y Seguimiento', estilos['Title']),
        Paragraph(f'Ficha {ficha.codigo} · {ficha.nombre_programa}', estilos['Normal']),
        Spacer(1, 8),
        Paragraph(f'<b>Aprendiz:</b> {aprendiz.nombre_completo}<br/><b>Documento:</b> {aprendiz.documento}', estilos['Normal']),
        Spacer(1, 10),
        Paragraph('Este documento organiza evidencia para revisión humana. No constituye una sanción ni declara deserción.', estilos['Italic']),
        Spacer(1, 12),
        Paragraph('Alertas y decisiones registradas', estilos['Heading2']),
    ]
    datos_alertas = [['Fecha', 'Tipo / nivel', 'Estado', 'Detalle', 'Observaciones']]
    for alerta in alertas:
        datos_alertas.append([
            alerta.fecha_generada.strftime('%d/%m/%Y'),
            f'{alerta.tipo} · {alerta.nivel}',
            alerta.estado,
            alerta.mensaje,
            alerta.observaciones or 'Sin observaciones',
        ])
    ancho_util = doc.width
    tabla_alertas = Table(datos_alertas, colWidths=[ancho_util*0.15, ancho_util*0.15, ancho_util*0.15, ancho_util*0.35, ancho_util*0.20], repeatRows=1, hAlign='CENTER')
    tabla_alertas.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#39A900')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elementos.append(tabla_alertas)
    elementos.append(Spacer(1, 12))
    elementos.append(Paragraph('Línea de tiempo relevante', estilos['Heading2']))
    datos_timeline = [['Fecha', 'Tipo', 'Evento', 'Detalle']]
    for evento in timeline:
        datos_timeline.append([
            evento['fecha'].strftime('%d/%m/%Y'),
            evento['tipo'],
            evento['titulo'],
            evento['detalle'] + (f" · {evento['nota']}" if evento.get('nota') else ''),
        ])
    tabla_timeline = Table(datos_timeline, colWidths=[ancho_util*0.15, ancho_util*0.15, ancho_util*0.35, ancho_util*0.35], repeatRows=1, hAlign='CENTER')
    tabla_timeline.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2d8600')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elementos.append(tabla_timeline)
    doc.build(elementos)
    salida.seek(0)
    return send_file(
        salida, mimetype='application/pdf', as_attachment=True,
        download_name=f'borrador_comite_{ficha.codigo}_{aprendiz.documento}.pdf',
    )


@aprendiz_seguimiento_bp.route('/<int:ficha_id>/notificaciones')
def notificaciones_aprendiz(ficha_id):
    documento = session.get('aprendiz_documento', '') or request.args.get('documento', '').strip()
    aprendiz = Aprendiz.query.filter_by(documento=documento, ficha_id=ficha_id).first()
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha or not aprendiz:
        flash('Documento no válido para esta ficha.', 'error')
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))
    notificaciones = Notificacion.query.filter_by(
        destinatario_tipo='aprendiz', destinatario_id=aprendiz.id, ficha_id=ficha_id
    ).order_by(Notificacion.fecha_creada.desc()).limit(100).all()
    return render_template(
        'notificaciones.html', notificaciones=notificaciones, aprendiz=aprendiz,
        ficha=ficha,
    )


@aprendiz_seguimiento_bp.route('/<int:ficha_id>/notificaciones/<int:notificacion_id>/leer', methods=['POST'])
def marcar_notificacion_aprendiz(ficha_id, notificacion_id):
    documento = session.get('aprendiz_documento', '') or request.form.get('documento', '').strip()
    aprendiz = Aprendiz.query.filter_by(documento=documento, ficha_id=ficha_id).first()
    notificacion = db.session.get(Notificacion, notificacion_id)
    if not aprendiz or not notificacion or not (
        notificacion.destinatario_tipo == 'aprendiz'
        and notificacion.destinatario_id == aprendiz.id
        and notificacion.ficha_id == ficha_id
    ):
        flash('Notificación no encontrada.', 'error')
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))
    notificacion.leida = True
    notificacion.leida_en = datetime.utcnow()
    db.session.commit()
    return redirect(url_for('aprendiz_seguimiento.notificaciones_aprendiz', ficha_id=ficha_id))


@aprendiz_seguimiento_bp.route('/<int:ficha_id>/notificaciones/leer-todas', methods=['POST'])
def marcar_todas_aprendiz(ficha_id):
    documento = session.get('aprendiz_documento', '') or request.form.get('documento', '').strip()
    aprendiz = Aprendiz.query.filter_by(documento=documento, ficha_id=ficha_id).first()
    if not aprendiz:
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))
    Notificacion.query.filter_by(
        destinatario_tipo='aprendiz', destinatario_id=aprendiz.id,
        ficha_id=ficha_id, leida=False,
    ).update({'leida': True, 'leida_en': datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    return redirect(url_for('aprendiz_seguimiento.notificaciones_aprendiz', ficha_id=ficha_id))
