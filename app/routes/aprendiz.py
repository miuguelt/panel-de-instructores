from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, abort, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import current_user
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload
from app import db, limiter
from app.models.ficha import Ficha
from app.models.aprendiz import Aprendiz
from app.models.asistencia import (
    RegistroAsistencia,
    SesionAsistencia,
    CAUSALES_JUSTIFICADAS,
)
from app.models.tarea import Tarea, Entrega
from app.models.material import MaterialFicha
from app.models.alertas import ConfiguracionAlertas
from app.models.insignia import Insignia, InsigniaOtorgada
from app.models.observador import NotaObservador
from app.services.ranking import (
    actualizar_participacion_ficha,
    calcular_ranking,
    mensaje_motivacional,
)
from app.models.alertas import Alerta, Notificacion, PlanMejoramiento
from app.services.alertas import (
    actualizar_alertas_ficha,
    crear_recordatorios_aprendiz,
    registrar_notificacion,
    vencer_planes_pendientes,
)
from app.services.cronograma import obtener_cronograma
from app.services.asistencia import mapa_asistencia_por_fecha
from app.services.aseo import resumen_aprendiz
from app.services.archivos import (
    ArchivoService,
    ErrorArchivo,
    TiposCarpeta,
    nombre_original_desde_ruta,
    resolver_archivo_subido,
)
from app.services.permisos import puede_gestionar_ficha, puede_gestionar_tarea
from datetime import datetime

aprendiz_bp = Blueprint('aprendiz', __name__, template_folder='../templates/aprendiz')


def verificar_acceso(ficha_id):
    documento = request.form.get('documento') or request.args.get('documento', '')
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        return None, None, 'Ficha no encontrada.'

    aprendiz = Aprendiz.query.filter_by(documento=documento.strip(), ficha_id=ficha_id).first()
    if not aprendiz:
        return ficha, None, 'No te encontramos en esta ficha. Verifica tu número de documento.'

    session['aprendiz_documento'] = aprendiz.documento
    session['aprendiz_ficha_id'] = ficha_id
    return ficha, aprendiz, None


def _documento_aprendiz_para_ficha(ficha_id):
    """Obtiene la identidad activa sin permitir cambiarla desde un POST."""
    documento_formulario = (request.form.get('documento') or '').strip()
    documento_sesion = (session.get('aprendiz_documento') or '').strip()
    ficha_sesion = session.get('aprendiz_ficha_id')

    if ficha_sesion == ficha_id and documento_sesion:
        if documento_formulario and documento_formulario != documento_sesion:
            return None
        return documento_sesion
    return documento_formulario or documento_sesion


@aprendiz_bp.route('/<int:ficha_id>', methods=['GET', 'POST'])
@limiter.limit("30 per minute")
def vista_aprendiz(ficha_id):
    if request.method == 'POST':
        ficha, aprendiz, error = verificar_acceso(ficha_id)
        if error:
            flash(error, 'error')
            return render_template('acceso.html', ficha=ficha, ficha_id=ficha_id)
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))

    session.pop('aprendiz_documento', None)
    session.pop('aprendiz_ficha_id', None)
    ficha = db.session.get(Ficha, ficha_id)
    return render_template('acceso.html', ficha=ficha, ficha_id=ficha_id)


