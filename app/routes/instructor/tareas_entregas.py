"""Tareas, entregas, prórrogas y evidencias de planes."""

from app import db
from app.models.alertas import PlanMejoramiento
from app.models.aprendiz import Aprendiz, ESTADOS_EN_FORMACION
from app.models.corte import Corte
from app.models.ficha import Ficha
from app.models.ficha_instructor import FichaInstructor
from app.models.grupo import Grupo
from app.models.insignia import Insignia, InsigniaOtorgada
from app.models.observador import NotaObservador, TIPO_NEGATIVA
from app.models.tarea import (
    Entrega,
    MODALIDAD_CLASE,
    MODALIDAD_EVIDENCIA,
    ProrrogaTarea,
    Tarea,
)
from app.services.alertas import actualizar_alertas_ficha, notificar_calificacion
from app.services.archivos import (
    ArchivoService,
    ErrorArchivo,
    nombre_original_desde_ruta,
    resolver_archivo_subido,
)
from app.services.cortes import corte_actual, cortes_visibles
from app.services.permisos import (
    puede_crear_tarea_en_corte,
    puede_gestionar_ficha,
    puede_gestionar_tarea,
    puede_ver_tarea,
    tareas_visibles,
)
from app.services.ranking import actualizar_participacion_ficha
from app.services.tareas import (
    DatosTareaInvalidos,
    agrupar_tareas_por_corte_e_instructor,
    agrupar_tareas_por_instructor,
    conceder_prorroga_tarea,
    eliminar_tarea_con_archivos,
    guardar_material_apoyo,
    leer_datos_tarea,
    obtener_planes_de_tarea,
    obtener_prorrogas_tarea,
    obtener_tarea_gestionable,
    revocar_prorroga_tarea,
)
from app.services.trabajos_grupales import DatosAsignacionTareaInvalidos, obtener_destinatarios_y_entregas_grupales, validar_destinatarios_tarea
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
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

