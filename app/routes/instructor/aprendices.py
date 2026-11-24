"""Directorio de aprendices, configuración y portafolio."""

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from sqlalchemy import case, func
from sqlalchemy.exc import SQLAlchemyError

from app.services.visualizacion import UMBRAL_AMARILLO, UMBRAL_VERDE
from app import db
from app.models.aprendiz import (
    ESTADOS_EN_FORMACION,
    Aprendiz,
    etiqueta_estado,
    normalizar_url_portafolio,
)
from app.models.ficha import Ficha
from app.models.juicio import JuicioEvaluativo
from app.routes.auth import _destino_interno
from app.services.permisos import (
    cambiar_estado_activo_aprendiz,
    configurar_rol_aprendiz,
    puede_gestionar_ficha,
)

from . import instructor_bp


@instructor_bp.route('/fichas/<int:ficha_id>/aprendices')
@login_required
def aprendices(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    # El listado parte de TODOS los aprendices que entraron a la ficha, sin
    # importar su estado (condicionados, retirados, etc.); el filtro por
    # estado es una decision explicita del instructor via ?estado=.
    consulta = Aprendiz.query.filter_by(ficha_id=ficha_id)

    estados_disponibles = (
        db.session.query(Aprendiz.estado, func.count(Aprendiz.id))
        .filter(Aprendiz.ficha_id == ficha_id)
        .group_by(Aprendiz.estado)
        .all()
    )
    # Los estados activos primero, el resto en orden alfabético legible.
    estados_disponibles.sort(
        key=lambda par: (par[0] not in ESTADOS_EN_FORMACION, etiqueta_estado(par[0]))
    )
    total_aprendices = sum(conteo for _estado, conteo in estados_disponibles)

    estado_seleccionado = (request.args.get('estado') or 'todos').strip()
    if estado_seleccionado != 'todos':
        consulta = consulta.filter(Aprendiz.estado == estado_seleccionado)

    lista_aprendices = consulta.order_by(Aprendiz.apellidos, Aprendiz.nombre).all()
    aprendiz_ids = [a.id for a in lista_aprendices]

    # Estadísticas de juicios por aprendiz y acumulados globales
    stats_map = {}
    total_juicios_ficha = 0
    total_aprobados_ficha = 0
    al_dia_count = 0
    en_proceso_count = 0
    en_riesgo_count = 0

    if aprendiz_ids:
        juicio_normalizado = func.upper(JuicioEvaluativo.juicio)
        resumen = db.session.query(
            JuicioEvaluativo.aprendiz_id,
            func.count(JuicioEvaluativo.id),
            func.sum(case((
                juicio_normalizado.contains('APROBADO') & ~juicio_normalizado.contains('AUN NO'),
                1,
            ), else_=0)),
        ).filter(
            JuicioEvaluativo.ficha_id == ficha_id,
            JuicioEvaluativo.aprendiz_id.in_(aprendiz_ids),
        ).group_by(JuicioEvaluativo.aprendiz_id).all()
        tmp = {a_id: {'total': 0, 'aprobados': 0, 'pct': 0} for a_id in aprendiz_ids}
        for a_id, total, aprobados in resumen:
            tmp[a_id].update(total=total, aprobados=aprobados)

        for a_id in aprendiz_ids:
            s = tmp[a_id]
            t = s['total']
            ap = s['aprobados']
            pct = round(ap / t * 100) if t > 0 else 0
            s['pct'] = pct
            total_juicios_ficha += t
            total_aprobados_ficha += ap
            # Umbrales únicos (visualizacion.py): verde desde 80, amarillo desde 60.
            if pct >= UMBRAL_VERDE:
                al_dia_count += 1
            elif pct >= UMBRAL_AMARILLO:
                en_proceso_count += 1
            else:
                en_riesgo_count += 1

        stats_map = dict(tmp)

    pct_global = (
        round(total_aprobados_ficha / total_juicios_ficha * 100)
        if total_juicios_ficha > 0
        else 0
    )

    aprendices_administrables = (
        Aprendiz.query_llamado_lista(ficha_id)
        .order_by(Aprendiz.apellidos, Aprendiz.nombre)
        .all()
    )

    enlace_acceso_aprendices = url_for(
        'aprendiz.vista_aprendiz', ficha_id=ficha.id, _external=True
    )

    return render_template(
        'aprendices.html',
        ficha=ficha,
        aprendices=lista_aprendices,
        aprendices_administrables=aprendices_administrables,
        juicios_stats=stats_map,
        estados_disponibles=estados_disponibles,
        total_aprendices=total_aprendices,
        estado_seleccionado=estado_seleccionado,
        pct_global=pct_global,
        total_juicios_ficha=total_juicios_ficha,
        total_aprobados_ficha=total_aprobados_ficha,
        al_dia_count=al_dia_count,
        en_proceso_count=en_proceso_count,
        en_riesgo_count=en_riesgo_count,
        enlace_acceso_aprendices=enlace_acceso_aprendices,
    )


@instructor_bp.route('/fichas/<int:ficha_id>/aprendices/configuracion')
@login_required
def configuracion_aprendices(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    aprendices_administrables = (
        Aprendiz.query_llamado_lista(ficha_id, solo_activos=True)
        .order_by(Aprendiz.apellidos, Aprendiz.nombre)
        .all()
    )
    todos_aprendices = (
        Aprendiz.query.filter_by(ficha_id=ficha_id)
        .order_by(Aprendiz.apellidos, Aprendiz.nombre)
        .all()
    )
    administrador = Aprendiz.query.filter_by(
        ficha_id=ficha_id, rol_administrativo=True
    ).first()

    return render_template(
        'aprendices_configuracion.html',
        ficha=ficha,
        aprendices_administrables=aprendices_administrables,
        todos_aprendices=todos_aprendices,
        administrador=administrador,
    )


@instructor_bp.route(
    '/fichas/<int:ficha_id>/aprendices/<int:aprendiz_id>/rol-administrativo',
    methods=['POST'],
)
@login_required
def actualizar_rol_administrativo(ficha_id, aprendiz_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    accion = (request.form.get('accion') or 'activar').strip().lower()
    habilitar = accion != 'desactivar'

    try:
        aprendiz = configurar_rol_aprendiz(ficha_id, aprendiz_id, habilitar=habilitar)
        db.session.commit()
        if habilitar:
            flash(
                f'{aprendiz.nombre_completo} ahora tiene el rol administrativo de la ficha.',
                'success',
            )
        else:
            flash(
                f'Se retiró el rol administrativo a {aprendiz.nombre_completo}.',
                'info',
            )
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error al actualizar rol administrativo del aprendiz')
        flash('Ocurrió un error al actualizar el rol administrativo.', 'error')

    return redirect(url_for('instructor.configuracion_aprendices', ficha_id=ficha_id))


@instructor_bp.route(
    '/fichas/<int:ficha_id>/aprendices/<int:aprendiz_id>/estado-activo',
    methods=['POST'],
)
@login_required
def alternar_estado_activo_aprendiz(ficha_id, aprendiz_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    accion = (request.form.get('accion') or '').strip().lower()
    activo = None
    if accion == 'deshabilitar':
        activo = False
    elif accion == 'habilitar':
        activo = True

    try:
        aprendiz = cambiar_estado_activo_aprendiz(ficha_id, aprendiz_id, activo=activo)
        db.session.commit()
        if aprendiz.activo:
            flash(
                f'{aprendiz.nombre_completo} ha sido habilitado para ranking, grupos, turnos de aseo y llamado a lista.',
                'success',
            )
        else:
            flash(
                f'{aprendiz.nombre_completo} ha sido deshabilitado. No aparecerá en el ranking, grupos, turnos de aseo ni en el llamado a lista.',
                'info',
            )
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error al cambiar estado activo del aprendiz')
        flash('Ocurrió un error al actualizar el estado del aprendiz.', 'error')

    siguiente = _destino_interno(request.form.get('next') or request.referrer)
    if siguiente:
        return redirect(siguiente)
    return redirect(url_for('instructor.aprendices', ficha_id=ficha_id))




@instructor_bp.route('/fichas/<int:ficha_id>/aprendices/<int:aprendiz_id>/portafolio', methods=['POST'])
@login_required
def guardar_portafolio_instructor(ficha_id, aprendiz_id):
    ficha = db.session.get(Ficha, ficha_id)
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not puede_gestionar_ficha(ficha) or not aprendiz or aprendiz.ficha_id != ficha_id:
        abort(403)

    es_ajax = (
        request.is_json
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('Accept', '')
    )
    datos = request.get_json(silent=True) if request.is_json else request.form
    if request.is_json and not isinstance(datos, dict):
        return jsonify(ok=False, error='Envíe los enlaces del portafolio en un objeto JSON válido.'), 400
    github_raw = datos.get('enlace_github', '')
    notion_raw = datos.get('enlace_notion', '')

    try:
        github_valido = normalizar_url_portafolio(github_raw, tipo='github')
        notion_valido = normalizar_url_portafolio(notion_raw, tipo='notion')
    except ValueError as error:
        # Mensajes propios de normalizar_url_portafolio: indican qué enlace corregir.
        mensaje_val = str(error) or 'Las direcciones web ingresadas no tienen un formato válido.'
        if es_ajax:
            return jsonify({'ok': False, 'error': mensaje_val}), 400
        flash(mensaje_val, 'error')
        return redirect(url_for('instructor.historial_aprendiz', ficha_id=ficha_id, aprendiz_id=aprendiz.id))

    aprendiz.enlace_github = github_valido
    aprendiz.enlace_notion = notion_valido
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        mensaje_error = 'Ocurrió un error al guardar los enlaces del aprendiz.'
        if es_ajax:
            return jsonify({'ok': False, 'error': mensaje_error}), 500
        flash(mensaje_error, 'error')
        return redirect(url_for('instructor.historial_aprendiz', ficha_id=ficha_id, aprendiz_id=aprendiz.id))

    mensaje_exito = f'Los enlaces de GitHub y Notion de {aprendiz.nombre} fueron actualizados con éxito.'
    if es_ajax:
        return jsonify({
            'ok': True,
            'mensaje': mensaje_exito,
            'enlace_github': aprendiz.enlace_github,
            'enlace_notion': aprendiz.enlace_notion,
        })

    flash(mensaje_exito, 'success')
    return redirect(url_for('instructor.historial_aprendiz', ficha_id=ficha_id, aprendiz_id=aprendiz.id))