@aprendiz_bp.route('/<int:ficha_id>/panel')
@limiter.limit("60 per minute")
def panel(ficha_id):
    documento = session.get('aprendiz_documento', '')
    url_documento = request.args.get('documento', '')
    if url_documento and url_documento != documento:
        documento = url_documento
        session['aprendiz_documento'] = documento
        session['aprendiz_ficha_id'] = ficha_id
    if url_documento:
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))

    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))

    aprendiz = Aprendiz.query.filter_by(documento=documento, ficha_id=ficha_id).first()
    if not aprendiz:
        flash('Documento no valido para esta ficha.', 'error')
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))

    actualizar_alertas_ficha(ficha_id)
    crear_recordatorios_aprendiz(ficha_id, aprendiz.id)
    vencer_planes_pendientes()

    total_sesiones = SesionAsistencia.query.join(RegistroAsistencia).filter(SesionAsistencia.ficha_id == ficha_id).distinct().count()
    total_faltas = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        RegistroAsistencia.aprendiz_id == aprendiz.id,
        RegistroAsistencia.estado.in_(['FALTA', 'FALTA_JUSTIFICADA', 'EXCUSA_MEDICA']),
    ).count()
    faltas_no_justificadas = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        RegistroAsistencia.aprendiz_id == aprendiz.id,
        RegistroAsistencia.estado == 'FALTA',
    ).count()
    faltas_justificadas = total_faltas - faltas_no_justificadas

    config = ConfiguracionAlertas.query.filter_by(ficha_id=ficha_id).first()
    if config:
        if faltas_no_justificadas >= config.umbral_rojo:
            nivel_alerta = 'rojo'
        elif faltas_no_justificadas >= config.umbral_amarillo:
            nivel_alerta = 'amarillo'
        else:
            nivel_alerta = 'verde'
    else:
        nivel_alerta = 'verde'

    pct_asistencia = ((total_sesiones - total_faltas) / total_sesiones * 100) if total_sesiones else 100

    actualizar_participacion_ficha(ficha_id)

    # Las insignias nuevas se marcan aqui, antes de armar el resto de la vista:
    # este es el ultimo commit del request y un commit expira los objetos vivos
    # de la sesion, de modo que todo lo cargado despues llega intacto a la
    # plantilla en vez de recargarse fila por fila durante el render.
    otorgamientos = InsigniaOtorgada.query.join(Insignia).filter(
        InsigniaOtorgada.aprendiz_id == aprendiz.id,
        Insignia.ficha_id == ficha_id,
    ).order_by(InsigniaOtorgada.fecha_obtencion.desc()).all()
    ids_nuevas = {item.id for item in otorgamientos if not item.notificada}
    if ids_nuevas:
        for item in otorgamientos:
            if item.id in ids_nuevas:
                item.notificada = True
        db.session.commit()
        otorgamientos = InsigniaOtorgada.query.join(Insignia).options(
            joinedload(InsigniaOtorgada.insignia)
        ).filter(
            InsigniaOtorgada.aprendiz_id == aprendiz.id,
            Insignia.ficha_id == ficha_id,
        ).order_by(InsigniaOtorgada.fecha_obtencion.desc()).all()
    ids_obtenidas = {item.insignia_id for item in otorgamientos}
    nuevas_insignias = [item for item in otorgamientos if item.id in ids_nuevas]
    catalogo_insignias = Insignia.query.filter_by(
        ficha_id=ficha_id, activa=True
    ).order_by(Insignia.nombre).all()

    tareas = Tarea.query.filter_by(ficha_id=ficha_id).order_by(Tarea.fecha_limite).all()
    # Todas las entregas del aprendiz en una consulta: recorrer tarea por tarea
    # costaba un SELECT por actividad de la ficha.
    entregas_aprendiz = {}
    if tareas:
        for entrega in (
            Entrega.query
            .filter(
                Entrega.aprendiz_id == aprendiz.id,
                Entrega.tarea_id.in_([tarea.id for tarea in tareas]),
            )
            .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
            .all()
        ):
            entregas_aprendiz.setdefault(entrega.tarea_id, entrega)

    tareas_estado = []
    for tarea in tareas:
        entrega = entregas_aprendiz.get(tarea.id)
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

    filas_ranking, config_ranking = calcular_ranking(ficha_id)
    fila_propia = next(
        (fila for fila in filas_ranking if fila['aprendiz'].id == aprendiz.id),
        None,
    )
    if config_ranking.modo_visibilidad == 'publico':
        ranking_visible = filas_ranking
    else:
        top_cinco = filas_ranking[:5]
        ranking_visible = list(top_cinco)
        if fila_propia and fila_propia not in ranking_visible:
            ranking_visible.append(fila_propia)

    punto_siguiente = None
    if fila_propia and fila_propia['posicion'] > 1:
        anterior = filas_ranking[fila_propia['posicion'] - 2]
        punto_siguiente = max(
            round(anterior['puntaje_total'] - fila_propia['puntaje_total'] + 0.01, 2),
            0.01,
        )

    alertas_activas = Alerta.query.filter_by(
        ficha_id=ficha_id, aprendiz_id=aprendiz.id, estado='activa'
    ).order_by(Alerta.nivel.desc(), Alerta.fecha_generada.desc()).all()
    notificaciones_aprendiz = Notificacion.query.filter_by(
        destinatario_tipo='aprendiz', destinatario_id=aprendiz.id,
        ficha_id=ficha_id, leida=False,
    ).order_by(Notificacion.fecha_creada.desc()).all()
    inasistencias_pendientes = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        RegistroAsistencia.aprendiz_id == aprendiz.id,
        RegistroAsistencia.estado == 'FALTA',
    ).order_by(SesionAsistencia.fecha.desc()).all()
    # El observador es la evidencia con la que se sustenta un plan de
    # mejoramiento o un comité: el aprendiz debe poder leer lo que se registró
    # sobre él, y con qué fecha, sin pedirlo. joinedload del autor porque la
    # vista muestra quién dejó cada constancia.
    notas_observador = (
        NotaObservador.query
        .options(joinedload(NotaObservador.autor))
        .filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz.id)
        .order_by(NotaObservador.fecha.desc(), NotaObservador.id.desc())
        .all()
    )
    planes_mejoramiento = (
        PlanMejoramiento.query
        .filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz.id)
        .order_by(PlanMejoramiento.fecha_creacion.desc(), PlanMejoramiento.id.desc())
        .all()
    )
    aseo = resumen_aprendiz(ficha_id, aprendiz)

    # El aprendiz solo recibe sus propios registros; el mismo mapa de estados
    # que usa el modal del instructor evita colores distintos entre roles.
    registros_calendario = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        RegistroAsistencia.aprendiz_id == aprendiz.id,
    ).order_by(SesionAsistencia.fecha.asc(), RegistroAsistencia.id.asc()).all()
    asistencia_calendario = mapa_asistencia_por_fecha(registros_calendario)
    causales = dict(CAUSALES_JUSTIFICADAS)
    for evento in asistencia_calendario.values():
        evento['causal'] = causales.get(
            evento.pop('causal_justificacion', ''), ''
        )

    # Juicios Evaluativos Oficiales
    from app.models.juicio import JuicioEvaluativo
    juicios_raw = JuicioEvaluativo.query.filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz.id).all()

    # Deduplicar por (competencia, resultado_aprendizaje) conservando el mejor registro
    juicios_dedup = {}
    for j in juicios_raw:
        key = ((j.competencia or '').strip().upper(), (j.resultado_aprendizaje or '').strip().upper())
        if key not in juicios_dedup:
            juicios_dedup[key] = j
        else:
            existing = juicios_dedup[key]
            es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
            existing_aprobado = bool(existing.juicio and 'APROBADO' in existing.juicio.upper() and 'AUN NO' not in existing.juicio.upper())
            if es_aprobado and not existing_aprobado:
                juicios_dedup[key] = j
            elif es_aprobado == existing_aprobado and j.funcionario_registro and not existing.funcionario_registro:
                juicios_dedup[key] = j

    juicios = list(juicios_dedup.values())

    stats_juicios = {
        'total': 0, 'aprobados': 0,
        'tecnica': 0, 'tecnica_aprobada': 0,
        'transversal': 0, 'transversal_aprobada': 0,
        'ingles': 0, 'ingles_aprobada': 0,
    }
    juicios_pendientes = []
    juicios_aprobados = []

    for j in juicios:
        stats_juicios['total'] += 1
        es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
        if es_aprobado:
            stats_juicios['aprobados'] += 1
            juicios_aprobados.append(j)
        else:
            juicios_pendientes.append(j)

        tipo = j.tipo_competencia or 'tecnica'
        stats_juicios[tipo] += 1
        if es_aprobado:
            stats_juicios[f"{tipo}_aprobada"] += 1

    stats_juicios['pct_total'] = round((stats_juicios['aprobados'] / stats_juicios['total'] * 100)) if stats_juicios['total'] > 0 else 0
    stats_juicios['pct_tecnica'] = round((stats_juicios['tecnica_aprobada'] / stats_juicios['tecnica'] * 100)) if stats_juicios['tecnica'] > 0 else 0
    stats_juicios['pct_transversal'] = round((stats_juicios['transversal_aprobada'] / stats_juicios['transversal'] * 100)) if stats_juicios['transversal'] > 0 else 0
    stats_juicios['pct_ingles'] = round((stats_juicios['ingles_aprobada'] / stats_juicios['ingles'] * 100)) if stats_juicios['ingles'] > 0 else 0

    # Evaluadores únicos para este aprendiz (excluye cédulas numéricas)
    evaluadores_set = set()
    for j in juicios:
        if j.funcionario_registro and any(c.isalpha() for c in j.funcionario_registro):
            evaluadores_set.add(j.funcionario_registro)
    evaluadores_lista = sorted(evaluadores_set)

    # ---- NUEVAS ESTADÍSTICAS PARA EL APRENDIZ ----

    # Stats por competencia para este aprendiz agrupadas con sus RAPs
    competencias_aprendiz = {}
    for j in juicios:
        comp = j.competencia or 'Sin nombre'
        if comp not in competencias_aprendiz:
            competencias_aprendiz[comp] = {
                'nombre': comp,
                'tipo': j.tipo_competencia or 'tecnica',
                'total': 0, 'aprobados': 0, 'pendientes': 0,
                'fecha_ultima': j.fecha_juicio,
                'raps': []
            }

        datos_comp = competencias_aprendiz[comp]
        datos_comp['total'] += 1
        es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
        if es_aprobado:
            datos_comp['aprobados'] += 1
        else:
            datos_comp['pendientes'] += 1

        if j.fecha_juicio and (not datos_comp['fecha_ultima'] or j.fecha_juicio > datos_comp['fecha_ultima']):
            datos_comp['fecha_ultima'] = j.fecha_juicio

        datos_comp['raps'].append({
            'rap': j.resultado_aprendizaje or 'Sin descripción',
            'juicio': j.juicio or 'POR EVALUAR',
            'es_aprobado': es_aprobado,
            'fecha': j.fecha_juicio.strftime('%d/%m/%Y') if j.fecha_juicio else 'Pendiente',
            'evaluador': j.funcionario_registro or 'Sin registro'
        })

    for comp in competencias_aprendiz.values():
        comp['pct'] = round((comp['aprobados'] / comp['total'] * 100)) if comp['total'] > 0 else 0
        if comp['pct'] == 100:
            comp['estado_label'] = 'Completada'
        elif comp['pct'] > 0:
            comp['estado_label'] = 'En Progreso'
        else:
            comp['estado_label'] = 'Pendiente'

    competencias_aprendiz_orden = sorted(competencias_aprendiz.values(), key=lambda x: (x['tipo'], x['nombre']))

    # Timeline de evaluaciones para este aprendiz
    timeline_aprendiz = {}
    for j in juicios:
        if j.fecha_juicio:
            mes = j.fecha_juicio.strftime('%Y-%m')
            if mes not in timeline_aprendiz:
                timeline_aprendiz[mes] = {'total': 0, 'aprobados': 0}
            timeline_aprendiz[mes]['total'] += 1
            es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
            if es_aprobado:
                timeline_aprendiz[mes]['aprobados'] += 1
    timeline_aprendiz_orden = sorted(timeline_aprendiz.items())

    # Stats por instructor para este aprendiz
    instructores_aprendiz = {}
    for j in juicios:
        func = j.funcionario_registro or 'Sin registro'
        if func not in instructores_aprendiz:
            instructores_aprendiz[func] = {'total': 0, 'aprobados': 0, 'pendientes': 0}
        instructores_aprendiz[func]['total'] += 1
        es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
        if es_aprobado:
            instructores_aprendiz[func]['aprobados'] += 1
        else:
            instructores_aprendiz[func]['pendientes'] += 1

    for func in instructores_aprendiz.values():
        func['pct'] = round((func['aprobados'] / func['total'] * 100)) if func['total'] > 0 else 0

    # Resumen extendido para el aprendiz
    fechas_juicios_ap = [j.fecha_juicio for j in juicios if j.fecha_juicio]
    stats_resumen_aprendiz = {
        'total_competencias': len(competencias_aprendiz),
        'total_instructores': len(instructores_aprendiz),
        'promedio_por_instructor': round(stats_juicios['total'] / len(instructores_aprendiz), 1) if instructores_aprendiz else 0,
        'primera_evaluacion': min(fechas_juicios_ap) if fechas_juicios_ap else None,
        'ultima_evaluacion': max(fechas_juicios_ap) if fechas_juicios_ap else None,
        'dias_entre_evaluaciones': (
            (max(fechas_juicios_ap) - min(fechas_juicios_ap)).days
            if len(fechas_juicios_ap) >= 2 else 0
        ),
    }
    
    # Sin commit aqui: desde que se marcaron las insignias no hay escrituras
    # pendientes, y confirmar justo antes del render expiraba tareas, entregas
    # e insignias, que la plantilla volvia a leer una por una.

    cronograma = obtener_cronograma(ficha)
    return render_template('panel.html',
                           ficha=ficha,
                           aprendiz=aprendiz,
                           total_sesiones=total_sesiones,
                           total_faltas=total_faltas,
                           faltas_no_justificadas=faltas_no_justificadas,
                           faltas_justificadas=faltas_justificadas,
                           pct_asistencia=pct_asistencia,
                           nivel_alerta=nivel_alerta,
                           config_alertas=config,
                           tareas_estado=tareas_estado,
                           fila_propia=fila_propia,
                           ranking_visible=ranking_visible,
                           total_ranking=len(filas_ranking),
                           punto_siguiente=punto_siguiente,
                           config_ranking=config_ranking,
                           mensaje_ranking=mensaje_motivacional(fila_propia) if fila_propia else '',
                           catalogo_insignias=catalogo_insignias,
                           ids_obtenidas=ids_obtenidas,
                           nuevas_insignias=nuevas_insignias,
                           otorgamientos=otorgamientos,
                           alertas_activas=alertas_activas,
                           notas_observador=notas_observador,
                           planes_mejoramiento=planes_mejoramiento,
                           notificaciones=notificaciones_aprendiz,
                           inasistencias_pendientes=inasistencias_pendientes,
                           asistencia_calendario=asistencia_calendario,
                           cronograma=cronograma,
                           aseo=aseo,
                           stats_juicios=stats_juicios,
                           juicios_pendientes=juicios_pendientes,
                           juicios_aprobados=juicios_aprobados,
                           competencias_aprendiz=competencias_aprendiz_orden,
                           juicios=juicios,
                           evaluadores=evaluadores_lista,
                           timeline_aprendiz=timeline_aprendiz_orden,
                           instructores_aprendiz=instructores_aprendiz,
                           resumen_aprendiz=stats_resumen_aprendiz)


