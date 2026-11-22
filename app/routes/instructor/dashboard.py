"""Panel «Mis fichas» del instructor."""
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
from sqlalchemy import func, or_

from app import db
from app.models.alertas import Alerta, PlanMejoramiento
from app.models.aprendiz import ESTADOS_EN_FORMACION, Aprendiz
from app.models.archivo_ficha import (
    TIPO_PLANEACION,
    TIPO_REPORTE_JUICIOS,
)
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.models.juicio import JuicioEvaluativo
from app.models.observador import NotaObservador
from app.models.tarea import MODALIDAD_EVIDENCIA, Entrega, Tarea
from app.services.cronograma import obtener_cronograma
from app.services.fases_dashboard import obtener_seguimiento_fases_dashboard
from app.services.prioridad_fichas import ordenar_por_urgencia, resumen_global
from app.services.emparejamiento_juicios import condicion_aprobado_sql
from app.services.versiones_archivos import (
    ultimas_versiones_por_fichas,
)

from . import instructor_bp, obtener_fichas


@instructor_bp.route('/')
@login_required
def dashboard():
    ficha_id = request.args.get('ficha_id', type=int)
    if ficha_id:
        return redirect(url_for('instructor.vision_general', ficha_id=ficha_id))
    try:
        return _dashboard_inner()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error cargando el dashboard del instructor.')
        flash('Hubo un problema al cargar el panel. Intenta de nuevo.', 'error')
        return render_template('dashboard.html', fichas=[], cronogramas={},
                               estadisticas_fichas={}, estadisticas_extra={},
                               fases_fichas={}, tyt_fichas={},
                               recomendaciones_fichas={}, resumen_hoy=None)


