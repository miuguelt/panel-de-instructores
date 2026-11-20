"""Entregas, calificación, prórrogas y evidencias de planes de mejoramiento."""

from app import db
from app.models.alertas import PlanMejoramiento
from app.models.aprendiz import Aprendiz, ESTADOS_EN_FORMACION
from app.models.insignia import Insignia, InsigniaOtorgada
from app.models.observador import NotaObservador, TIPO_NEGATIVA
from app.models.tarea import Entrega, Tarea
from app.services.alertas import actualizar_alertas_ficha, notificar_calificacion
from app.services.archivos import ArchivoService, nombre_original_desde_ruta, resolver_archivo_subido
from app.services.permisos import puede_gestionar_ficha, puede_gestionar_tarea, puede_ver_tarea
from app.services.tareas import (
    conceder_prorroga_tarea,
    obtener_planes_de_tarea,
    obtener_prorrogas_tarea,
    revocar_prorroga_tarea,
)
from datetime import date, datetime
from flask import (
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from . import (  # noqa: E402
    _actualizar_resumenes_despues_de_evaluar,
    _validar_calificacion,
    instructor_bp,
)


@instructor_bp.route('/tareas/<int:tarea_id>/entregas')
@login_required
def ver_entregas(tarea_id):
    tarea = db.session.get(Tarea, tarea_id)
    if not tarea:
        flash('Tarea no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    ficha = tarea.ficha
    if not puede_gestionar_ficha(ficha) or not puede_ver_tarea(tarea):
        flash('No tienes permiso para ver esta tarea.', 'error')
        return redirect(url_for('instructor.fichas'))

    entregas = (
        Entrega.query
        .join(Tarea, Entrega.tarea_id == Tarea.id)
        .join(Aprendiz, Entrega.aprendiz_id == Aprendiz.id)
        .filter(
            Entrega.tarea_id == tarea.id,
            Tarea.ficha_id == ficha.id,
            Aprendiz.ficha_id == ficha.id,
        )
        .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
        .all()
    )
    # La restricción única impide duplicados nuevos. El setdefault mantiene
    # determinismo durante la transición de datos históricos ya existentes.
    entregas_map = {}
    for entrega in entregas:
        entregas_map.setdefault(entrega.aprendiz_id, entrega)
    entregas_grupo_map = {}
    for entrega in entregas:
        if entrega.grupo_id:
            entregas_grupo_map.setdefault(entrega.grupo_id, entrega)
    aprendices = Aprendiz.query_en_formacion(ficha.id).order_by(Aprendiz.apellidos).all()

    # Obtener insignias de la ficha
    otorgamientos = InsigniaOtorgada.query.join(Insignia).filter(
        Insignia.ficha_id == ficha.id
    ).order_by(InsigniaOtorgada.fecha_obtencion.desc()).all()
    
    from collections import defaultdict
    insignias_map = defaultdict(list)
    for ot in otorgamientos:
        insignias_map[ot.aprendiz_id].append(ot.insignia)

    prorrogas_map = obtener_prorrogas_tarea(tarea.id)
    planes_map = obtener_planes_de_tarea(tarea.id)

    return render_template('entregas.html', tarea=tarea, ficha=ficha,
                           aprendices=aprendices, entregas_map=entregas_map,
                           entregas_grupo_map=entregas_grupo_map,
                           insignias_map=insignias_map,
                           prorrogas_map=prorrogas_map,
                           planes_map=planes_map,
                           corte_actual=tarea.corte,
                           puede_editar_tarea=puede_gestionar_tarea(tarea))


@instructor_bp.route('/tareas/<int:tarea_id>/aprendices/<int:aprendiz_id>/prorroga', methods=['POST'])
@login_required
def gestionar_prorroga_tarea(tarea_id, aprendiz_id):
    tarea = db.session.get(Tarea, tarea_id)
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not tarea or not aprendiz or aprendiz.ficha_id != tarea.ficha_id:
        flash('Tarea o aprendiz no válidos.', 'error')
        return redirect(url_for('instructor.fichas'))

    ficha = tarea.ficha
    if not puede_gestionar_ficha(ficha) or not puede_gestionar_tarea(tarea):
        flash('No tienes permiso para gestionar prórrogas en esta tarea.', 'error')
        return redirect(url_for('instructor.ver_entregas', tarea_id=tarea_id))

    accion = request.form.get('accion', 'guardar')
    if accion == 'revocar':
        revocar_prorroga_tarea(tarea.id, aprendiz.id)
        flash(f'Prórroga revocada para {aprendiz.nombre_completo}.', 'info')
        return redirect(url_for('instructor.ver_entregas', tarea_id=tarea_id))

    nueva_fecha_str = request.form.get('nueva_fecha_limite', '').strip()
    motivo = request.form.get('motivo', '').strip() or None
    if not nueva_fecha_str:
        flash('Debes indicar una nueva fecha límite para la prórroga.', 'error')
        return redirect(url_for('instructor.ver_entregas', tarea_id=tarea_id))

    try:
        if 'T' in nueva_fecha_str:
            nueva_fecha = datetime.strptime(nueva_fecha_str, '%Y-%m-%dT%H:%M')
        else:
            nueva_fecha = datetime.strptime(nueva_fecha_str, '%Y-%m-%d')
    except ValueError:
        flash('Formato de fecha inválido para la prórroga.', 'error')
        return redirect(url_for('instructor.ver_entregas', tarea_id=tarea_id))

    conceder_prorroga_tarea(
        tarea_id=tarea.id,
        aprendiz_id=aprendiz.id,
        instructor_id=current_user.id,
        nueva_fecha_limite=nueva_fecha,
        motivo=motivo,
    )
    flash(f'Prórroga concedida a {aprendiz.nombre_completo} hasta el {nueva_fecha.strftime("%d/%m/%Y %H:%M")}.', 'success')
    return redirect(url_for('instructor.ver_entregas', tarea_id=tarea_id))


@instructor_bp.route('/tareas/<int:tarea_id>/aprendices/<int:aprendiz_id>/anotar-observador', methods=['POST'])
@login_required
def anotar_observador_tarea(tarea_id, aprendiz_id):
    tarea = db.session.get(Tarea, tarea_id)
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not tarea or not aprendiz or aprendiz.ficha_id != tarea.ficha_id:
        flash('Tarea o aprendiz no válidos.', 'error')
        return redirect(url_for('instructor.fichas'))

    ficha = tarea.ficha
    if not puede_gestionar_ficha(ficha) or not puede_gestionar_tarea(tarea):
        flash('No tienes permiso para registrar llamados de atención en esta ficha.', 'error')
        return redirect(url_for('instructor.ver_entregas', tarea_id=tarea_id))

    descripcion = request.form.get('descripcion', '').strip()
    if not descripcion:
        descripcion = f'Incumplimiento en la entrega oportuna de la evidencia "{tarea.titulo}". No se registra entrega ni justificación en la fecha límite acordada.'

    categoria = request.form.get('categoria', 'compromiso')
    nota = NotaObservador(
        ficha_id=ficha.id,
        aprendiz_id=aprendiz.id,
        instructor_id=current_user.id,
        tipo=TIPO_NEGATIVA,
        categoria=categoria,
        descripcion=descripcion,
        fecha=date.today(),
        creada_en=datetime.utcnow(),
    )
    db.session.add(nota)
    db.session.commit()
    actualizar_alertas_ficha(ficha.id)
    flash(f'Se registró un llamado de atención en el Observador de {aprendiz.nombre_completo} por incumplimiento de evidencia.', 'warning')
    return redirect(url_for('instructor.ver_entregas', tarea_id=tarea_id))


@instructor_bp.route('/entregas/<int:entrega_id>/archivo')
@login_required
def descargar_archivo_entrega(entrega_id):
    """Descarga una evidencia vinculada al registro exacto de entrega."""
    entrega = db.session.get(Entrega, entrega_id)
    if (
        not entrega
        or not entrega.archivo_url
        or not entrega.tarea
        or not entrega.aprendiz
        or entrega.aprendiz.ficha_id != entrega.tarea.ficha_id
        or not puede_gestionar_ficha(entrega.tarea.ficha)
        or not puede_ver_tarea(entrega.tarea)
    ):
        abort(404)

    try:
        raiz, relativa, _ = resolver_archivo_subido(entrega.archivo_url)
    except FileNotFoundError:
        abort(404)

    return ArchivoService.enviar(
        raiz,
        relativa,
        nombre_descarga=(
            f'{entrega.aprendiz.documento}_evidencia_{entrega.id}_'
            f'{nombre_original_desde_ruta(entrega.archivo_url)}'
        ),
    )


@instructor_bp.route('/entregas/<int:entrega_id>/calificar', methods=['POST'])
@login_required
def calificar_entrega(entrega_id):
    entrega = db.session.get(Entrega, entrega_id)
    if not entrega or not entrega.tarea or not entrega.aprendiz:
        flash('Entrega no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    if (
        entrega.aprendiz.ficha_id != entrega.tarea.ficha_id
        or not puede_gestionar_ficha(entrega.tarea.ficha)
        or not puede_gestionar_tarea(entrega.tarea)
    ):
        flash('No tienes permiso para calificar esta entrega.', 'error')
        return redirect(url_for('instructor.fichas'))

    calificacion, error_calificacion = _validar_calificacion(
        request.form.get('calificacion')
    )
    if error_calificacion:
        flash(error_calificacion, 'error')
        return redirect(url_for('instructor.ver_entregas', tarea_id=entrega.tarea_id))
    feedback = request.form.get('feedback', '').strip()

    entrega.calificacion = calificacion or None
    entrega.feedback = feedback or None
    entrega.estado_revision = request.form.get('estado_revision', 'aprobada')
    if entrega.estado_revision not in ('aprobada', 'rechazada'):
        entrega.estado_revision = 'aprobada'
    entrega.calificada = True
    entrega.revisada_en = datetime.utcnow()
    entrega.revisada_por_id = current_user.id
    notificar_calificacion(entrega, entrega.tarea.ficha_id, commit=False)
    db.session.commit()
    errores_resumen = _actualizar_resumenes_despues_de_evaluar(entrega.tarea.ficha_id)

    flash('Calificación guardada.', 'success')
    if errores_resumen:
        flash(
            'La calificación quedó guardada, pero no se pudieron actualizar: '
            + ', '.join(errores_resumen) + '.',
            'warning',
        )
    return redirect(url_for('instructor.ver_entregas', tarea_id=entrega.tarea_id))


@instructor_bp.route('/tareas/<int:tarea_id>/entregas/evaluar-en-bloque', methods=['POST'])
@login_required
def evaluar_entregas_en_bloque(tarea_id):
    """Aplica una evaluación común a varias entregas de una misma tarea."""
    tarea = db.session.get(Tarea, tarea_id)
    if not tarea:
        flash('Tarea no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    ficha = tarea.ficha
    if not puede_gestionar_ficha(ficha) or not puede_gestionar_tarea(tarea):
        flash('No tienes permiso para evaluar estas entregas.', 'error')
        return redirect(url_for('instructor.fichas'))

    entrega_ids = set()
    for valor in request.form.getlist('entrega_ids'):
        try:
            entrega_ids.add(int(valor))
        except (TypeError, ValueError):
            continue

    calificacion, error_calificacion = _validar_calificacion(
        request.form.get('calificacion_general'), obligatoria=True
    )
    feedback = request.form.get('feedback_general', '').strip()
    estado_revision = request.form.get('estado_revision_general', 'aprobada')
    if estado_revision not in ('aprobada', 'rechazada'):
        estado_revision = 'aprobada'

    if not entrega_ids:
        flash('Selecciona al menos una entrega para evaluar.', 'error')
        return redirect(url_for('instructor.ver_entregas', tarea_id=tarea.id))
    if error_calificacion:
        flash(error_calificacion, 'error')
        return redirect(url_for('instructor.ver_entregas', tarea_id=tarea.id))

    entregas = (
        Entrega.query
        .join(Aprendiz, Entrega.aprendiz_id == Aprendiz.id)
        .filter(
            Entrega.tarea_id == tarea.id,
            Entrega.id.in_(entrega_ids),
            Aprendiz.ficha_id == ficha.id,
            Aprendiz.estado.in_(ESTADOS_EN_FORMACION),
        )
        .all()
    )
    if len(entregas) != len(entrega_ids):
        flash('Una o más entregas seleccionadas no pertenecen a esta tarea o ya no están disponibles.', 'error')
        return redirect(url_for('instructor.ver_entregas', tarea_id=tarea.id))

    ahora = datetime.utcnow()
    for entrega in entregas:
        entrega.calificacion = calificacion
        entrega.feedback = feedback or None
        entrega.estado_revision = estado_revision
        entrega.calificada = True
        entrega.revisada_en = ahora
        entrega.revisada_por_id = current_user.id
        notificar_calificacion(entrega, ficha.id, commit=False)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('No se pudieron guardar las evaluaciones masivas de la tarea %s.', tarea.id)
        flash('No se pudieron guardar las evaluaciones. Inténtalo de nuevo.', 'error')
        return redirect(url_for('instructor.ver_entregas', tarea_id=tarea.id))

    errores_resumen = _actualizar_resumenes_despues_de_evaluar(ficha.id)
    flash(
        f'Se evaluaron {len(entregas)} entrega(s) correctamente.',
        'warning' if errores_resumen else 'success',
    )
    if errores_resumen:
        flash(
            'Las evaluaciones quedaron guardadas, pero no se pudieron actualizar: '
            + ', '.join(errores_resumen) + '.',
            'warning',
        )
    return redirect(url_for('instructor.ver_entregas', tarea_id=tarea.id))


@instructor_bp.route('/planes/<int:plan_id>/evidencia')
@login_required
def descargar_evidencia_plan(plan_id):
    """Descarga la evidencia de un plan solo para instructores autorizados."""
    plan = db.session.get(PlanMejoramiento, plan_id)
    if (
        not plan or not plan.evidencia_url or not plan.ficha
        or not plan.aprendiz or plan.aprendiz.ficha_id != plan.ficha_id
        or not puede_gestionar_ficha(plan.ficha)
    ):
        abort(404)
    try:
        raiz, relativa, _ = resolver_archivo_subido(plan.evidencia_url)
    except FileNotFoundError:
        abort(404)
    return ArchivoService.enviar(
        raiz,
        relativa,
        nombre_descarga=(
            f'{plan.aprendiz.documento}_plan_{plan.id}_'
            f'{nombre_original_desde_ruta(plan.evidencia_url)}'
        ),
    )