@aprendiz_bp.route('/<int:ficha_id>/descargar-reporte')
@limiter.limit("10 per minute")
def descargar_reporte(ficha_id):
    documento = session.get('aprendiz_documento', '') or request.args.get('documento', '')
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        abort(404)
        
    aprendiz = Aprendiz.query.filter_by(documento=documento, ficha_id=ficha_id).first()
    if not aprendiz:
        abort(404)
        
    total_sesiones = SesionAsistencia.query.join(RegistroAsistencia).filter(SesionAsistencia.ficha_id == ficha_id).distinct().count()
    total_faltas = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        RegistroAsistencia.aprendiz_id == aprendiz.id,
        RegistroAsistencia.estado.in_(['FALTA', 'FALTA_JUSTIFICADA', 'EXCUSA_MEDICA']),
    ).count()
    faltas_no_justificadas = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        RegistroAsistencia.aprendiz_id == aprendiz.id,
        RegistroAsistencia.estado == 'FALTA',
    ).count()
    faltas_justificadas = total_faltas - faltas_no_justificadas
    pct_asistencia = ((total_sesiones - total_faltas) / total_sesiones * 100) if total_sesiones > 0 else 100
    
    config = ConfiguracionAlertas.query.filter_by(ficha_id=ficha_id).first()
    if config:
        if faltas_no_justificadas >= config.umbral_rojo:
            nivel_alerta = 'Rojo (Crítico)'
        elif faltas_no_justificadas >= config.umbral_amarillo:
            nivel_alerta = 'Amarillo (En Riesgo)'
        else:
            nivel_alerta = 'Verde (Al Día)'
    else:
        nivel_alerta = 'Verde (Al Día)'

    tareas = Tarea.query.filter_by(ficha_id=ficha_id).order_by(Tarea.fecha_limite).all()
    tareas_estado = []
    now = datetime.utcnow()
    for tarea in tareas:
        entrega = (
            Entrega.query
            .filter_by(tarea_id=tarea.id, aprendiz_id=aprendiz.id)
            .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
            .first()
        )
        if entrega:
            if entrega.estado_revision == 'rechazada':
                estado = 'Corrección'
            elif entrega.entregada_a_tiempo:
                estado = 'Entregada'
            else:
                estado = 'Retraso'
        elif tarea.fecha_limite and tarea.fecha_limite < now:
            estado = 'Vencida'
        else:
            estado = 'Pendiente'
        tareas_estado.append({'tarea': tarea.titulo, 'estado': estado, 'calificacion': entrega.calificacion if entrega and entrega.calificacion else 'N/A'})

    from app.models.juicio import JuicioEvaluativo
    juicios = JuicioEvaluativo.query.filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz.id).all()
    stats_juicios = {
        'total': 0, 'aprobados': 0,
        'tecnica': 0, 'tecnica_aprobada': 0,
        'transversal': 0, 'transversal_aprobada': 0,
        'ingles': 0, 'ingles_aprobada': 0,
    }
    competencias_agrupadas = {}
    for j in juicios:
        stats_juicios['total'] += 1
        es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
        if es_aprobado:
            stats_juicios['aprobados'] += 1
        tipo = j.tipo_competencia or 'tecnica'
        stats_juicios[tipo] += 1
        if es_aprobado:
            stats_juicios[f"{tipo}_aprobada"] += 1
        comp = j.competencia or 'Sin nombre'
        if comp not in competencias_agrupadas:
            competencias_agrupadas[comp] = {
                'nombre': comp, 'tipo': tipo,
                'total': 0, 'aprobados': 0,
                'raps': []
            }
        competencias_agrupadas[comp]['total'] += 1
        if es_aprobado:
            competencias_agrupadas[comp]['aprobados'] += 1
        competencias_agrupadas[comp]['raps'].append({
            'rap': j.resultado_aprendizaje or 'Sin descripción',
            'juicio': j.juicio or 'POR EVALUAR',
            'fecha': j.fecha_juicio.strftime('%d/%m/%Y') if j.fecha_juicio else 'Pendiente',
            'evaluador': j.funcionario_registro or 'Sin registro'
        })
    stats_juicios['pct_total'] = round((stats_juicios['aprobados'] / stats_juicios['total'] * 100)) if stats_juicios['total'] > 0 else 0
    stats_juicios['pct_tecnica'] = round((stats_juicios['tecnica_aprobada'] / stats_juicios['tecnica'] * 100)) if stats_juicios['tecnica'] > 0 else 0
    stats_juicios['pct_transversal'] = round((stats_juicios['transversal_aprobada'] / stats_juicios['transversal'] * 100)) if stats_juicios['transversal'] > 0 else 0
    stats_juicios['pct_ingles'] = round((stats_juicios['ingles_aprobada'] / stats_juicios['ingles'] * 100)) if stats_juicios['ingles'] > 0 else 0
    competencias_lista = sorted(competencias_agrupadas.values(), key=lambda x: (x['tipo'], x['nombre']))

    otorgamientos = InsigniaOtorgada.query.join(Insignia).filter(
        InsigniaOtorgada.aprendiz_id == aprendiz.id,
        Insignia.ficha_id == ficha_id,
    ).order_by(InsigniaOtorgada.fecha_obtencion.desc()).all()

    return _generar_pdf_reporte_aprendiz(ficha, aprendiz, total_sesiones, total_faltas, faltas_justificadas, faltas_no_justificadas, pct_asistencia, nivel_alerta, tareas_estado, stats_juicios, competencias_lista, otorgamientos)

