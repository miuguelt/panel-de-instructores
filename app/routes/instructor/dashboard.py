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

from app import db
from app.models.archivo_ficha import (
    TIPO_PLANEACION,
    TIPO_REPORTE_JUICIOS,
)
from app.services.cronograma import obtener_cronograma
from app.services.estadisticas_fichas import calcular_estadisticas_fichas
from app.services.fases_dashboard import obtener_seguimiento_fases_dashboard
from app.services.prioridad_fichas import ordenar_por_urgencia, resumen_global
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

    now = datetime.utcnow()
    # El administrador ve todas las tareas; el instructor, solo las suyas.
    estadisticas_fichas, estadisticas_extra = calcular_estadisticas_fichas(
        fichas, cronogramas, instructor_id=None if current_user.es_admin else current_user.id, ahora=now,
    )

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