from . import (  # noqa: E402
    ZONA_HORARIA_BOGOTA,
    _actualizar_indicadores_carga,
    _actualizar_resumenes_despues_de_evaluar,
    _validar_calificacion,
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


@instructor_bp.route('/tareas/<int:tarea_id>/actividad-clase', methods=['POST'])
@login_required
def registrar_actividad_clase(tarea_id):
    """Aprueba en bloque una actividad revisada presencialmente.

    Cada aprendiz marcado recibe (o conserva) un registro de cumplimiento sin
    archivo; los desmarcados pierden el registro previo, de modo que el
    instructor puede corregir una aprobación equivocada.
    """
    tarea = db.session.get(Tarea, tarea_id)
    if not tarea:
        flash('Tarea no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    ficha = tarea.ficha
    if not puede_gestionar_ficha(ficha) or not puede_gestionar_tarea(tarea):
        flash('No tienes permiso para registrar esta actividad.', 'error')
        return redirect(url_for('instructor.fichas'))

    if not tarea.es_actividad_clase:
        flash('Esta tarea espera evidencias del aprendiz, no aprobación en aula.', 'error')
        return redirect(url_for('instructor.ver_entregas', tarea_id=tarea.id))

    aprendices = Aprendiz.query_en_formacion(ficha.id).all()
    ids_validos = {aprendiz.id for aprendiz in aprendices}
    aprendices_por_id = {aprendiz.id: aprendiz for aprendiz in aprendices}
    aprobados = set()
    for valor in request.form.getlist('aprobados'):
        try:
            aprendiz_id = int(valor)
        except (TypeError, ValueError):
            continue
        if aprendiz_id in ids_validos:
            aprobados.add(aprendiz_id)

    calificacion, error_calificacion = _validar_calificacion(
        request.form.get('calificacion_general')
    )
    if error_calificacion:
        flash(error_calificacion, 'error')
        return redirect(url_for('instructor.ver_entregas', tarea_id=tarea.id))
    observacion = request.form.get('observacion_general', '').strip() or None

    existentes = {
        entrega.aprendiz_id: entrega
        for entrega in Entrega.query.filter_by(tarea_id=tarea.id).all()
    }
    ahora = datetime.utcnow()
    nuevas = 0
    retiradas = 0

    for aprendiz_id in ids_validos:
        entrega = existentes.get(aprendiz_id)
        if aprendiz_id in aprobados:
            anterior = None if not entrega else (
                entrega.registrada_por_instructor,
                entrega.calificada,
                entrega.calificacion,
                entrega.feedback,
                entrega.estado_revision,
            )
            if not entrega:
                entrega = Entrega(
                    tarea_id=tarea.id,
                    aprendiz_id=aprendiz_id,
                    aprendiz=aprendices_por_id[aprendiz_id],
                )
                db.session.add(entrega)
                nuevas += 1
            entrega.registrada_por_instructor = True
            entrega.fecha_entrega = entrega.fecha_entrega or ahora
            entrega.estado_revision = 'aprobada'
            entrega.calificada = True
            entrega.calificacion = calificacion
            entrega.feedback = observacion
            entrega.revisada_en = ahora
            entrega.revisada_por_id = current_user.id
            actual = (
                entrega.registrada_por_instructor,
                entrega.calificada,
                entrega.calificacion,
                entrega.feedback,
                entrega.estado_revision,
            )
            if anterior != actual:
                notificar_calificacion(entrega, ficha.id, commit=False)
        elif entrega and entrega.registrada_por_instructor:
            db.session.delete(entrega)
            retiradas += 1

    try:
        db.session.commit()
    except IntegrityError:
        # Dos instructores registrando la misma actividad a la vez: se deja
        # ganar al primero y se informa para que el segundo recargue.
        db.session.rollback()
        flash('Otro instructor registró esta actividad al mismo tiempo. Revisa el resultado.', 'error')
        return redirect(url_for('instructor.ver_entregas', tarea_id=tarea.id))

    errores_resumen = _actualizar_resumenes_despues_de_evaluar(ficha.id)
    flash(
        f'Actividad registrada: {len(aprobados)} aprendiz(es) aprobado(s) '
        f'({nuevas} nuevo(s), {retiradas} aprobación(es) retirada(s)).',
        'warning' if errores_resumen else 'success',
    )
    if errores_resumen:
        flash(
            'La actividad quedó guardada, pero no se pudieron actualizar: '
            + ', '.join(errores_resumen) + '.',
            'warning',
        )
    return redirect(url_for('instructor.ver_entregas', tarea_id=tarea.id))


@instructor_bp.route('/fichas/<int:ficha_id>/evidencias-faltantes')
@login_required
def evidencias_faltantes(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    aprendices_list = Aprendiz.query_en_formacion(ficha.id).order_by(
        Aprendiz.apellidos, Aprendiz.nombre
    ).all()
    tareas = tareas_visibles(ficha_id).order_by(Tarea.fecha_limite.desc()).all()
    
    ahora = datetime.now(ZONA_HORARIA_BOGOTA).replace(tzinfo=None)
    
    ids_tareas = [tarea.id for tarea in tareas]
    if ids_tareas:
        entregas_query = (
            Entrega.query
            .filter(Entrega.tarea_id.in_(ids_tareas))
            .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
            .all()
        )
        prorrogas_query = ProrrogaTarea.query.filter(
            ProrrogaTarea.tarea_id.in_(ids_tareas)
        ).all()
    else:
        entregas_query = []
        prorrogas_query = []

    entregas_map = {}
    for e in entregas_query:
        key = (e.tarea_id, e.aprendiz_id)
        entregas_map.setdefault(key, e)

    prorrogas_map = {
        (prorroga.tarea_id, prorroga.aprendiz_id): prorroga
        for prorroga in prorrogas_query
    }
    destinatarios_grupales, entregas_grupales = (
        obtener_destinatarios_y_entregas_grupales(ficha_id, ids_tareas)
    )
    ids_grupales = {tarea.id for tarea in tareas if tarea.es_grupal}
    for clave in list(entregas_map):
        if clave[0] in ids_grupales:
            entregas_map.pop(clave)
    entregas_map.update(entregas_grupales)

    datos_aprendices = []
    for ap in aprendices_list:
        faltantes = []
        entregadas = 0
        tareas_aprendiz = []
        for tarea in tareas:
            if (
                tarea.es_grupal
                and ap.id not in destinatarios_grupales.get(tarea.id, set())
            ):
                continue
            tareas_aprendiz.append(tarea)
            entrega = entregas_map.get((tarea.id, ap.id))
            prorroga = prorrogas_map.get((tarea.id, ap.id))
            fecha_limite = (
                prorroga.nueva_fecha_limite if prorroga else tarea.fecha_limite
            )
            if entrega:
                if entrega.estado_revision == 'rechazada':
                    estado = 'correccion'
                else:
                    entregadas += 1
                    continue
            else:
                vencida = bool(fecha_limite and fecha_limite < ahora)
                if tarea.modalidad == MODALIDAD_CLASE:
                    estado = 'actividad_vencida' if vencida else 'actividad'
                else:
                    estado = 'vencida' if vencida else 'pendiente'

            if estado in ('pendiente', 'vencida', 'correccion', 'actividad', 'actividad_vencida'):
                faltantes.append({
                    'tarea': tarea,
                    'estado': estado,
                    'fecha_limite': (
                        fecha_limite.replace(tzinfo=ZONA_HORARIA_BOGOTA)
                        if fecha_limite and fecha_limite.tzinfo is None
                        else fecha_limite.astimezone(ZONA_HORARIA_BOGOTA)
                        if fecha_limite else None
                    ),
                    'tiene_prorroga': bool(prorroga),
                    'prorroga_vigente': bool(
                        prorroga and prorroga.nueva_fecha_limite >= ahora
                    ),
                })

        total_tareas = len(tareas_aprendiz)
        cantidad_faltante = len(faltantes)
        estado_general = (
            'sin_tareas' if total_tareas == 0
            else 'completo' if cantidad_faltante == 0
            else 'pendiente'
        )
        datos_aprendices.append({
            'aprendiz': ap,
            'faltantes': faltantes,
            'cantidad': cantidad_faltante,
            'entregadas': entregadas,
            'total_tareas': total_tareas,
            'porcentaje': round(entregadas / total_tareas * 100) if total_tareas else None,
            'estado_general': estado_general,
        })

    datos_aprendices.sort(
        key=lambda item: (
            item['estado_general'] != 'pendiente',
            -item['cantidad'],
            item['aprendiz'].apellidos.casefold(),
            item['aprendiz'].nombre.casefold(),
        )
    )
    total_asignaciones = sum(item['total_tareas'] for item in datos_aprendices)
    total_entregadas = sum(item['entregadas'] for item in datos_aprendices)
    resumen = {
        'total_tareas': len(tareas),
        'total_aprendices': len(aprendices_list),
        'total_asignaciones': total_asignaciones,
        'entregadas': total_entregadas,
        'pendientes': total_asignaciones - total_entregadas,
        'aprendices_completos': sum(
            item['estado_general'] == 'completo' for item in datos_aprendices
        ),
        'aprendices_pendientes': sum(
            item['estado_general'] == 'pendiente' for item in datos_aprendices
        ),
        'porcentaje': round(total_entregadas / total_asignaciones * 100)
        if total_asignaciones else None,
    }

    return render_template(
        'instructor/evidencias_faltantes.html',
        ficha=ficha,
        datos=datos_aprendices,
        resumen=resumen,
        corte_actual=corte_actual(ficha_id)
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
