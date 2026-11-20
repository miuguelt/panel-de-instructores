"""Registro de actividades de clase y evidencias faltantes."""

from app import db
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.tarea import (
    Entrega,
    MODALIDAD_CLASE,
    ProrrogaTarea,
    Tarea,
)
from app.services.alertas import notificar_calificacion
from app.services.cortes import corte_actual
from app.services.permisos import puede_gestionar_ficha, puede_gestionar_tarea, tareas_visibles
from app.services.trabajos_grupales import obtener_destinatarios_y_entregas_grupales
from datetime import datetime
from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from . import (  # noqa: E402
    ZONA_HORARIA_BOGOTA,
    _actualizar_resumenes_despues_de_evaluar,
    _validar_calificacion,
    instructor_bp,
)


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
