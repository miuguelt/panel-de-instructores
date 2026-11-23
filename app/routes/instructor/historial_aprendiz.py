"""Historial del aprendiz visto por el instructor."""
from datetime import datetime

from flask import (
    flash,
    redirect,
    render_template,
    url_for,
)
from flask_login import login_required
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from app import db
from app.models.alertas import Alerta, PlanMejoramiento
from app.models.aprendiz import (
    Aprendiz,
)
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.models.ficha import Ficha
from app.models.grupo import GrupoAprendiz
from app.models.insignia import Insignia, InsigniaOtorgada
from app.models.juicio import JuicioEvaluativo
from app.models.observador import NotaObservador
from app.models.tarea import Tarea
from app.services.aseo import resumen_aprendiz
from app.services.asistencia import (
    conteo_asistencia_aprendiz,
    resumen_asistencia_aprendiz,
)
from app.services.evidencias_aprendiz import tareas_del_aprendiz
from app.services.juicios_aprendiz import (
    analizar_juicios,
    competencias_por_tipo,
    deduplicar_juicios,
)
from app.services.permisos import (
    puede_gestionar_ficha,
    tareas_visibles,
)
from app.services.ranking import calcular_ranking
from app.services.reporte_aprendiz import (
    detalle_asistencia,
    resumir_evidencias,
    resumir_seguimiento,
    ultima_actividad,
)

from . import instructor_bp


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

    # La tabla de juicios oficiales muestra todos los registros; las cifras usan
    # los juicios deduplicados, igual que el panel del aprendiz y su PDF.
    unicos = deduplicar_juicios(juicios)
    analisis = analizar_juicios(unicos)
    stats_juicios = analisis['stats_juicios']
    competencias_tipo, resumen_tipos = competencias_por_tipo(unicos)

    instructores = {ficha.instructor}
    instructores.update(v.instructor for v in ficha.instructores_asociados if v.instructor)
    instructores = sorted(instructores, key=lambda i: i.nombre)

    conteo = conteo_asistencia_aprendiz(ficha_id, aprendiz.id)
    pct_asistencia = resumen_asistencia_aprendiz(conteo['total_sesiones'], conteo['faltas_no_justificadas'])['pct']

    # Solo las tareas que el instructor puede consultar, con prórrogas y sin consultas por tarea.
    tareas_estado = tareas_del_aprendiz(ficha_id, aprendiz.id, tareas=tareas_visibles(ficha_id).order_by(Tarea.fecha_limite).all())

    grupos_aprendiz = select(GrupoAprendiz.grupo_id).where(GrupoAprendiz.aprendiz_id == aprendiz.id)
    otorgamientos = InsigniaOtorgada.query.join(Insignia).filter(
        or_(InsigniaOtorgada.aprendiz_id == aprendiz.id, InsigniaOtorgada.grupo_id.in_(grupos_aprendiz)),
        Insignia.ficha_id == ficha_id,
    ).order_by(InsigniaOtorgada.fecha_obtencion.desc()).all()

    filas_ranking, _ = calcular_ranking(ficha_id)
    ranking = next((fila for fila in filas_ranking if fila['aprendiz'].id == aprendiz.id), None)
    aseo = resumen_aprendiz(ficha_id, aprendiz)

    registros = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id, RegistroAsistencia.aprendiz_id == aprendiz.id,
    ).order_by(SesionAsistencia.fecha.desc()).all()
    asistencia = detalle_asistencia(registros)

    alertas_aprendiz = Alerta.query.filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz.id).order_by(Alerta.fecha_generada.desc()).all()
    planes_aprendiz = PlanMejoramiento.query.filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz.id).order_by(PlanMejoramiento.fecha_creacion.desc()).all()

    ultima_asistencia = registros[0].sesion.fecha if registros and registros[0].sesion else None
    ultima_entrega = max((i['entrega'].fecha_entrega for i in tareas_estado if i['entrega'] and i['entrega'].fecha_entrega), default=None)
    resumen_reporte = {
        'generado_en': datetime.now(),
        'total_aprendices_ficha': Aprendiz.query_en_formacion(ficha_id).count(),
        'ultima_actividad': ultima_actividad(analisis['resumen']['ultima_evaluacion'], ultima_asistencia, ultima_entrega),
        'ultima_asistencia': ultima_asistencia,
        'ultima_entrega': ultima_entrega,
        'total_registros_asistencia': len(registros),
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
                           pct_asistencia=pct_asistencia, total_sesiones=conteo['total_sesiones'],
                           total_faltas=conteo['total_faltas'],
                           tareas_estado=tareas_estado, otorgamientos=otorgamientos,
                           ranking=ranking, aseo=aseo,
                           stats_juicios=stats_juicios,
                           competencias_por_tipo=competencias_tipo,
                           resumen_tipos=resumen_tipos,
                           timeline_aprendiz_hist=analisis['timeline'],
                           instructores_aprendiz_hist=analisis['instructores'],
                           resumen_aprendiz_hist=analisis['resumen'],
                           registros_asistencia=asistencia['registros'],
                           estados_asistencia=asistencia['estados'],
                           asistencia_mensual=asistencia['mensual'],
                           faltas_injustificadas=asistencia['faltas_injustificadas'],
                           faltas_justificadas=asistencia['faltas_justificadas'],
                           tareas_resumen=resumir_evidencias(tareas_estado),
                           alertas_aprendiz=alertas_aprendiz,
                           planes_aprendiz=planes_aprendiz,
                           seguimiento_resumen=resumir_seguimiento(alertas_aprendiz, planes_aprendiz),
                           resumen_reporte=resumen_reporte)