def _generar_pdf_reporte_aprendiz(ficha, aprendiz, total_sesiones, total_faltas, faltas_justificadas, faltas_no_justificadas, pct_asistencia, nivel_alerta, tareas_estado, stats_juicios=None, competencias_lista=None, otorgamientos=None):
    from app.helpers import strip_document_id
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    import io

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    styles['Title'].alignment = TA_CENTER
    styles['Normal'].alignment = TA_CENTER
    styles['Heading2'].alignment = TA_CENTER
    style_left = ParagraphStyle('LeftAlign', parent=styles['Normal'], alignment=TA_LEFT, spaceAfter=6)
    style_rap = ParagraphStyle('RAP', parent=styles['Normal'], alignment=TA_LEFT, fontSize=9, spaceAfter=4, leftIndent=10)
    style_comp_label = ParagraphStyle('CompLabel', parent=styles['Normal'], alignment=TA_LEFT, fontSize=10, spaceAfter=2, spaceBefore=8)
    elements = []

    elements.append(Paragraph(f'Reporte Académico - {aprendiz.nombre} {aprendiz.apellidos}', styles['Title']))
    elements.append(Paragraph(f'Ficha: {ficha.codigo} - {ficha.nombre_programa}', styles['Normal']))
    elements.append(Spacer(1, 12))
    
    elements.append(Paragraph('Resumen de Asistencia', styles['Heading2']))
    datos_asistencia = [
        ['Total Sesiones', 'Faltas Injustificadas', 'Faltas Justificadas', '% Asistencia', 'Alerta'],
        [str(total_sesiones), str(faltas_no_justificadas), str(faltas_justificadas), f'{pct_asistencia:.1f}%', nivel_alerta]
    ]
    ancho_util = doc.width
    t_asistencia = Table(datos_asistencia, colWidths=[ancho_util * 0.2, ancho_util * 0.2, ancho_util * 0.2, ancho_util * 0.2, ancho_util * 0.2], hAlign='CENTER')
    t_asistencia.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#39A900')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
    ]))
    elements.append(t_asistencia)
    elements.append(Spacer(1, 20))
    
    elements.append(Paragraph('Estado de Tareas', styles['Heading2']))
    if tareas_estado:
        datos_tareas = [['Tarea', 'Estado', 'Calificación']]
        for t in tareas_estado:
            datos_tareas.append([t['tarea'], t['estado'], str(t['calificacion'])])
            
        t_tareas = Table(datos_tareas, colWidths=[ancho_util * 0.5, ancho_util * 0.25, ancho_util * 0.25], hAlign='CENTER')
        t_tareas.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#39A900')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        elements.append(t_tareas)
    else:
        elements.append(Paragraph('No hay tareas registradas.', styles['Normal']))
    elements.append(Spacer(1, 20))

    # ---- Juicios Evaluativos ----
    if stats_juicios and stats_juicios['total'] > 0:
        elements.append(Paragraph('Juicios Evaluativos', styles['Heading2']))
        datos_juicios_resumen = [
            ['Total Juicios', 'Aprobados', '% Global'],
            [str(stats_juicios['total']), str(stats_juicios['aprobados']), f"{stats_juicios['pct_total']}%"],
        ]
        t_juicios_resumen = Table(datos_juicios_resumen, colWidths=[ancho_util * 0.33, ancho_util * 0.33, ancho_util * 0.33], hAlign='CENTER')
        t_juicios_resumen.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4f46e5')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        elements.append(t_juicios_resumen)
        elements.append(Spacer(1, 8))

        datos_desglose = [['Tipo', 'Aprobados', 'Total', '%']]
        tipos = [('Técnica', 'tecnica'), ('Transversal', 'transversal'), ('Inglés', 'ingles')]
        for label, key in tipos:
            total = stats_juicios.get(key, 0)
            aprobados = stats_juicios.get(f'{key}_aprobada', 0)
            pct = stats_juicios.get(f'pct_{key}', 0)
            if total > 0:
                datos_desglose.append([label, str(aprobados), str(total), f'{pct}%'])
        if len(datos_desglose) > 1:
            t_desglose = Table(datos_desglose, colWidths=[ancho_util * 0.25, ancho_util * 0.25, ancho_util * 0.25, ancho_util * 0.25], hAlign='CENTER')
            t_desglose.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e7ff')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#3730a3')),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8faff')]),
            ]))
            elements.append(t_desglose)
        elements.append(Spacer(1, 16))

        # Detalle por competencia
        if competencias_lista:
            elements.append(Paragraph('Detalle por Competencia', styles['Heading2']))
            for comp in competencias_lista:
                pct_comp = round((comp['aprobados'] / comp['total'] * 100)) if comp['total'] > 0 else 0
                estado_label = 'Completada' if pct_comp == 100 else ('En Progreso' if pct_comp > 0 else 'Pendiente')
                tipo_tag = {'tecnica': 'Técnica', 'transversal': 'Transversal', 'ingles': 'Inglés'}.get(comp['tipo'], comp['tipo'])
                label_text = f'<b>{comp["nombre"]}</b>  |  {tipo_tag}  |  {comp["aprobados"]}/{comp["total"]} RAPs ({pct_comp}%)  |  {estado_label}'
                elements.append(Paragraph(label_text, style_comp_label))
                rap_data = [['Resultado de Aprendizaje', 'Juicio', 'Fecha', 'Evaluador']]
                for rap in comp['raps']:
                    rap_data.append([
                        Paragraph(rap['rap'], style_rap),
                        rap['juicio'],
                        rap['fecha'],
                        strip_document_id(rap['evaluador'])
                    ])
                col_w = [ancho_util * 0.30, ancho_util * 0.20, ancho_util * 0.15, ancho_util * 0.35]
                t_rap = Table(rap_data, colWidths=col_w, hAlign='CENTER')
                t_rap.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0fdf4')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#166534')),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('ALIGN', (0, 1), (0, -1), 'LEFT'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fafafa')]),
                ]))
                elements.append(t_rap)
                elements.append(Spacer(1, 8))

    # ---- Logros ----
    if otorgamientos:
        elements.append(Paragraph('Logros y Reconocimientos', styles['Heading2']))
        logros_data = [['Insignia', 'Descripción', 'Fecha']]
        for o in otorgamientos:
            logros_data.append([
                f'{o.insignia.icono} {o.insignia.nombre}',
                o.insignia.descripcion,
                o.fecha_obtencion.strftime('%d/%m/%Y') if o.fecha_obtencion else '-',
            ])
        t_logros = Table(logros_data, colWidths=[ancho_util * 0.25, ancho_util * 0.50, ancho_util * 0.25], hAlign='CENTER')
        t_logros.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fef3c7')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#92400e')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fffbeb')]),
        ]))
        elements.append(t_logros)

    doc.build(elements)
    buffer.seek(0)

    from flask import send_file
    return send_file(buffer, mimetype='application/pdf', as_attachment=True,
                     download_name=f'reporte_{ficha.codigo}.pdf')


