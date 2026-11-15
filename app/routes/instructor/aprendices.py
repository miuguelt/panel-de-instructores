from collections import defaultdict
from datetime import datetime

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from app import db
from app.models.alertas import Alerta, PlanMejoramiento
from app.models.aprendiz import ESTADOS_EN_FORMACION, Aprendiz, etiqueta_estado, normalizar_url_portafolio
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.models.ficha import Ficha
from app.models.grupo import GrupoAprendiz
from app.models.insignia import Insignia, InsigniaOtorgada
from app.models.juicio import JuicioEvaluativo
from app.models.observador import NotaObservador
from app.models.tarea import Entrega, Tarea
from app.routes.auth import _destino_interno
from app.services.aseo import resumen_aprendiz
from app.services.importacion_ficha import clasificar_competencia
from app.services.permisos import (
    cambiar_estado_activo_aprendiz,
    configurar_rol_aprendiz,
    puede_gestionar_ficha,
    tareas_visibles,
)
from app.services.ranking import calcular_ranking

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
            if pct >= 80:
                al_dia_count += 1
            elif pct >= 50:
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


@instructor_bp.route('/fichas/<int:ficha_id>/aprendices/<int:aprendiz_id>/historial')
@login_required
def historial_aprendiz(ficha_id, aprendiz_id):
    # Detailed learner report keeps persisted academic, attendance and follow-up data together.
    ficha = db.session.get(Ficha, ficha_id)
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not puede_gestionar_ficha(ficha) or not aprendiz or aprendiz.ficha_id != ficha_id:
        flash('Aprendiz no encontrado.', 'error')
        return redirect(url_for('instructor.aprendices', ficha_id=ficha_id))

    juicios = JuicioEvaluativo.query.filter_by(
        ficha_id=ficha_id, aprendiz_id=aprendiz.id
    ).order_by(JuicioEvaluativo.fecha_juicio.desc(), JuicioEvaluativo.importado_en.desc()).all()

    # Stat global de juicios
    stats_juicios = {
        'total': 0, 'aprobados': 0,
        'tecnica': 0, 'tecnica_aprobada': 0,
        'transversal': 0, 'transversal_aprobada': 0,
        'ingles': 0, 'ingles_aprobada': 0,
    }
    for j in juicios:
        stats_juicios['total'] += 1
        es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper() and 'POR EVALUAR' not in j.juicio.upper())
        if es_aprobado:
            stats_juicios['aprobados'] += 1
        tipo = j.tipo_competencia or clasificar_competencia(j.competencia)
        if tipo not in ('tecnica', 'transversal', 'ingles'):
            tipo = 'tecnica'
        stats_juicios[tipo] += 1
        if es_aprobado:
            stats_juicios[f"{tipo}_aprobada"] += 1

    stats_juicios['pct_total'] = round((stats_juicios['aprobados'] / stats_juicios['total'] * 100)) if stats_juicios['total'] > 0 else 0
    stats_juicios['pct_tecnica'] = round((stats_juicios['tecnica_aprobada'] / stats_juicios['tecnica'] * 100)) if stats_juicios['tecnica'] > 0 else 0
    stats_juicios['pct_transversal'] = round((stats_juicios['transversal_aprobada'] / stats_juicios['transversal'] * 100)) if stats_juicios['transversal'] > 0 else 0
    stats_juicios['pct_ingles'] = round((stats_juicios['ingles_aprobada'] / stats_juicios['ingles'] * 100)) if stats_juicios['ingles'] > 0 else 0

    instructores = {ficha.instructor}
    instructores.update(v.instructor for v in ficha.instructores_asociados if v.instructor)
    instructores = sorted(instructores, key=lambda i: i.nombre)

    # Asistencia
    total_sesiones = SesionAsistencia.query.join(RegistroAsistencia).filter(SesionAsistencia.ficha_id == ficha_id).distinct().count()
    total_faltas = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        RegistroAsistencia.aprendiz_id == aprendiz.id,
        RegistroAsistencia.estado.in_(['FALTA', 'FALTA_JUSTIFICADA', 'EXCUSA_MEDICA']),
    ).count()
    pct_asistencia = round(((total_sesiones - total_faltas) / total_sesiones * 100), 1) if total_sesiones else 100.0

    # Tareas
    tareas = tareas_visibles(ficha_id).order_by(Tarea.fecha_limite).all()
    tareas_estado = []
    for tarea in tareas:
        entrega = (
            Entrega.query
            .filter_by(tarea_id=tarea.id, aprendiz_id=aprendiz.id)
            .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
            .first()
        )
        estado = 'pendiente'
        if entrega:
            if entrega.estado_revision == 'rechazada':
                estado = 'correccion'
            elif entrega.entregada_a_tiempo:
                estado = 'entregada'
            else:
                estado = 'retraso'
        elif tarea.fecha_limite and tarea.fecha_limite < datetime.utcnow():
            estado = 'vencida'
        tareas_estado.append({'tarea': tarea, 'entrega': entrega, 'estado': estado})

    # Insignias
    # Buscar insignias individuales y grupales
    grupos_aprendiz = select(GrupoAprendiz.grupo_id).where(
        GrupoAprendiz.aprendiz_id == aprendiz.id
    )

    otorgamientos = InsigniaOtorgada.query.join(Insignia).filter(
        or_(
            InsigniaOtorgada.aprendiz_id == aprendiz.id,
            InsigniaOtorgada.grupo_id.in_(grupos_aprendiz)
        ),
        Insignia.ficha_id == ficha_id,
    ).order_by(InsigniaOtorgada.fecha_obtencion.desc()).all()

    # Ranking y Aseo
    filas_ranking, _ = calcular_ranking(ficha_id)
    ranking = next((fila for fila in filas_ranking if fila['aprendiz'].id == aprendiz.id), None)
    aseo = resumen_aprendiz(ficha_id, aprendiz)

    # ---- ANÁLISIS DE COMPETENCIAS DE ESTE APRENDIZ ----
    competencias_map = {}
    for j in juicios:
        comp_nombre = (j.competencia or 'Sin nombre').strip()
        tipo = j.tipo_competencia or clasificar_competencia(comp_nombre)
        if tipo not in ('tecnica', 'transversal', 'ingles'):
            tipo = 'tecnica'

        if comp_nombre not in competencias_map:
            competencias_map[comp_nombre] = {
                'nombre': comp_nombre,
                'tipo': tipo,
                'total_raps': 0,
                'aprobados_raps': 0,
                'raps': [],
                'ultima_fecha': j.fecha_juicio
            }

        c_data = competencias_map[comp_nombre]
        c_data['total_raps'] += 1

        es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper() and 'POR EVALUAR' not in j.juicio.upper())
        if es_aprobado:
            c_data['aprobados_raps'] += 1

        c_data['raps'].append({
            'resultado': j.resultado_aprendizaje or 'Sin descripción de resultado',
            'juicio': j.juicio or 'Sin registrar',
            'aprobado': es_aprobado,
            'fecha': j.fecha_juicio,
            'instructor': j.funcionario_registro or 'Sistema'
        })

        if j.fecha_juicio and (not c_data['ultima_fecha'] or j.fecha_juicio > c_data['ultima_fecha']):
            c_data['ultima_fecha'] = j.fecha_juicio

    competencias_por_tipo = {
        'tecnica': [],
        'transversal': [],
        'ingles': []
    }

    for c_data in competencias_map.values():
        total = c_data['total_raps']
        aprobados = c_data['aprobados_raps']
        pct = round((aprobados / total * 100)) if total > 0 else 0
        c_data['pct'] = pct
        c_data['pendientes_raps'] = total - aprobados

        if pct == 100:
            c_data['estado'] = 'completada'
        elif aprobados > 0:
            c_data['estado'] = 'en_progreso'
        else:
            c_data['estado'] = 'pendiente'

        competencias_por_tipo[c_data['tipo']].append(c_data)

    for tipo in competencias_por_tipo:
        competencias_por_tipo[tipo].sort(key=lambda x: x['nombre'])

    resumen_tipos = {}
    for tipo, lista in competencias_por_tipo.items():
        t_raps = sum(c['total_raps'] for c in lista)
        a_raps = sum(c['aprobados_raps'] for c in lista)
        resumen_tipos[tipo] = {
            'total': len(lista),
            'completadas': sum(1 for c in lista if c['estado'] == 'completada'),
            'en_progreso': sum(1 for c in lista if c['estado'] == 'en_progreso'),
            'pendientes': sum(1 for c in lista if c['estado'] == 'pendiente'),
            'total_raps': t_raps,
            'aprobados_raps': a_raps,
            'pct_raps': round((a_raps / t_raps * 100)) if t_raps > 0 else 0
        }

    # Timeline para este aprendiz
    timeline_aprendiz_hist = {}
    for j in juicios:
        if j.fecha_juicio:
            mes = j.fecha_juicio.strftime('%Y-%m')
            if mes not in timeline_aprendiz_hist:
                timeline_aprendiz_hist[mes] = {'total': 0, 'aprobados': 0}
            timeline_aprendiz_hist[mes]['total'] += 1
            es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper() and 'POR EVALUAR' not in j.juicio.upper())
            if es_aprobado:
                timeline_aprendiz_hist[mes]['aprobados'] += 1
    timeline_aprendiz_hist_ord = sorted(timeline_aprendiz_hist.items())

    # Stats por instructor para este aprendiz
    instructores_aprendiz_hist = {}
    for j in juicios:
        func_reg = j.funcionario_registro or 'Sin registro'
        if func_reg not in instructores_aprendiz_hist:
            instructores_aprendiz_hist[func_reg] = {'total': 0, 'aprobados': 0, 'pendientes': 0}
        instructores_aprendiz_hist[func_reg]['total'] += 1
        es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper() and 'POR EVALUAR' not in j.juicio.upper())
        if es_aprobado:
            instructores_aprendiz_hist[func_reg]['aprobados'] += 1
        else:
            instructores_aprendiz_hist[func_reg]['pendientes'] += 1

    for func_reg in instructores_aprendiz_hist.values():
        func_reg['pct'] = round((func_reg['aprobados'] / func_reg['total'] * 100)) if func_reg['total'] > 0 else 0

    fechas_aprendiz = [j.fecha_juicio for j in juicios if j.fecha_juicio]
    resumen_aprendiz_hist = {
        'total_competencias': len(competencias_map),
        'total_instructores': len(instructores_aprendiz_hist),
        'primera_evaluacion': min(fechas_aprendiz) if fechas_aprendiz else None,
        'ultima_evaluacion': max(fechas_aprendiz) if fechas_aprendiz else None,
    }

    # ---- REPORTE DETALLADO: ASISTENCIA ----
    registros_aprendiz = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        RegistroAsistencia.aprendiz_id == aprendiz.id,
    ).order_by(SesionAsistencia.fecha.desc()).all()

    estados_asistencia = {
        'ASISTE': {'label': 'Asistió', 'count': 0, 'tone': 'success'},
        'TARDANZA': {'label': 'Tardanza', 'count': 0, 'tone': 'warning'},
        'FALTA': {'label': 'Falta injustificada', 'count': 0, 'tone': 'danger'},
        'FALTA_JUSTIFICADA': {'label': 'Falta justificada', 'count': 0, 'tone': 'info'},
        'EXCUSA_MEDICA': {'label': 'Excusa médica', 'count': 0, 'tone': 'info'},
        'SIN_REGISTRO': {'label': 'Sin registro', 'count': 0, 'tone': 'secondary'},
    }
    asistencia_por_mes = defaultdict(lambda: {
        'total': 0, 'asistio': 0, 'tardanzas': 0, 'faltas': 0, 'justificadas': 0,
    })
    for registro in registros_aprendiz:
        # Un estado desconocido no se presume falta injustificada.
        estado = registro.estado if registro.estado in estados_asistencia else 'SIN_REGISTRO'
        estados_asistencia[estado]['count'] += 1
        if registro.sesion and registro.sesion.fecha:
            mes = registro.sesion.fecha.strftime('%Y-%m')
            mensual = asistencia_por_mes[mes]
            mensual['total'] += 1
            if estado == 'ASISTE':
                mensual['asistio'] += 1
            elif estado == 'TARDANZA':
                mensual['tardanzas'] += 1
            elif estado == 'FALTA':
                mensual['faltas'] += 1
            elif estado in ('FALTA_JUSTIFICADA', 'EXCUSA_MEDICA'):
                mensual['justificadas'] += 1

    asistencia_detalle = [{
        'fecha': registro.sesion.fecha if registro.sesion else None,
        'estado': registro.estado,
        'causal': registro.causal_justificacion,
        'nota': registro.nota,
        'soporte': bool(registro.soporte_url),
        'observaciones_sesion': registro.sesion.observaciones if registro.sesion else None,
    } for registro in registros_aprendiz]
    asistencia_mensual = sorted(asistencia_por_mes.items(), reverse=True)
    faltas_injustificadas = estados_asistencia['FALTA']['count']
    faltas_justificadas = (
        estados_asistencia['FALTA_JUSTIFICADA']['count']
        + estados_asistencia['EXCUSA_MEDICA']['count']
    )

    # ---- REPORTE DETALLADO: TAREAS Y EVIDENCIAS ----
    tareas_resumen = {
        'total': len(tareas_estado),
        'entregas': sum(1 for item in tareas_estado if item['entrega']),
        'a_tiempo': sum(1 for item in tareas_estado if item['estado'] == 'entregada'),
        'retrasos': sum(1 for item in tareas_estado if item['estado'] == 'retraso'),
        'pendientes': sum(1 for item in tareas_estado if item['estado'] == 'pendiente'),
        'vencidas': sum(1 for item in tareas_estado if item['estado'] == 'vencida'),
        'correcciones': sum(1 for item in tareas_estado if item['estado'] == 'correccion'),
        'calificadas': sum(1 for item in tareas_estado if item['entrega'] and item['entrega'].calificada),
    }
    calificaciones = []
    for item in tareas_estado:
        if item['entrega'] and item['entrega'].calificacion:
            try:
                calificaciones.append(float(str(item['entrega'].calificacion).replace(',', '.')))
            except (TypeError, ValueError):
                pass
    tareas_resumen['promedio'] = round(sum(calificaciones) / len(calificaciones), 2) if calificaciones else None
    tareas_resumen['pct_entrega'] = round((tareas_resumen['entregas'] / tareas_resumen['total']) * 100) if tareas_resumen['total'] else 0
    tareas_resumen['pct_a_tiempo'] = round((tareas_resumen['a_tiempo'] / tareas_resumen['total']) * 100) if tareas_resumen['total'] else 0

    # ---- REPORTE DETALLADO: SEGUIMIENTO Y PLANES ----
    alertas_aprendiz = Alerta.query.filter_by(
        ficha_id=ficha_id, aprendiz_id=aprendiz.id
    ).order_by(Alerta.fecha_generada.desc()).all()
    planes_aprendiz = PlanMejoramiento.query.filter_by(
        ficha_id=ficha_id, aprendiz_id=aprendiz.id
    ).order_by(PlanMejoramiento.fecha_creacion.desc()).all()
    seguimiento_resumen = {
        'alertas_total': len(alertas_aprendiz),
        'alertas_activas': sum(1 for alerta in alertas_aprendiz if alerta.estado == 'activa'),
        'alertas_rojas': sum(1 for alerta in alertas_aprendiz if alerta.nivel == 'roja' and alerta.estado in ('activa', 'escalada_comite')),
        'alertas_resueltas': sum(1 for alerta in alertas_aprendiz if alerta.estado == 'resuelta'),
        'planes_total': len(planes_aprendiz),
        'planes_pendientes': sum(1 for plan in planes_aprendiz if plan.estado == 'pendiente'),
        'planes_cumplidos': sum(1 for plan in planes_aprendiz if plan.estado == 'cumplido'),
        'planes_vencidos': sum(1 for plan in planes_aprendiz if plan.estado == 'vencido'),
    }

    # ---- ACTIVIDAD Y CONTEXTO DEL REPORTE ----
    entregas_aprendiz = [item['entrega'] for item in tareas_estado if item['entrega']]

    def _actividad_datetime(valor):
        if isinstance(valor, datetime):
            return valor
        return datetime.combine(valor, datetime.min.time()) if valor else None

    fechas_actividad = [
        fecha for fecha in (
            resumen_aprendiz_hist['ultima_evaluacion'],
            registros_aprendiz[0].sesion.fecha if registros_aprendiz and registros_aprendiz[0].sesion else None,
            max((entrega.fecha_entrega for entrega in entregas_aprendiz if entrega.fecha_entrega), default=None),
        ) if fecha
    ]
    resumen_reporte = {
        'generado_en': datetime.now(),
        'total_aprendices_ficha': Aprendiz.query_en_formacion(ficha_id).count(),
        'ultima_actividad': max((_actividad_datetime(fecha) for fecha in fechas_actividad), default=None),
        'ultima_asistencia': registros_aprendiz[0].sesion.fecha if registros_aprendiz and registros_aprendiz[0].sesion else None,
        'ultima_entrega': max((entrega.fecha_entrega for entrega in entregas_aprendiz if entrega.fecha_entrega), default=None),
        'total_registros_asistencia': len(registros_aprendiz),
    }

    notas_observador = (
        NotaObservador.query
        .options(joinedload(NotaObservador.autor))
        .filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz.id)
        .order_by(NotaObservador.fecha.desc(), NotaObservador.id.desc())
        .all()
    )

    return render_template('instructor/historial_aprendiz.html', ficha=ficha, aprendiz=aprendiz,
                           notas_observador=notas_observador,
                           juicios=juicios, instructores=instructores,
                           pct_asistencia=pct_asistencia, total_sesiones=total_sesiones, total_faltas=total_faltas,
                           tareas_estado=tareas_estado, otorgamientos=otorgamientos,
                           ranking=ranking, aseo=aseo,
                           stats_juicios=stats_juicios,
                           competencias_por_tipo=competencias_por_tipo,
                           resumen_tipos=resumen_tipos,
                           timeline_aprendiz_hist=timeline_aprendiz_hist_ord,
                           instructores_aprendiz_hist=instructores_aprendiz_hist,
                           resumen_aprendiz_hist=resumen_aprendiz_hist,
                           registros_asistencia=asistencia_detalle,
                           estados_asistencia=estados_asistencia,
                           asistencia_mensual=asistencia_mensual,
                           faltas_injustificadas=faltas_injustificadas,
                           faltas_justificadas=faltas_justificadas,
                           tareas_resumen=tareas_resumen,
                           alertas_aprendiz=alertas_aprendiz,
                           planes_aprendiz=planes_aprendiz,
                           seguimiento_resumen=seguimiento_resumen,
                           resumen_reporte=resumen_reporte)


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
