"""Creación, edición y eliminación de tareas de la ficha."""

from app import db
from app.models.corte import Corte
from app.models.ficha import Ficha
from app.models.ficha_instructor import FichaInstructor
from app.models.grupo import Grupo
from app.models.tarea import MODALIDAD_EVIDENCIA, Tarea
from app.services.alertas import actualizar_alertas_ficha
from app.services.archivos import ArchivoService, ErrorArchivo
from app.services.cortes import corte_actual, cortes_visibles
from app.services.permisos import puede_crear_tarea_en_corte, puede_gestionar_ficha, tareas_visibles
from app.services.ranking import actualizar_participacion_ficha
from app.services.tareas import (
    DatosTareaInvalidos,
    agrupar_tareas_por_corte_e_instructor,
    agrupar_tareas_por_instructor,
    eliminar_tarea_con_archivos,
    guardar_material_apoyo,
    leer_datos_tarea,
    obtener_tarea_gestionable,
)
from app.services.trabajos_grupales import DatosAsignacionTareaInvalidos, validar_destinatarios_tarea
from datetime import datetime
from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

from . import (  # noqa: E402
    _actualizar_indicadores_carga,
    instructor_bp,
)


@instructor_bp.route('/fichas/<int:ficha_id>/tareas', methods=['GET', 'POST'])
@login_required
def tareas(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    corte_param = request.values.get('corte_id')
    modo_todos = request.method == 'GET' and corte_param == 'todos'
    if modo_todos:
        # Vista agrupada: sin filtro de corte, el tablero separa por corte e instructor.
        corte = None
        corte_id = None
    else:
        corte_id = request.values.get('corte_id', type=int)
        if corte_id == 0:
            # «Sin corte» explícito: corte_actual(0) devolvería el corte activo.
            corte = None
            corte_id = None
        else:
            corte = corte_actual(ficha_id, corte_id=corte_id)
            if corte_id and not corte:
                flash('El corte no existe o no está compartido contigo.', 'error')
                return redirect(url_for('instructor.tareas', ficha_id=ficha_id))
            corte_id = corte.id if corte else None

    if request.method == 'POST':
        if corte and not puede_crear_tarea_en_corte(corte, ficha):
            flash(
                'Este corte es de solo lectura: está cerrado, archivado o no tienes permisos en esta ficha.',
                'error',
            )
            return redirect(url_for('instructor.tareas', ficha_id=ficha_id, corte_id=corte_id))
        try:
            datos = leer_datos_tarea(request.form)
            es_grupal, grupos_destino = validar_destinatarios_tarea(
                ficha_id,
                request.form.get('tipo_asignacion', 'individual'),
                datos['modalidad'],
                request.form.getlist('grupos_ids[]'),
            )
        except (DatosTareaInvalidos, DatosAsignacionTareaInvalidos) as exc:
            flash(str(exc), 'error')
            return redirect(url_for('instructor.tareas', ficha_id=ficha_id))

        material_url = None
        archivo_material = request.files.get('material_apoyo')
        if archivo_material and archivo_material.filename:
            try:
                material_url = guardar_material_apoyo(archivo_material, ficha_id, current_user.id)
            except ErrorArchivo as exc:
                flash(str(exc), 'error')
                return redirect(url_for('instructor.tareas', ficha_id=ficha_id))

        tarea = Tarea(
            ficha_id=ficha_id,
            instructor_id=current_user.id,
            corte_id=corte_id,
            material_apoyo_url=material_url,
            es_grupal=es_grupal,
            grupos=grupos_destino,
            **datos,
        )
        db.session.add(tarea)
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            if material_url:
                ArchivoService.eliminar(material_url)
            current_app.logger.exception('No se pudo registrar la tarea con su material.')
            flash('No fue posible registrar la tarea. Vuelva a intentarlo; el material no quedó guardado.', 'error')
            return redirect(url_for('instructor.tareas', ficha_id=ficha_id))
        _actualizar_indicadores_carga(ficha_id, corte_id=corte_id)
        flash(f'Tarea "{datos["titulo"]}" creada correctamente.', 'success')
        return redirect(url_for('instructor.tareas', ficha_id=ficha_id))

    filtro_instructor = request.args.get('filtro_instructor', 'mias')
    instructor_filtro_id = None
    ver_todas = (filtro_instructor == 'todas')
    if filtro_instructor not in ('mias', 'todas'):
        try:
            instructor_filtro_id = int(filtro_instructor)
        except ValueError:
            pass

    lista_tareas = tareas_visibles(
        ficha_id,
        corte_id=corte_id,
        ver_todas=ver_todas,
        instructor_id=instructor_filtro_id,
    ).options(
        joinedload(Tarea.creador), joinedload(Tarea.corte), selectinload(Tarea.grupos),
    ).order_by(
        Tarea.creada_en.desc()
    ).all()

    instructores_ficha = [ficha.instructor]
    for fi in ficha.instructores_asociados.options(joinedload(FichaInstructor.instructor)).all():
        if fi.instructor and fi.instructor.id != ficha.instructor_id and fi.instructor not in instructores_ficha:
            instructores_ficha.append(fi.instructor)

    cortes_lista = cortes_visibles(ficha_id).order_by(
        Corte.fecha_inicio.desc(), Corte.id.desc()
    ).all()

    now = datetime.utcnow()

    # Agrupación por instructor para el tablero
    grupos_instructor = agrupar_tareas_por_instructor(
        lista_tareas,
        current_user_id=current_user.id,
        ahora=now,
    )

    # Tablero agrupado: se activa en la vista de todos los cortes o al ver
    # las tareas de todos los instructores; separa por corte y por responsable.
    grupos = None
    if modo_todos or ver_todas:
        grupos = agrupar_tareas_por_corte_e_instructor(
            lista_tareas,
            cortes_lista,
            ahora=now,
        )

    cortes_editables = [c for c in cortes_lista if puede_crear_tarea_en_corte(c, ficha)] if modo_todos else []

    from app.services.recomendaciones import obtener_recomendaciones_ficha, CAT_TAREAS
    recomendaciones_tareas = obtener_recomendaciones_ficha(
        ficha_id, instructor_id=current_user.id, categorias={CAT_TAREAS},
    )

    metricas_resumen = {
        'total_tareas': len(lista_tareas),
        'tareas_activas': sum(
            1 for t in lista_tareas
            if t.progreso_tiempo['estado'] in ('normal', 'atencion', 'urgente')
        ),
        'tareas_urgentes': sum(
            1 for t in lista_tareas
            if t.progreso_tiempo['estado'] == 'urgente'
        ),
        'tareas_vencidas': sum(
            1 for t in lista_tareas
            if t.progreso_tiempo['estado'] == 'vencida'
        ),
        'tareas_sin_limite': sum(
            1 for t in lista_tareas
            if t.progreso_tiempo['estado'] == 'sin_limite'
        ),
    }

    return render_template(
        'tareas.html',
        ficha=ficha,
        tareas=lista_tareas,
        now=now,
        cortes=cortes_lista,
        corte_actual=corte,
        modo_todos=modo_todos,
        cortes_editables=cortes_editables,
        grupos=grupos,
        grupos_instructor=grupos_instructor,
        metricas_resumen=metricas_resumen,
        puede_editar_corte=puede_crear_tarea_en_corte(corte, ficha),
        filtro_instructor=filtro_instructor,
        instructores_ficha=instructores_ficha,
        recomendaciones_tareas=recomendaciones_tareas,
        grupos_ficha=Grupo.query.filter_by(ficha_id=ficha_id, activo=True).order_by(Grupo.nombre).all(),
    )


@instructor_bp.route('/fichas/<int:ficha_id>/tareas/<int:tarea_id>/editar', methods=['POST'])
@login_required
def editar_tarea(ficha_id, tarea_id):
    """Actualiza una tarea existente conservando entregas y evaluaciones."""
    ficha, tarea = obtener_tarea_gestionable(ficha_id, tarea_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    if not tarea:
        flash('No tienes permiso para editar esta tarea.', 'error')
        return redirect(url_for('instructor.tareas', ficha_id=ficha_id))

    try:
        datos = leer_datos_tarea(request.form)
        es_grupal, grupos_destino = validar_destinatarios_tarea(
            ficha_id,
            request.form.get('tipo_asignacion', 'individual'),
            datos['modalidad'],
            request.form.getlist('grupos_ids[]'),
        )
    except (DatosTareaInvalidos, DatosAsignacionTareaInvalidos) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('instructor.tareas', ficha_id=ficha_id))

    tiene_entregas = tarea.entregas.count() > 0
    if tiene_entregas and (
        es_grupal != tarea.es_grupal
        or {grupo.id for grupo in grupos_destino} != {grupo.id for grupo in tarea.grupos}
    ):
        flash(
            'No se puede cambiar la asignación individual o grupal cuando ya hay entregas. '
            'El resto de los cambios sí se guardó.',
            'error',
        )
        es_grupal = tarea.es_grupal
        grupos_destino = list(tarea.grupos)
    if tiene_entregas and datos['modalidad'] != tarea.modalidad:
        # Cambiar de modalidad con entregas registradas dejaría evidencias
        # huérfanas o aprobaciones de aula sin sentido. Se conserva la actual.
        flash(
            'No se puede cambiar la modalidad de una tarea que ya tiene registros. '
            'El resto de los cambios sí se guardó.',
            'error',
        )
        datos['modalidad'] = tarea.modalidad
        datos['requiere_archivo'] = (
            tarea.modalidad == MODALIDAD_EVIDENCIA and 'requiere_archivo' in request.form
        )

    material_anterior = tarea.material_apoyo_url
    material_nuevo = None
    archivo_material = request.files.get('material_apoyo')
    if archivo_material and archivo_material.filename:
        try:
            material_nuevo = guardar_material_apoyo(archivo_material, ficha_id, current_user.id)
        except ErrorArchivo as exc:
            flash(str(exc), 'error')
            return redirect(url_for('instructor.tareas', ficha_id=ficha_id))

    quitar_material = 'quitar_material' in request.form

    for campo, valor in datos.items():
        setattr(tarea, campo, valor)
    tarea.es_grupal = es_grupal
    tarea.grupos = grupos_destino
    if material_nuevo:
        tarea.material_apoyo_url = material_nuevo
    elif quitar_material:
        tarea.material_apoyo_url = None
    tarea.actualizada_en = datetime.utcnow()
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        if material_nuevo:
            ArchivoService.eliminar(material_nuevo)
        current_app.logger.exception('No se pudo actualizar la tarea con su material.')
        flash('No fue posible actualizar la tarea. El material anterior se conserva; vuelva a intentarlo.', 'error')
        return redirect(url_for('instructor.tareas', ficha_id=ficha_id))

    # El archivo viejo se borra después del commit: si la transacción fallara,
    # el registro seguiría apuntando a un archivo que ya no existe en disco.
    if material_anterior and (material_nuevo or quitar_material):
        ArchivoService.eliminar(material_anterior)

    _actualizar_indicadores_carga(ficha_id)
    flash(f'Tarea "{tarea.titulo}" actualizada.', 'success')
    return redirect(url_for('instructor.tareas', ficha_id=ficha_id))


@instructor_bp.route('/fichas/<int:ficha_id>/tareas/<int:tarea_id>/eliminar', methods=['POST'])
@login_required
def eliminar_tarea(ficha_id, tarea_id):
    """Elimina la tarea con sus entregas y los archivos asociados en disco."""
    ficha, tarea = obtener_tarea_gestionable(ficha_id, tarea_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))
    if not tarea:
        flash('No tienes permiso para eliminar esta tarea.', 'error')
        return redirect(url_for('instructor.tareas', ficha_id=ficha_id))

    titulo = eliminar_tarea_con_archivos(tarea)
    actualizar_alertas_ficha(ficha_id)
    actualizar_participacion_ficha(ficha_id)
    flash(f'Tarea "{titulo}" eliminada junto con sus registros.', 'success')
    return redirect(url_for('instructor.tareas', ficha_id=ficha_id))