@aprendiz_bp.route('/<int:ficha_id>/justificar/<int:registro_id>', methods=['POST'])
@limiter.limit("10 per minute")
def adjuntar_soporte_inasistencia(ficha_id, registro_id):
    documento = (
        request.form.get('documento')
        or session.get('aprendiz_documento', '')
    ).strip()
    aprendiz = Aprendiz.query.filter_by(documento=documento, ficha_id=ficha_id).first()
    registro = db.session.get(RegistroAsistencia, registro_id)
    if not aprendiz or not registro or registro.aprendiz_id != aprendiz.id or registro.sesion.ficha_id != ficha_id:
        flash('No encontramos esa inasistencia para tu ficha.', 'error')
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))

    archivo = request.files.get('soporte')
    nota = request.form.get('nota', '').strip()
    if (not archivo or not archivo.filename) and not nota:
        flash('Adjunta un soporte o escribe una nota para que tu instructor pueda revisarla.', 'error')
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))

    if archivo and archivo.filename:
        try:
            resultado = ArchivoService.guardar(
                archivo=archivo,
                carpeta=TiposCarpeta.JUSTIFICACIONES,
                prefijo_extra=f'{aprendiz.documento}_inasistencia_{registro.id}',
            )
            registro.soporte_url = resultado.url
        except ErrorArchivo as exc:
            flash(str(exc), 'error')
            return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))
    if nota:
        registro.nota = nota
    db.session.commit()
    actualizar_alertas_ficha(ficha_id)
    flash('Soporte enviado. Tu instructor revisará la justificación.', 'success')
    return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))