def _dashboard_inner():
    fichas = obtener_fichas()
    cronogramas = {ficha.id: obtener_cronograma(ficha) for ficha in fichas}

    estadisticas_fichas = {}
    estadisticas_extra = {}
    now = datetime.utcnow()

    if fichas:
        ficha_ids = [f.id for f in fichas]

        # --- Estados de aprendices ---
        rows = db.session.query(
            Aprendiz.ficha_id, Aprendiz.estado, func.count(Aprendiz.id)
        ).filter(Aprendiz.ficha_id.in_(ficha_ids)).group_by(Aprendiz.ficha_id, Aprendiz.estado).all()
        for fid, estado, cnt in rows:
            if fid not in estadisticas_fichas:
                estadisticas_fichas[fid] = {'total': 0, 'activos': 0, 'estados': {}}
            estadisticas_fichas[fid]['estados'][estado] = cnt
            estadisticas_fichas[fid]['total'] += cnt
            if estado in ESTADOS_EN_FORMACION:
                estadisticas_fichas[fid]['activos'] += cnt

        # --- Asistencia ---
        sesiones_count = dict(
            db.session.query(
                SesionAsistencia.ficha_id,
                func.count(func.distinct(SesionAsistencia.id)),
            )
            .join(RegistroAsistencia)
            .filter(SesionAsistencia.ficha_id.in_(ficha_ids))
            .group_by(SesionAsistencia.ficha_id)
            .all()
        )
        faltas_por_ficha = dict(
            db.session.query(
                SesionAsistencia.ficha_id,
                func.count(RegistroAsistencia.id)
            )
            .join(RegistroAsistencia)
            .join(Aprendiz, RegistroAsistencia.aprendiz_id == Aprendiz.id)
            .filter(
                SesionAsistencia.ficha_id.in_(ficha_ids),
                # Solo las faltas sin justificar restan al porcentaje de asistencia.
                RegistroAsistencia.estado == 'FALTA',
                Aprendiz.estado.in_(ESTADOS_EN_FORMACION)
            )
            .group_by(SesionAsistencia.ficha_id).all()
        )

        # --- Tareas ---
        # Aggregate deliveries in the same query. The previous implementation
        # loaded every task and executed two extra queries per task, producing
        # an N+1 cascade on the dashboard.
        tareas_query = db.session.query(
            Tarea.ficha_id,
            Tarea.fecha_limite,
            func.count(Entrega.id),
            func.sum(db.case((Entrega.estado_revision == 'rechazada', 1), else_=0)),
        ).outerjoin(Entrega).filter(Tarea.ficha_id.in_(ficha_ids))
        if not current_user.es_admin:
            tareas_query = tareas_query.filter(Tarea.instructor_id == current_user.id)
        tareas_rows = tareas_query.group_by(Tarea.ficha_id, Tarea.id, Tarea.fecha_limite).all()

        tareas_por_ficha = {
            fid: {'total': 0, 'entregas': 0, 'pendientes': 0}
            for fid in ficha_ids
        }
        for fid, fecha_limite, entregas, rechazadas in tareas_rows:
            data = tareas_por_ficha[fid]
            entregas = entregas or 0
            rechazadas = rechazadas or 0
            data['total'] += 1
            data['entregas'] += entregas
            data['pendientes'] += rechazadas
            if fecha_limite and fecha_limite < now:
                activos = estadisticas_fichas.get(fid, {}).get('activos', 0)
                data['pendientes'] += max(activos - entregas, 0)

        # --- Entregas por calificar (misma regla que la visión general) ---
        por_calificar = dict(
            db.session.query(Tarea.ficha_id, func.count(Entrega.id))
            .join(Entrega, Entrega.tarea_id == Tarea.id)
            .join(Aprendiz, Entrega.aprendiz_id == Aprendiz.id)
            .filter(
                Tarea.ficha_id.in_(ficha_ids),
                Tarea.modalidad == MODALIDAD_EVIDENCIA,
                or_(Entrega.calificada.is_(False), Entrega.estado_revision == 'pendiente'),
                Aprendiz.estado.in_(ESTADOS_EN_FORMACION),
            )
            .group_by(Tarea.ficha_id).all()
        )

        # --- Alertas activas ---
        alertas_activas = dict(
            db.session.query(Alerta.ficha_id, func.count(Alerta.id))
            .filter(Alerta.ficha_id.in_(ficha_ids), Alerta.estado == 'activa')
            .group_by(Alerta.ficha_id).all()
        )

        # --- Juicios evaluativos y avance de certificación ---
        # Un solo agregado por aprendiz alimenta el resumen global y el conteo
        # de certificados, evitando recorrer de nuevo toda la tabla de juicios.
        juicios_por_ficha = {}
        es_aprobado_sql = condicion_aprobado_sql(JuicioEvaluativo.juicio)
        juicios_aprendices_data = db.session.query(
            JuicioEvaluativo.ficha_id,
            JuicioEvaluativo.aprendiz_id,
            func.count(JuicioEvaluativo.id),
            func.sum(db.case((es_aprobado_sql, 1), else_=0)),
        ).join(Aprendiz).filter(
            JuicioEvaluativo.ficha_id.in_(ficha_ids),
            Aprendiz.estado.in_(ESTADOS_EN_FORMACION),
        ).group_by(JuicioEvaluativo.ficha_id, JuicioEvaluativo.aprendiz_id).all()

        certificados_por_ficha = {fid: 0 for fid in ficha_ids}
        for fid, aid, total_cnt, aprobados_cnt in juicios_aprendices_data:
            total_cnt = total_cnt or 0
            aprobados_cnt = aprobados_cnt or 0
            resumen = juicios_por_ficha.setdefault(
                fid, {'total': 0, 'aprobados': 0},
            )
            resumen['total'] += total_cnt
            resumen['aprobados'] += aprobados_cnt
            if total_cnt > 0 and total_cnt == aprobados_cnt:
                certificados_por_ficha[fid] += 1

        # --- Resumen de Competencias ---
        comps_data = db.session.query(
            JuicioEvaluativo.ficha_id,
            JuicioEvaluativo.competencia,
            func.count(JuicioEvaluativo.id),
            func.sum(db.case((es_aprobado_sql, 1), else_=0)),
        ).join(Aprendiz).filter(
            JuicioEvaluativo.ficha_id.in_(ficha_ids),
            Aprendiz.estado.in_(ESTADOS_EN_FORMACION),
        ).group_by(JuicioEvaluativo.ficha_id, JuicioEvaluativo.competencia).all()

        competencias_por_ficha = {}
        for fid, comp, total_cnt, aprobados_cnt in comps_data:
            if not comp or not comp.strip():
                continue
            total_cnt = total_cnt or 0
            aprobados_cnt = aprobados_cnt or 0
            if fid not in competencias_por_ficha:
                competencias_por_ficha[fid] = {}
            competencias_por_ficha[fid][comp] = {
                'total': total_cnt,
                'aprobados': aprobados_cnt,
            }

        top_competencias = {}
        for fid, comps in competencias_por_ficha.items():
            sorted_comps = sorted(
                comps.items(),
                key=lambda x: ((x[1]['aprobados'] / x[1]['total']) if x[1]['total'] > 0 else 0, -x[1]['total'])
            )
            top_competencias[fid] = sorted_comps[:2]

        # --- Notas del observador por ficha ---
        notas_obs_data = db.session.query(
            NotaObservador.ficha_id, NotaObservador.tipo, func.count(NotaObservador.id)
        ).filter(
            NotaObservador.ficha_id.in_(ficha_ids)
        ).group_by(NotaObservador.ficha_id, NotaObservador.tipo).all()

        notas_obs_por_ficha = {}
        for fid, tipo, cnt in notas_obs_data:
            if fid not in notas_obs_por_ficha:
                notas_obs_por_ficha[fid] = {'positiva': 0, 'negativa': 0, 'neutra': 0}
            notas_obs_por_ficha[fid][tipo] = cnt

        # --- Planes de mejoramiento pendientes ---
        planes_pendientes = dict(
            db.session.query(
                PlanMejoramiento.ficha_id, func.count(PlanMejoramiento.id)
            ).filter(
                PlanMejoramiento.ficha_id.in_(ficha_ids),
                PlanMejoramiento.estado == 'pendiente'
            ).group_by(PlanMejoramiento.ficha_id).all()
        )

        # --- Consolidar por ficha ---
        for ficha in fichas:
            fid = ficha.id
            n_ap_total = estadisticas_fichas.get(fid, {}).get('total', 0)
            n_ap = estadisticas_fichas.get(fid, {}).get('activos', 0)
            ses = sesiones_count.get(fid, 0)
            faltas = faltas_por_ficha.get(fid, 0)
            posibles = ses * n_ap
            # Sin sesiones o sin tareas no hay porcentaje: se muestra «Sin datos».
            pct_asistencia = round(((posibles - faltas) / posibles * 100), 1) if posibles else None

            tareas_data = tareas_por_ficha.get(fid, {'total': 0, 'entregas': 0, 'pendientes': 0})
            if tareas_data['total'] and n_ap:
                pct_entregas = round((tareas_data['entregas'] / (tareas_data['total'] * n_ap) * 100))
            else:
                pct_entregas = None

            juicios = juicios_por_ficha.get(fid, {})
            pct_juicios = round((juicios.get('aprobados', 0) / juicios.get('total', 1) * 100)) if juicios.get('total') else 0

            pct_tiempo = int(cronogramas.get(fid, {}).get('porcentaje', 0))

            notas_obs = notas_obs_por_ficha.get(fid, {'positiva': 0, 'negativa': 0, 'neutra': 0})

            estadisticas_extra[fid] = {
                'total_aprendices': n_ap,
                'total_aprendices_incl_inactivos': n_ap_total,
                'sesiones': ses,
                'pct_asistencia': pct_asistencia,
                'tareas_totales': tareas_data['total'],
                'entregas_totales': tareas_data['entregas'],
                'pendientes': tareas_data['pendientes'],
                'por_calificar': por_calificar.get(fid, 0),
                'pct_entregas': pct_entregas,
                'juicios_totales': juicios.get('total', 0),
                'juicios_aprobados': juicios.get('aprobados', 0),
                'pct_juicios': pct_juicios,
                'aprendices_certificados': certificados_por_ficha.get(fid, 0),
                'alertas_activas': alertas_activas.get(fid, 0),
                'pct_tiempo': pct_tiempo,
                'top_competencias': top_competencias.get(fid, []),
                'notas_positivas': notas_obs['positiva'],
                'notas_negativas': notas_obs['negativa'],
                'notas_neutras': notas_obs['neutra'],
                'notas_total': sum(notas_obs.values()),
                'planes_pendientes': planes_pendientes.get(fid, 0),
            }

    cache_planeaciones_prog = {}
    versiones_lote = ultimas_versiones_por_fichas(
        [f.id for f in fichas],
        tipos=[TIPO_PLANEACION, TIPO_REPORTE_JUICIOS],
        solo_procesadas=True,
    ) if fichas else {}

    fases_fichas = {
        ficha.id: obtener_seguimiento_fases_dashboard(
            ficha,
            cronogramas[ficha.id],
            hoy=now.date(),
            cache_programa=cache_planeaciones_prog,
            version_plan=versiones_lote.get((ficha.id, TIPO_PLANEACION)),
            version_reporte=versiones_lote.get((ficha.id, TIPO_REPORTE_JUICIOS)),
        )
        for ficha in fichas
    }

    fichas = ordenar_por_urgencia(fichas, cronogramas, estadisticas_extra, fases_fichas)
    resumen_hoy = resumen_global(fichas, cronogramas, estadisticas_extra)

    from app.services.recomendaciones import obtener_recomendaciones_ficha

    recomendaciones_fichas = {}
    for ficha in fichas:
        fid = ficha.id
        extra = estadisticas_extra.get(fid, {})
        ctx_recom = {
            'fases_data': fases_fichas.get(fid, {}),
            'cronograma': cronogramas.get(fid, {}),
            'extra': {'top_competencias': extra.get('top_competencias', [])},
        }
        recoms = obtener_recomendaciones_ficha(
            fid,
            instructor_id=current_user.id if getattr(current_user, 'is_authenticated', False) else None,
            ahora=now,
            contexto_precalculado=ctx_recom,
            categorias=['fases_cronograma', 'juicios_evaluativos'],
        )
        recomendaciones_fichas[fid] = recoms

    tyt_fichas = {}
    try:
        from flask import g

        from app.tyt.consulta import obtener_seguimiento_por_fichas
        tyt_fichas = obtener_seguimiento_por_fichas(fichas, hoy=now.date())
        if not hasattr(g, '_seguimientos_tyt') or g._seguimientos_tyt is None:
            g._seguimientos_tyt = {}
        g._seguimientos_tyt.update(tyt_fichas)
    except Exception:
        current_app.logger.exception('No se pudo precargar seguimiento TyT en dashboard.')

    return render_template('dashboard.html', fichas=fichas, cronogramas=cronogramas,
                           estadisticas_fichas=estadisticas_fichas,
                           estadisticas_extra=estadisticas_extra,
                           fases_fichas=fases_fichas,
                           tyt_fichas=tyt_fichas,
                           recomendaciones_fichas=recomendaciones_fichas,
                           resumen_hoy=resumen_hoy)