@aprendiz_bp.route('/<int:ficha_id>/subir-evidencia/<int:tarea_id>', methods=['POST'])
@limiter.limit("10 per minute")
def subir_evidencia(ficha_id, tarea_id):
    documento = _documento_aprendiz_para_ficha(ficha_id)
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))

    if not documento:
        flash('La identidad del aprendiz no es válida para esta sesión.', 'error')
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))

    aprendiz = Aprendiz.query.filter_by(documento=documento, ficha_id=ficha_id).first()
    if not aprendiz:
        flash('Documento no valido.', 'error')
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))

    tarea = db.session.get(Tarea, tarea_id)
    if not tarea or tarea.ficha_id != ficha_id:
        flash('Tarea no encontrada.', 'error')
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))

    if tarea.es_actividad_clase:
        # La actividad se verifica en el aula: aceptar archivos aquí crearía
        # una evidencia que el instructor no espera revisar.
        flash('Esta actividad se revisa en clase; no requiere que subas nada.', 'error')
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))

    enlace_repo = request.form.get('enlace_repositorio', '').strip()
    archivo = request.files.get('archivo_evidencia')
    entrega_existente = (
        Entrega.query
        .filter_by(tarea_id=tarea_id, aprendiz_id=aprendiz.id)
        .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
        .first()
    )

    tiene_archivo_previo = bool(entrega_existente and entrega_existente.archivo_url)
    tiene_nuevo_archivo = bool(archivo and archivo.filename)
    tiene_archivo = tiene_nuevo_archivo or tiene_archivo_previo

    if tarea.requiere_archivo and not tiene_archivo:
        flash('Esta tarea requiere adjuntar un archivo de evidencia.', 'error')
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))

    if not tiene_archivo and not enlace_repo:
        flash('Debes subir un archivo o indicar un enlace.', 'error')
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))

    archivo_url = None
    if tiene_nuevo_archivo:
        try:
            resultado = ArchivoService.guardar(
                archivo=archivo,
                carpeta=TiposCarpeta.ENTREGAS,
                subcarpeta=(
                    f'ficha_{ficha_id}/'
                    f'instructor_{tarea.instructor_id}/'
                    f'aprendiz_{aprendiz.id}/'
                    f'tarea_{tarea.id}'
                ),
                prefijo_extra=f'tarea_{tarea_id}',
            )
            archivo_url = resultado.url
        except ErrorArchivo as exc:
            flash(str(exc), 'error')
            return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))

    if entrega_existente:
        if archivo_url:
            entrega_existente.archivo_url = archivo_url
        if 'enlace_repositorio' in request.form:
            entrega_existente.enlace_repositorio = enlace_repo or None
        entrega_existente.fecha_entrega = datetime.utcnow()
        entrega_existente.calificada = False
        entrega_existente.estado_revision = 'pendiente'
        entrega_existente.revisada_en = None
    else:
        entrega = Entrega(
            tarea_id=tarea_id,
            aprendiz_id=aprendiz.id,
            archivo_url=archivo_url,
            enlace_repositorio=enlace_repo or None,
        )
        db.session.add(entrega)

    try:
        db.session.commit()
    except IntegrityError:
        # La restricción única evita dos entregas para la misma tarea y
        # aprendiz. Si dos solicitudes llegaron al mismo tiempo, actualiza
        # el registro canónico en lugar de dejar datos ambiguos.
        db.session.rollback()
        entrega_existente = (
            Entrega.query
            .filter_by(tarea_id=tarea.id, aprendiz_id=aprendiz.id)
            .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
            .first()
        )
        if not entrega_existente:
            flash('No fue posible guardar la evidencia. Intenta nuevamente.', 'error')
            return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))
        if archivo_url:
            entrega_existente.archivo_url = archivo_url
        entrega_existente.enlace_repositorio = enlace_repo or None
        entrega_existente.fecha_entrega = datetime.utcnow()
        entrega_existente.calificada = False
        entrega_existente.estado_revision = 'pendiente'
        entrega_existente.revisada_en = None
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        if archivo_url:
            ArchivoService.eliminar(archivo_url)
        current_app.logger.exception(
            'No se pudo persistir la evidencia de la tarea %s.', tarea_id
        )
        flash('No fue posible registrar la evidencia. Intenta nuevamente.', 'error')
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))
    # La entrega principal ya está persistida. Las alertas y el ranking son
    # derivados: una caída temporal de cualquiera no debe convertir una
    # subida válida en un 500/502 ni obligar al aprendiz a repetirla.
    try:
        actualizar_alertas_ficha(ficha_id)
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'La evidencia de la tarea %s quedó guardada, pero falló la actualización de alertas.',
            tarea_id,
        )
    try:
        actualizar_participacion_ficha(ficha_id)
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'La evidencia de la tarea %s quedó guardada, pero falló la actualización del ranking.',
            tarea_id,
        )
    flash('Evidencia guardada correctamente. El sistema actualizará sus indicadores en segundo plano.', 'success')
    return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))


@aprendiz_bp.route('/<int:ficha_id>/subir-evidencia-plan/<int:plan_id>', methods=['POST'])
@limiter.limit("10 per minute")
def subir_evidencia_plan(ficha_id, plan_id):
    """Recibe la evidencia del aprendiz para un plan de mejoramiento."""
    documento = _documento_aprendiz_para_ficha(ficha_id)
    ficha = db.session.get(Ficha, ficha_id)
    aprendiz = Aprendiz.query.filter_by(
        documento=documento, ficha_id=ficha_id
    ).first() if documento else None
    plan = db.session.get(PlanMejoramiento, plan_id)

    if not ficha or not aprendiz or not plan or plan.ficha_id != ficha_id or plan.aprendiz_id != aprendiz.id:
        flash('No encontramos ese plan para tu ficha.', 'error')
        return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))
    if plan.estado != 'pendiente':
        flash('Este plan ya no acepta nuevas evidencias porque está cerrado.', 'warning')
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))

    archivo = request.files.get('archivo_evidencia_plan')
    if not archivo or not archivo.filename:
        flash('Adjunta un archivo que demuestre el cumplimiento de las actividades acordadas.', 'error')
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))

    try:
        resultado = ArchivoService.guardar(
            archivo=archivo,
            carpeta=TiposCarpeta.PLANES_MEJORAMIENTO,
            subcarpeta=f'ficha_{ficha_id}/aprendiz_{aprendiz.id}/plan_{plan.id}',
            prefijo_extra=f'plan_{plan.id}',
        )
    except ErrorArchivo as exc:
        flash(str(exc), 'error')
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))

    archivo_anterior = plan.evidencia_url
    plan.evidencia_url = resultado.url
    plan.evidencia_enviada_en = datetime.utcnow()
    plan.observaciones_aprendiz = request.form.get('observaciones_aprendiz', '').strip() or None
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        ArchivoService.eliminar(resultado.url)
        current_app.logger.exception('No se pudo registrar evidencia del plan %s', plan.id)
        flash('No fue posible registrar la evidencia. Intenta nuevamente.', 'error')
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))

    if archivo_anterior and archivo_anterior != resultado.url:
        ArchivoService.eliminar(archivo_anterior)

    if plan.creado_por:
        registrar_notificacion(
            'instructor', plan.creado_por,
            f'{aprendiz.nombre_completo} envió evidencia para su plan de mejoramiento.',
            'plan_evidencia', f'plan-evidencia:{plan.id}:{plan.evidencia_enviada_en}',
            ficha_id, f'/instructor/fichas/{ficha_id}/casos-seguimiento',
        )
        db.session.commit()
    flash('Evidencia del plan enviada. Tu instructor la revisará antes de cerrar el plan.', 'success')
    return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))


def _resolver_archivo_subido(filename):
    """Devuelve una ruta contenida en uploads y sus representaciones históricas."""
    try:
        return resolver_archivo_subido(filename)
    except FileNotFoundError:
        abort(404)


def _puede_descargar_archivo(candidatos):
    tareas = Tarea.query.filter(Tarea.material_apoyo_url.in_(candidatos)).all()
    entregas = Entrega.query.filter(Entrega.archivo_url.in_(candidatos)).all()
    registros = RegistroAsistencia.query.filter(
        RegistroAsistencia.soporte_url.in_(candidatos)
    ).all()
    materiales = MaterialFicha.query.filter(
        MaterialFicha.url_archivo.in_(candidatos)
    ).all()

    if current_user.is_authenticated:
        if any(puede_gestionar_tarea(tarea) for tarea in tareas):
            return True
        if any(
            entrega.tarea
            and entrega.aprendiz
            and entrega.aprendiz.ficha_id == entrega.tarea.ficha_id
            and puede_gestionar_tarea(entrega.tarea)
            for entrega in entregas
        ):
            return True
        if any(
            registro.sesion
            and registro.sesion.ficha
            and puede_gestionar_ficha(registro.sesion.ficha)
            for registro in registros
        ):
            return True
        return any(
            material.ficha and puede_gestionar_ficha(material.ficha)
            for material in materiales
        )

    ficha_id = request.args.get('ficha_id', type=int)
    documento = (session.get('aprendiz_documento', '') or request.args.get('documento', '')).strip()
    aprendiz = Aprendiz.query.filter_by(
        ficha_id=ficha_id,
        documento=documento,
    ).first() if ficha_id and documento else None
    if not aprendiz:
        return False
    if any(tarea.ficha_id == ficha_id for tarea in tareas):
        return True
    if any(
        entrega.aprendiz_id == aprendiz.id
        and entrega.tarea
        and entrega.aprendiz
        and entrega.aprendiz.ficha_id == ficha_id
        and entrega.tarea.ficha_id == ficha_id
        for entrega in entregas
    ):
        return True
    if any(material.ficha_id == ficha_id for material in materiales):
        return True
    return any(
        registro.aprendiz_id == aprendiz.id
        and registro.sesion
        and registro.sesion.ficha_id == ficha_id
        for registro in registros
    )


@aprendiz_bp.route('/descargar/<path:filename>')
@limiter.limit("60 per minute")
def descargar_archivo(filename):
    raiz, relativa, candidatos = _resolver_archivo_subido(filename)
    if not _puede_descargar_archivo(candidatos):
        abort(404)
    # El material de ficha conserva en BD el nombre con el que se subió; es más
    # fiable que reconstruirlo desde el nombre técnico del disco.
    material = MaterialFicha.query.filter(
        MaterialFicha.url_archivo.in_(candidatos)
    ).first()
    return ArchivoService.enviar(
        raiz,
        relativa,
        nombre_descarga=(material.nombre_archivo if material else ''),
        inline=request.args.get('inline') == '1',
    )


@aprendiz_bp.route('/descargar-evidencia/<int:entrega_id>')
@limiter.limit("60 per minute")
def descargar_evidencia(entrega_id):
    entrega = db.session.get(Entrega, entrega_id)
    ficha_id = session.get('aprendiz_ficha_id')
    documento = session.get('aprendiz_documento', '').strip()
    aprendiz = Aprendiz.query.filter_by(
        ficha_id=ficha_id,
        documento=documento,
    ).first() if ficha_id and documento else None

    if (
        not entrega
        or not entrega.archivo_url
        or not aprendiz
        or entrega.aprendiz_id != aprendiz.id
        or not entrega.tarea
        or entrega.tarea.ficha_id != ficha_id
        or not entrega.aprendiz
        or entrega.aprendiz.ficha_id != ficha_id
    ):
        abort(404)

    raiz, relativa, _ = _resolver_archivo_subido(entrega.archivo_url)
    return ArchivoService.enviar(
        raiz,
        relativa,
        nombre_descarga=(
            f'evidencia_{entrega.id}_'
            f'{nombre_original_desde_ruta(entrega.archivo_url)}'
        ),
    )


@aprendiz_bp.route('/descargar-evidencia-plan/<int:plan_id>')
@limiter.limit("60 per minute")
def descargar_evidencia_plan(plan_id):
    plan = db.session.get(PlanMejoramiento, plan_id)
    ficha_id = session.get('aprendiz_ficha_id')
    documento = session.get('aprendiz_documento', '').strip()
    aprendiz = Aprendiz.query.filter_by(
        ficha_id=ficha_id, documento=documento
    ).first() if ficha_id and documento else None
    if (
        not plan or not plan.evidencia_url or not aprendiz
        or plan.aprendiz_id != aprendiz.id or plan.ficha_id != ficha_id
    ):
        abort(404)

    raiz, relativa, _ = _resolver_archivo_subido(plan.evidencia_url)
    return ArchivoService.enviar(
        raiz,
        relativa,
        nombre_descarga=(
            f'plan_{plan.id}_evidencia_'
            f'{nombre_original_desde_ruta(plan.evidencia_url)}'
        ),
    )


@aprendiz_bp.route('/descargar-soporte/<int:registro_id>')
@limiter.limit("60 per minute")
def descargar_soporte(registro_id):
    registro = db.session.get(RegistroAsistencia, registro_id)
    ficha_id = session.get('aprendiz_ficha_id')
    documento = session.get('aprendiz_documento', '').strip()
    aprendiz = Aprendiz.query.filter_by(
        ficha_id=ficha_id,
        documento=documento,
    ).first() if ficha_id and documento else None

    if (
        not registro
        or not registro.soporte_url
        or not aprendiz
        or registro.aprendiz_id != aprendiz.id
        or not registro.sesion
        or registro.sesion.ficha_id != ficha_id
    ):
        abort(404)

    raiz, relativa, _ = _resolver_archivo_subido(registro.soporte_url)
    return ArchivoService.enviar(
        raiz,
        relativa,
        nombre_descarga=(
            f'soporte_inasistencia_{registro.id}_'
            f'{nombre_original_desde_ruta(registro.soporte_url)}'
        ),
    )
