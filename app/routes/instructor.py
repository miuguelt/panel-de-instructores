from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort, send_from_directory, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import joinedload
from pathlib import Path
from app import db
from app.models.ficha import Ficha
from app.models.aprendiz import ESTADOS_EN_FORMACION, Aprendiz
from app.models.asistencia import SesionAsistencia, RegistroAsistencia, ESTADOS_ASISTENCIA, CAUSALES_JUSTIFICADAS
from app.models.tarea import Tarea, Entrega
from app.models.alertas import Alerta, ConfiguracionAlertas, PlanMejoramiento
from app.models.insignia import Insignia, InsigniaOtorgada
from app.models.ranking import ConfiguracionRanking
from app.models.aseo import ConfiguracionAseo
from app.services.ranking import actualizar_participacion_ficha
from app.services.alertas import (
    actualizar_alertas_ficha,
    asegurar_resumen_semanal,
    notificar_calificacion,
    obtener_config_comite,
)
from app.services.aseo import ajustar_turno_por_asistencia
from app.services.asistencia import contar_sesiones_registradas, guardar_asistencia
from app.services.importacion_ficha import ErrorImportacion, importar_archivo, clasificar_competencia
from app.services.permisos import puede_gestionar_ficha, puede_gestionar_tarea, tareas_visibles
from app.services.archivos import (
    ArchivoService,
    ErrorArchivo,
    ErrorExtension,
    TiposCarpeta,
    resolver_archivo_subido,
)
from app.services.cronograma import obtener_cronograma
from app.models.ficha_instructor import FichaInstructor
from app.models.juicio import JuicioEvaluativo, JuicioEvaluativoInstructor
from app.models.material import MaterialFicha
from app.models.importacion import ImportacionJob
from app.services.importacion_jobs import encolar_importacion, ColaImportacionesNoDisponible
from datetime import datetime, date
import os
from uuid import uuid4
import openpyxl
from werkzeug.utils import secure_filename

instructor_bp = Blueprint('instructor', __name__, template_folder='../templates/instructor')


ESTADOS_FALTA = ('FALTA', 'FALTA_JUSTIFICADA', 'EXCUSA_MEDICA')


def _faltas_por_aprendiz(ficha_id):
    """Cuenta faltas por aprendiz y estado en una sola consulta agregada.

    Devuelve ``{aprendiz_id: {estado: cantidad}}``. Antes cada aprendiz costaba
    dos COUNT independientes, asi que una ficha de 30 aprendices emitia 60
    consultas solo para pintar el semaforo.
    """
    filas = (
        db.session.query(
            RegistroAsistencia.aprendiz_id,
            RegistroAsistencia.estado,
            func.count(RegistroAsistencia.id),
        )
        .join(SesionAsistencia, RegistroAsistencia.sesion_id == SesionAsistencia.id)
        .filter(
            SesionAsistencia.ficha_id == ficha_id,
            RegistroAsistencia.estado.in_(ESTADOS_FALTA),
        )
        .group_by(RegistroAsistencia.aprendiz_id, RegistroAsistencia.estado)
        .all()
    )
    conteo = {}
    for aprendiz_id, estado, cantidad in filas:
        conteo.setdefault(aprendiz_id, {})[estado] = cantidad
    return conteo


def _ultima_entrega_por_aprendiz(tareas):
    """Mapa ``{(tarea_id, aprendiz_id): entrega mas reciente}`` en una consulta."""
    ids_tareas = [t.id for t in tareas]
    if not ids_tareas:
        return {}
    entregas = (
        Entrega.query
        .filter(Entrega.tarea_id.in_(ids_tareas))
        .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
        .all()
    )
    ultimas = {}
    for entrega in entregas:
        ultimas.setdefault((entrega.tarea_id, entrega.aprendiz_id), entrega)
    return ultimas


def calcular_semaforo(ficha_id, aprendices, config, ahora=None):
    """Nivel de riesgo, faltas y tareas pendientes de cada aprendiz de la ficha.

    Las vistas de asistencia y de alertas mostraban el mismo semaforo
    resolviendolo aprendiz por aprendiz (dos COUNT mas un SELECT por tarea).
    Aqui se resuelve con tres consultas para toda la ficha.
    """
    ahora = ahora or datetime.utcnow()
    total_sesiones = contar_sesiones_registradas(ficha_id)
    faltas = _faltas_por_aprendiz(ficha_id)
    tareas_ficha = tareas_visibles(ficha_id).all()
    ultimas_entregas = _ultima_entrega_por_aprendiz(tareas_ficha)

    stats_map = {}
    for aprendiz in aprendices:
        conteo = faltas.get(aprendiz.id, {})
        faltas_no_justificadas = conteo.get('FALTA', 0)
        total_faltas = sum(conteo.values())
        faltas_justificadas = total_faltas - faltas_no_justificadas
        pct_asistencia = (
            (total_sesiones - total_faltas) / total_sesiones * 100
            if total_sesiones > 0 else 100.0
        )

        tareas_pendientes = 0
        for tarea in tareas_ficha:
            entrega = ultimas_entregas.get((tarea.id, aprendiz.id))
            if entrega and entrega.estado_revision == 'rechazada':
                tareas_pendientes += 1
            elif not entrega and tarea.fecha_limite and tarea.fecha_limite < ahora:
                tareas_pendientes += 1

        if faltas_no_justificadas >= config.umbral_rojo or tareas_pendientes >= 3:
            nivel = 'rojo'
        elif faltas_no_justificadas >= config.umbral_amarillo or tareas_pendientes >= 1:
            nivel = 'amarillo'
        else:
            nivel = 'verde'

        stats_map[aprendiz.id] = {
            'faltas_no_justificadas': faltas_no_justificadas,
            'faltas_justificadas': faltas_justificadas,
            'pct_asistencia': round(pct_asistencia, 1),
            'tareas_pendientes': tareas_pendientes,
            'nivel': nivel,
        }
    return stats_map, total_sesiones


def obtener_fichas():
    if current_user.es_admin:
        return Ficha.query.order_by(Ficha.codigo).all()
    return Ficha.query.outerjoin(FichaInstructor, FichaInstructor.ficha_id == Ficha.id).filter(
        or_(Ficha.instructor_id == current_user.id,
               FichaInstructor.instructor_id == current_user.id)
    ).distinct().order_by(Ficha.codigo).all()


@instructor_bp.route('/')
@login_required
def dashboard():
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
                RegistroAsistencia.estado.in_(['FALTA', 'FALTA_JUSTIFICADA', 'EXCUSA_MEDICA']),
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

        # --- Alertas activas ---
        alertas_activas = dict(
            db.session.query(Alerta.ficha_id, func.count(Alerta.id))
            .filter(Alerta.ficha_id.in_(ficha_ids), Alerta.estado == 'activa')
            .group_by(Alerta.ficha_id).all()
        )

        # --- Juicios evaluativos ---
        juicios_por_ficha = {}
        juicios_data = db.session.query(
            JuicioEvaluativo.ficha_id, JuicioEvaluativo.juicio, func.count(JuicioEvaluativo.id)
        ).join(Aprendiz).filter(
            JuicioEvaluativo.ficha_id.in_(ficha_ids),
            Aprendiz.estado.in_(ESTADOS_EN_FORMACION)
        ).group_by(JuicioEvaluativo.ficha_id, JuicioEvaluativo.juicio).all()
        for fid, juicio, cnt in juicios_data:
            if fid not in juicios_por_ficha:
                juicios_por_ficha[fid] = {'total': 0, 'aprobados': 0}
            juicios_por_ficha[fid]['total'] += cnt
            if juicio and 'APROBADO' in juicio.upper() and 'AUN NO' not in juicio.upper():
                juicios_por_ficha[fid]['aprobados'] += cnt

        # --- Avance de Certificación (100% Aprobados por Aprendiz) ---
        estado_juicios_aprendices = {}
        juicios_aprendices_data = db.session.query(
            JuicioEvaluativo.ficha_id, JuicioEvaluativo.aprendiz_id, JuicioEvaluativo.juicio
        ).join(Aprendiz).filter(
            JuicioEvaluativo.ficha_id.in_(ficha_ids),
            Aprendiz.estado.in_(ESTADOS_EN_FORMACION)
        ).all()
        for fid, aid, juicio in juicios_aprendices_data:
            if aid not in estado_juicios_aprendices:
                estado_juicios_aprendices[aid] = {'ficha_id': fid, 'total': 0, 'aprobados': 0}
            estado_juicios_aprendices[aid]['total'] += 1
            if juicio and 'APROBADO' in juicio.upper() and 'AUN NO' not in juicio.upper():
                estado_juicios_aprendices[aid]['aprobados'] += 1
        
        certificados_por_ficha = {fid: 0 for fid in ficha_ids}
        for aid, data in estado_juicios_aprendices.items():
            if data['total'] > 0 and data['total'] == data['aprobados']:
                certificados_por_ficha[data['ficha_id']] += 1

        # --- Resumen de Competencias ---
        competencias_por_ficha = {}
        comps_data = db.session.query(
            JuicioEvaluativo.ficha_id, JuicioEvaluativo.competencia, JuicioEvaluativo.juicio
        ).join(Aprendiz).filter(
            JuicioEvaluativo.ficha_id.in_(ficha_ids),
            Aprendiz.estado.in_(ESTADOS_EN_FORMACION)
        ).all()
        
        for fid, comp, juicio in comps_data:
            if not comp or comp.strip() == '':
                continue
            if fid not in competencias_por_ficha:
                competencias_por_ficha[fid] = {}
            if comp not in competencias_por_ficha[fid]:
                competencias_por_ficha[fid][comp] = {'total': 0, 'aprobados': 0}
            competencias_por_ficha[fid][comp]['total'] += 1
            if juicio and 'APROBADO' in juicio.upper() and 'AUN NO' not in juicio.upper():
                competencias_por_ficha[fid][comp]['aprobados'] += 1
                
        top_competencias = {}
        for fid, comps in competencias_por_ficha.items():
            sorted_comps = sorted(
                comps.items(), 
                key=lambda x: ((x[1]['aprobados'] / x[1]['total']) if x[1]['total'] > 0 else 0, -x[1]['total'])
            )
            top_competencias[fid] = sorted_comps[:2]

        # --- Consolidar por ficha ---
        for ficha in fichas:
            fid = ficha.id
            n_ap_total = estadisticas_fichas.get(fid, {}).get('total', 0)
            n_ap = estadisticas_fichas.get(fid, {}).get('activos', 0)
            ses = sesiones_count.get(fid, 0)
            faltas = faltas_por_ficha.get(fid, 0)
            posibles = ses * n_ap
            pct_asistencia = round(((posibles - faltas) / posibles * 100), 1) if posibles else 100.0

            tareas_data = tareas_por_ficha.get(fid, {'total': 0, 'entregas': 0, 'pendientes': 0})
            if tareas_data['total'] and n_ap:
                pct_entregas = round((tareas_data['entregas'] / (tareas_data['total'] * n_ap) * 100))
            else:
                pct_entregas = 100

            juicios = juicios_por_ficha.get(fid, {})
            pct_juicios = round((juicios.get('aprobados', 0) / juicios.get('total', 1) * 100)) if juicios.get('total') else 0

            total_days = (ficha.fecha_fin - ficha.fecha_inicio).days if (ficha.fecha_inicio and ficha.fecha_fin) else 0
            if total_days > 0:
                elapsed = (now.date() - ficha.fecha_inicio).days
                pct_tiempo = max(0, min(100, int((elapsed / total_days) * 100)))
            else:
                pct_tiempo = 0

            estadisticas_extra[fid] = {
                'total_aprendices': n_ap,
                'total_aprendices_incl_inactivos': n_ap_total,
                'sesiones': ses,
                'pct_asistencia': pct_asistencia,
                'tareas_totales': tareas_data['total'],
                'entregas_totales': tareas_data['entregas'],
                'pendientes': tareas_data['pendientes'],
                'pct_entregas': pct_entregas,
                'juicios_totales': juicios.get('total', 0),
                'juicios_aprobados': juicios.get('aprobados', 0),
                'pct_juicios': pct_juicios,
                'aprendices_certificados': certificados_por_ficha.get(fid, 0),
                'alertas_activas': alertas_activas.get(fid, 0),
                'pct_tiempo': pct_tiempo,
                'top_competencias': top_competencias.get(fid, [])
            }

    def get_order(fase):
        return {'lectiva': 1, 'por_iniciar': 2, 'productiva': 3, 'finalizada': 4, 'sin_fechas': 5}.get(fase, 99)

    fichas.sort(key=lambda f: get_order(cronogramas[f.id]['fase']))

    return render_template('dashboard.html', fichas=fichas, cronogramas=cronogramas,
                           estadisticas_fichas=estadisticas_fichas,
                           estadisticas_extra=estadisticas_extra)


@instructor_bp.route('/fichas', methods=['GET', 'POST'])
@login_required
def fichas():
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip()
        nombre_programa = request.form.get('nombre_programa', '').strip()
        fecha_inicio_str = request.form.get('fecha_inicio', '')
        fecha_fin_str = request.form.get('fecha_fin', '')
        duracion_productiva_str = request.form.get('duracion_productiva_meses', '6')

        if not codigo or not nombre_programa:
            flash('El código y el nombre del programa son obligatorios.', 'error')
            return redirect(url_for('instructor.fichas'))

        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date() if fecha_inicio_str else None
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date() if fecha_fin_str else None
        except ValueError:
            flash('Las fechas de la ficha no tienen un formato válido.', 'error')
            return redirect(url_for('instructor.fichas'))
        if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
            flash('La fecha de finalización debe ser posterior a la fecha de inicio.', 'error')
            return redirect(url_for('instructor.fichas'))
        try:
            duracion_productiva = min(max(int(duracion_productiva_str), 1), 24)
        except ValueError:
            duracion_productiva = 6

        ficha = Ficha.query.filter(
            or_(Ficha.codigo == codigo, Ficha.codigo_ficha == codigo)
        ).order_by(Ficha.id).first()
        if ficha:
            if not puede_gestionar_ficha(ficha):
                flash(
                    f'La ficha {ficha.codigo} ya existe. Solicita al administrador o al instructor responsable que te vincule.',
                    'warning',
                )
                return redirect(url_for('instructor.fichas'))
            # Actualizar datos de la ficha existente
            ficha.nombre_programa = nombre_programa
            ficha.fecha_inicio = fecha_inicio
            ficha.fecha_fin = fecha_fin
            ficha.duracion_productiva_meses = duracion_productiva
            ficha.codigo_ficha = codigo
            if not FichaInstructor.query.filter_by(ficha_id=ficha.id, instructor_id=current_user.id).first():
                db.session.add(FichaInstructor(ficha_id=ficha.id, instructor_id=current_user.id))
            db.session.commit()
            flash(f'La ficha {ficha.codigo} fue actualizada correctamente.', 'success')
            return redirect(url_for('instructor.fichas'))

        ficha = Ficha(
            codigo=codigo,
            codigo_ficha=codigo,
            nombre_programa=nombre_programa,
            instructor_id=current_user.id,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            duracion_productiva_meses=duracion_productiva,
        )
        db.session.add(ficha)
        db.session.flush()
        db.session.add(FichaInstructor(ficha_id=ficha.id, instructor_id=current_user.id))

        config = ConfiguracionAlertas(ficha_id=ficha.id)
        db.session.add(config)
        db.session.add(ConfiguracionRanking(ficha_id=ficha.id))
        db.session.add(ConfiguracionAseo(ficha_id=ficha.id))
        db.session.commit()

        flash(f'Ficha {codigo} creada correctamente.', 'success')
        return redirect(url_for('instructor.fichas'))

    fichas = obtener_fichas()
    cronogramas = {ficha.id: obtener_cronograma(ficha) for ficha in fichas}
    return render_template('fichas.html', fichas=fichas, cronogramas=cronogramas)


def _resumen_importacion(resultado):
    mensaje = (
        f"{resultado['nuevos']} aprendices nuevos, "
        f"{resultado['actualizados']} actualizados y "
        f"{resultado['juicios_nuevos']} juicios evaluativos incorporados."
    )
    if resultado['juicios_repetidos']:
        mensaje += (
            f" {resultado['juicios_repetidos']} juicios ya estaban en el historial."
        )
    sesiones = resultado.get('sesiones_creadas', 0)
    if sesiones:
        mensaje += f" {sesiones} sesiones de clase creadas automáticamente."
    return mensaje


@instructor_bp.route('/fichas/importar-reporte', methods=['POST'])
@login_required
def importar_reporte_ficha():
    archivo = request.files.get('archivo')
    if not archivo or not archivo.filename.lower().endswith(('.xlsx', '.xls')):
        flash('Selecciona el Reporte de Juicios Evaluativos en formato .xls o .xlsx.', 'error')
        return redirect(url_for('instructor.fichas'))

    try:
        resultado = importar_archivo(
            archivo,
            ficha_actual=None,
            instructor_id=current_user.id,
            crear_ficha=True,
        )
        ficha = resultado['ficha']
        db.session.commit()
        actualizar_alertas_ficha(ficha.id)
        actualizar_participacion_ficha(ficha.id)

        accion = 'creada' if resultado['ficha_creada'] else 'vinculada'
        mensaje = (
            f"Ficha {ficha.codigo} {accion} automáticamente. "
            f"{_resumen_importacion(resultado)}"
        )
        if resultado['errores']:
            flash(mensaje + f" {len(resultado['errores'])} filas no se pudieron importar.", 'warning')
            for error in resultado['errores'][:10]:
                flash(error, 'error')
        else:
            flash(mensaje, 'success')
        return redirect(url_for('instructor.aprendices', ficha_id=ficha.id))
    except (ErrorImportacion, RuntimeError) as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error inesperado al crear una ficha desde el reporte')
        flash('No fue posible procesar el reporte. Verifica el archivo e inténtalo de nuevo.', 'error')
    return redirect(url_for('instructor.fichas'))


@instructor_bp.route('/fichas/<int:ficha_id>/aprendices')
@login_required
def aprendices(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    lista_aprendices = Aprendiz.query.filter_by(ficha_id=ficha_id).order_by(Aprendiz.apellidos, Aprendiz.nombre).all()
    aprendiz_ids = [a.id for a in lista_aprendices]

    # Estadísticas de juicios por aprendiz
    stats_map = {}
    if aprendiz_ids:
        juicios = JuicioEvaluativo.query.filter(
            JuicioEvaluativo.ficha_id == ficha_id,
            JuicioEvaluativo.aprendiz_id.in_(aprendiz_ids),
        ).all()
        from collections import defaultdict
        tmp = defaultdict(lambda: {'total': 0, 'aprobados': 0})
        for j in juicios:
            tmp[j.aprendiz_id]['total'] += 1
            if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper():
                tmp[j.aprendiz_id]['aprobados'] += 1
        stats_map = dict(tmp)

    return render_template('aprendices.html', ficha=ficha, aprendices=lista_aprendices, juicios_stats=stats_map)


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
    from app.models.insignia import Insignia, InsigniaOtorgada
    otorgamientos = InsigniaOtorgada.query.join(Insignia).filter(
        InsigniaOtorgada.aprendiz_id == aprendiz.id,
        Insignia.ficha_id == ficha_id,
    ).order_by(InsigniaOtorgada.fecha_obtencion.desc()).all()

    # Ranking y Aseo
    from app.services.ranking import calcular_ranking
    from app.services.aseo import resumen_aprendiz
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
        func = j.funcionario_registro or 'Sin registro'
        if func not in instructores_aprendiz_hist:
            instructores_aprendiz_hist[func] = {'total': 0, 'aprobados': 0, 'pendientes': 0}
        instructores_aprendiz_hist[func]['total'] += 1
        es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper() and 'POR EVALUAR' not in j.juicio.upper())
        if es_aprobado:
            instructores_aprendiz_hist[func]['aprobados'] += 1
        else:
            instructores_aprendiz_hist[func]['pendientes'] += 1

    for func in instructores_aprendiz_hist.values():
        func['pct'] = round((func['aprobados'] / func['total'] * 100)) if func['total'] > 0 else 0

    fechas_aprendiz = [j.fecha_juicio for j in juicios if j.fecha_juicio]
    resumen_aprendiz_hist = {
        'total_competencias': len(competencias_map),
        'total_instructores': len(instructores_aprendiz_hist),
        'primera_evaluacion': min(fechas_aprendiz) if fechas_aprendiz else None,
        'ultima_evaluacion': max(fechas_aprendiz) if fechas_aprendiz else None,
    }

    # ---- REPORTE DETALLADO: ASISTENCIA ----
    from collections import defaultdict

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
    }
    asistencia_por_mes = defaultdict(lambda: {
        'total': 0, 'asistio': 0, 'tardanzas': 0, 'faltas': 0, 'justificadas': 0,
    })
    for registro in registros_aprendiz:
        estado = registro.estado if registro.estado in estados_asistencia else 'FALTA'
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
            else:
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

    return render_template('instructor/historial_aprendiz.html', ficha=ficha, aprendiz=aprendiz,
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


@instructor_bp.route('/fichas/<int:ficha_id>/cargar-excel', methods=['POST'])
@login_required
def cargar_excel(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    archivo = request.files.get('archivo')
    if not archivo or not archivo.filename.lower().endswith(('.xlsx', '.xls')):
        flash('Debes subir un archivo Excel (.xlsx o .xls).', 'error')
        return redirect(url_for('instructor.aprendices', ficha_id=ficha_id))

    importacion_job_id = None
    try:
        if current_app.config.get('IMPORTACIONES_ASINCRONAS'):
            nombre_archivo = secure_filename(archivo.filename) or 'reporte.xls'
            carpeta = os.path.join(current_app.config['UPLOAD_FOLDER'], 'importaciones')
            os.makedirs(carpeta, exist_ok=True)
            ruta = os.path.join(carpeta, f'{uuid4().hex}_{nombre_archivo}')
            archivo.save(ruta)

            job = ImportacionJob(
                ficha_id=ficha.id,
                instructor_id=current_user.id,
                archivo_path=ruta,
                nombre_archivo=nombre_archivo,
                estado='encolado',
            )
            db.session.add(job)
            db.session.commit()
            importacion_job_id = job.id
            try:
                encolar_importacion(job.id, current_app.config['IMPORT_QUEUE_NAME'])
            except ColaImportacionesNoDisponible as exc:
                db.session.rollback()
                try:
                    os.remove(ruta)
                except OSError:
                    pass
                raise RuntimeError(
                    'No fue posible poner la importación en cola. '
                    'Revisa REDIS_URL y que el worker esté activo.'
                ) from exc

            flash(
                f'Importación encolada (trabajo #{job.id}). '
                'Puedes seguir usando el panel; el archivo se procesará en segundo plano.',
                'success',
            )
        else:
            resultado = importar_archivo(archivo, ficha, current_user.id)
            ficha = resultado['ficha']
            db.session.commit()
            actualizar_alertas_ficha(ficha.id)
            actualizar_participacion_ficha(ficha.id)

            msg = _resumen_importacion(resultado)
            if resultado['errores']:
                flash(msg + f" {len(resultado['errores'])} errores.", 'warning')
                for err in resultado['errores'][:10]:
                    flash(err, 'error')
            else:
                flash(msg, 'success')

    except (ErrorImportacion, RuntimeError) as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error inesperado al importar aprendices')
        flash('No fue posible procesar el archivo. Verifica el Excel e inténtalo de nuevo.', 'error')

    parametros = {'ficha_id': ficha.id}
    if importacion_job_id:
        parametros['importacion_id'] = importacion_job_id
    return redirect(url_for('instructor.aprendices', **parametros))


@instructor_bp.route('/fichas/<int:ficha_id>/importaciones/<int:job_id>', methods=['GET'])
@login_required
def estado_importacion(ficha_id, job_id):
    """Estado consultable para una barra de progreso del frontend."""
    ficha = db.session.get(Ficha, ficha_id)
    job = db.session.get(ImportacionJob, job_id)
    if not job or job.ficha_id != ficha_id or not puede_gestionar_ficha(ficha):
        return jsonify({'error': 'Importación no encontrada.'}), 404
    return jsonify({
        'id': job.id,
        'estado': job.estado,
        'resultado': job.resultado,
        'error': job.error,
        'creado_en': job.creado_en.isoformat() if job.creado_en else None,
        'iniciado_en': job.iniciado_en.isoformat() if job.iniciado_en else None,
        'terminado_en': job.terminado_en.isoformat() if job.terminado_en else None,
    })


@instructor_bp.route('/fichas/<int:ficha_id>/plantilla-excel')
@login_required
def descargar_plantilla(ficha_id):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Aprendices'
    ws.append(['Documento', 'Nombre', 'Apellidos', 'Tipo (CC/TI)', 'Estado', 'Correo (opcional)'])
    ws.append(['1234567890', 'Juan', 'Perez Garcia', 'CC', 'EN_FORMACION', 'juan@ejemplo.com'])
    ws.append(['9876543210', 'Maria', 'Lopez Ruiz', 'TI', 'EN_FORMACION', ''])

    from flask import send_file
    import io
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='plantilla_aprendices.xlsx')


@instructor_bp.route('/fichas/<int:ficha_id>/asistencia', methods=['GET', 'POST'])
@login_required
def asistencia(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    if request.method == 'POST':
        fecha_str = request.form.get('fecha', '')
        if not fecha_str:
            flash('Debes indicar la fecha de la sesión.', 'error')
            return redirect(url_for('instructor.asistencia', ficha_id=ficha_id))

        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            flash('La fecha de la sesión no tiene un formato válido.', 'error')
            return redirect(url_for('instructor.asistencia', ficha_id=ficha_id))

        aprendices = Aprendiz.query_en_formacion(ficha_id).order_by(Aprendiz.apellidos).all()
        estados_validos = {valor for valor, _etiqueta in ESTADOS_ASISTENCIA}
        causales_validas = {valor for valor, _etiqueta in CAUSALES_JUSTIFICADAS}
        for aprendiz in aprendices:
            estado = request.form.get(f'asistencia_{aprendiz.id}')
            causal = request.form.get(f'causal_{aprendiz.id}', '')
            if estado not in estados_validos:
                flash(f'Selecciona la asistencia de {aprendiz.nombre} {aprendiz.apellidos}.', 'error')
                return redirect(url_for('instructor.asistencia', ficha_id=ficha_id, fecha=fecha.isoformat()))
            if estado in ('FALTA_JUSTIFICADA', 'EXCUSA_MEDICA') and causal not in causales_validas:
                flash(f'Selecciona una causal válida para {aprendiz.nombre} {aprendiz.apellidos}.', 'error')
                return redirect(url_for('instructor.asistencia', ficha_id=ficha_id, fecha=fecha.isoformat()))

        registros = {
            aprendiz.id: (
                request.form.get(f'asistencia_{aprendiz.id}'),
                request.form.get(f'causal_{aprendiz.id}', '') or None,
            )
            for aprendiz in aprendices
        }

        try:
            guardar_asistencia(ficha_id, fecha, registros)
        except OperationalError as e:
            db.session.rollback()
            current_app.logger.error("Error de conexión con la base de datos al guardar asistencia: %s", str(e))
            flash('Error de conexión con la base de datos. Por favor, inténtalo de nuevo en unos segundos.', 'error')
        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.error("Error de integridad al guardar asistencia: %s", str(e))
            flash('Error de integridad: Ya existe un registro conflictivo para esta sesión.', 'error')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error("Error inesperado al guardar asistencia: %s", str(e), exc_info=True)
            flash('Ocurrió un error inesperado al guardar la asistencia. Contacta al soporte si el problema persiste.', 'error')
        else:
            turno_aseo = None
            tareas_secundarias_fallidas = []

            try:
                turno_aseo = ajustar_turno_por_asistencia(ficha_id, fecha)
                db.session.commit()
            except Exception:
                db.session.rollback()
                tareas_secundarias_fallidas.append('turnos de aseo')
                current_app.logger.exception(
                    'La asistencia quedó guardada, pero falló el ajuste de aseo '
                    'para ficha %s y fecha %s', ficha_id, fecha
                )

            try:
                actualizar_alertas_ficha(ficha_id)
            except Exception:
                db.session.rollback()
                tareas_secundarias_fallidas.append('alertas')
                current_app.logger.exception(
                    'La asistencia quedó guardada, pero falló la actualización '
                    'de alertas para ficha %s', ficha_id
                )

            try:
                actualizar_participacion_ficha(ficha_id)
            except Exception:
                db.session.rollback()
                tareas_secundarias_fallidas.append('ranking')
                current_app.logger.exception(
                    'La asistencia quedó guardada, pero falló la actualización '
                    'del ranking para ficha %s', ficha_id
                )

            mensaje = 'Asistencia guardada correctamente en la base de datos.'
            if turno_aseo and getattr(turno_aseo, 'observacion', None) and 'Suplente por ausencia' in (turno_aseo.observacion or ''):
                mensaje += (
                    ' Se reasignó el turno de aseo: el ausente quedó con reposición '
                    'en el próximo cupo para mantener la equidad del grupo.'
                )
            if tareas_secundarias_fallidas:
                mensaje += (
                    ' La asistencia está segura; se reintentará la actualización de '
                    + ', '.join(tareas_secundarias_fallidas) + ' en la próxima operación.'
                )
            flash(mensaje, 'success')

        return redirect(url_for('instructor.asistencia', ficha_id=ficha_id, fecha=fecha.isoformat()))

    fecha_param = request.args.get('fecha', date.today().isoformat())
    sesion = SesionAsistencia.query.filter_by(ficha_id=ficha_id, fecha=fecha_param).first()

    registros_map = {}
    if sesion:
        for r in sesion.registros:
            registros_map[r.aprendiz_id] = r

    sesiones_recientes = (
        SesionAsistencia.query
        .join(RegistroAsistencia)
        .filter(SesionAsistencia.ficha_id == ficha_id)
        .distinct()
        .order_by(SesionAsistencia.fecha.desc())
        .limit(10)
        .all()
    )

    config = ConfiguracionAlertas.query.filter_by(ficha_id=ficha_id).first()
    if not config:
        config = ConfiguracionAlertas(ficha_id=ficha_id)
        db.session.add(config)
        db.session.commit()

    # Los aprendices se cargan despues del commit: al confirmar la sesion
    # SQLAlchemy expira los objetos vivos y volver a leer aprendiz.id
    # recargaria cada fila una por una.
    aprendices = Aprendiz.query_en_formacion(ficha_id).order_by(Aprendiz.apellidos).all()

    stats_map, total_sesiones = calcular_semaforo(ficha_id, aprendices, config)

    return render_template('asistencia.html',
                           ficha=ficha,
                           aprendices=aprendices,
                           registros_map=registros_map,
                           sesiones_recientes=sesiones_recientes,
                           stats_map=stats_map,
                           fecha_actual=fecha_param,
                           estados_asistencia=ESTADOS_ASISTENCIA,
                           causales_justificadas=CAUSALES_JUSTIFICADAS,
                           config=config,
                           sesion=sesion,
                           total_sesiones=total_sesiones)

@instructor_bp.route('/fichas/<int:ficha_id>/asistencia/aprendiz/<int:aprendiz_id>/modal')
@login_required
def asistencia_aprendiz_modal(ficha_id, aprendiz_id):
    ficha = db.session.get(Ficha, ficha_id)
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not puede_gestionar_ficha(ficha) or not aprendiz or aprendiz.ficha_id != ficha_id:
        return 'Aprendiz no encontrado', 404

    registros = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        RegistroAsistencia.aprendiz_id == aprendiz.id
    ).order_by(SesionAsistencia.fecha.asc()).all()

    config_alertas = ConfiguracionAlertas.query.filter_by(ficha_id=ficha_id).first()

    asistencia_map = {}
    faltas = {}
    faltas_detalladas = []
    total_asistencias = 0
    total_tardanzas = 0
    total_faltas_nj = 0
    total_faltas_j = 0
    conteo_dias_falta = {}

    DIAS_SEMANA_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    MESES_ES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    CAUSALES_DICT = dict(CAUSALES_JUSTIFICADAS)

    for r in registros:
        fecha_obj = r.sesion.fecha
        fecha_iso = fecha_obj.isoformat()
        dia_nom = DIAS_SEMANA_ES[fecha_obj.weekday()]
        fecha_fmt = f"{dia_nom}, {fecha_obj.day} de {MESES_ES[fecha_obj.month]} de {fecha_obj.year}"

        causal_label = CAUSALES_DICT.get(r.causal_justificacion, r.causal_justificacion or '')

        asistencia_map[fecha_iso] = {
            'estado': r.estado,
            'causal': causal_label,
            'nota': r.nota or '',
            'fecha_fmt': fecha_fmt
        }

        if r.estado == 'ASISTE':
            total_asistencias += 1
        elif r.estado == 'TARDANZA':
            total_tardanzas += 1
            total_asistencias += 1
        elif r.estado == 'FALTA':
            total_faltas_nj += 1
            conteo_dias_falta[dia_nom] = conteo_dias_falta.get(dia_nom, 0) + 1
            faltas[fecha_iso] = {'estado': r.estado, 'causal': causal_label}
            faltas_detalladas.append({
                'fecha_iso': fecha_iso,
                'fecha_fmt': fecha_fmt,
                'dia_semana': dia_nom,
                'estado': r.estado,
                'causal': causal_label,
                'nota': r.nota or ''
            })
        elif r.estado in ('FALTA_JUSTIFICADA', 'EXCUSA_MEDICA'):
            total_faltas_j += 1
            conteo_dias_falta[dia_nom] = conteo_dias_falta.get(dia_nom, 0) + 1
            faltas[fecha_iso] = {'estado': r.estado, 'causal': causal_label}
            faltas_detalladas.append({
                'fecha_iso': fecha_iso,
                'fecha_fmt': fecha_fmt,
                'dia_semana': dia_nom,
                'estado': r.estado,
                'causal': causal_label,
                'nota': r.nota or ''
            })

    # Faltas detalladas ordenadas de la más reciente a la más antigua
    faltas_detalladas.reverse()

    # Cálculo de racha consecutiva asistida
    racha_actual = 0
    for r in reversed(registros):
        if r.estado in ('ASISTE', 'TARDANZA'):
            racha_actual += 1
        else:
            break

    # Día con más inasistencias
    dia_mas_inasistencias = None
    max_faltas_dia = 0
    for dia, cnt in conteo_dias_falta.items():
        if cnt > max_faltas_dia:
            max_faltas_dia = cnt
            dia_mas_inasistencias = dia

    total_sesiones = contar_sesiones_registradas(ficha_id)
    total_faltas = total_faltas_nj + total_faltas_j
    pct_asistencia = ((total_sesiones - total_faltas) / total_sesiones * 100) if total_sesiones > 0 else 100.0

    return render_template('instructor/asistencia_modal_aprendiz.html',
                           ficha=ficha, aprendiz=aprendiz,
                           asistencia_map=asistencia_map,
                           faltas=faltas,
                           faltas_detalladas=faltas_detalladas,
                           total_asistencias=total_asistencias,
                           total_tardanzas=total_tardanzas,
                           total_faltas_nj=total_faltas_nj,
                           total_faltas_j=total_faltas_j,
                           total_faltas=total_faltas,
                           total_sesiones=total_sesiones,
                           pct_asistencia=round(pct_asistencia, 1),
                           racha_actual=racha_actual,
                           dia_mas_inasistencias=dia_mas_inasistencias,
                           max_faltas_dia=max_faltas_dia,
                           config_alertas=config_alertas)


@instructor_bp.route('/fichas/<int:ficha_id>/tareas', methods=['GET', 'POST'])
@login_required
def tareas(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        enlace = request.form.get('enlace_externo', '').strip()
        fecha_limite_str = request.form.get('fecha_limite', '')
        requiere_archivo = 'requiere_archivo' in request.form

        if not titulo:
            flash('El título es obligatorio.', 'error')
            return redirect(url_for('instructor.tareas', ficha_id=ficha_id))

        fecha_limite = None
        if fecha_limite_str:
            try:
                fecha_limite = datetime.strptime(fecha_limite_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('La fecha límite no tiene un formato válido.', 'error')
                return redirect(url_for('instructor.tareas', ficha_id=ficha_id))

        material_url = None
        archivo_material = request.files.get('material_apoyo')
        if archivo_material and archivo_material.filename:
            try:
                resultado = ArchivoService.guardar(
                    archivo=archivo_material,
                    carpeta=TiposCarpeta.MATERIALES_TAREA,
                    # Keep support material inside the same instructor scope
                    # as the task. This prevents files with the same logical
                    # task name from being mixed across shared fichas.
                    subcarpeta=f'ficha_{ficha_id}/instructor_{current_user.id}',
                    prefijo_extra=f'tarea_{current_user.id}',
                    check_magic=True,
                )
                material_url = resultado.url
            except ErrorArchivo as exc:
                flash(str(exc), 'error')
                return redirect(url_for('instructor.tareas', ficha_id=ficha_id))

        tarea = Tarea(
            ficha_id=ficha_id,
            instructor_id=current_user.id,
            titulo=titulo,
            descripcion=descripcion,
            enlace_externo=enlace or None,
            material_apoyo_url=material_url,
            fecha_limite=fecha_limite,
            requiere_archivo=requiere_archivo,
        )
        db.session.add(tarea)
        db.session.commit()
        actualizar_alertas_ficha(ficha_id)
        actualizar_participacion_ficha(ficha_id)
        flash(f'Tarea "{titulo}" creada correctamente.', 'success')
        return redirect(url_for('instructor.tareas', ficha_id=ficha_id))

    lista_tareas = tareas_visibles(ficha_id).order_by(Tarea.creada_en.desc()).all()
    return render_template('tareas.html', ficha=ficha, tareas=lista_tareas, now=datetime.utcnow())


@instructor_bp.route('/tareas/<int:tarea_id>/entregas')
@login_required
def ver_entregas(tarea_id):
    tarea = db.session.get(Tarea, tarea_id)
    if not tarea:
        flash('Tarea no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    ficha = tarea.ficha
    if not puede_gestionar_ficha(ficha) or not puede_gestionar_tarea(tarea):
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
    aprendices = Aprendiz.query_en_formacion(ficha.id).order_by(Aprendiz.apellidos).all()

    # Obtener insignias de la ficha
    otorgamientos = InsigniaOtorgada.query.join(Insignia).filter(
        Insignia.ficha_id == ficha.id
    ).order_by(InsigniaOtorgada.fecha_obtencion.desc()).all()
    
    from collections import defaultdict
    insignias_map = defaultdict(list)
    for ot in otorgamientos:
        insignias_map[ot.aprendiz_id].append(ot.insignia)

    return render_template('entregas.html', tarea=tarea, ficha=ficha,
                           aprendices=aprendices, entregas_map=entregas_map,
                           insignias_map=insignias_map)


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
        or not puede_gestionar_tarea(entrega.tarea)
    ):
        abort(404)

    try:
        raiz, relativa, _ = resolver_archivo_subido(entrega.archivo_url)
    except FileNotFoundError:
        abort(404)

    extension = Path(entrega.archivo_url).suffix
    return send_from_directory(
        str(raiz),
        relativa.as_posix(),
        as_attachment=True,
        download_name=f'evidencia_{entrega.id}{extension}',
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

    calificacion = request.form.get('calificacion', '').strip()
    feedback = request.form.get('feedback', '').strip()

    entrega.calificacion = calificacion or None
    entrega.feedback = feedback or None
    entrega.estado_revision = request.form.get('estado_revision', 'aprobada')
    if entrega.estado_revision not in ('aprobada', 'rechazada'):
        entrega.estado_revision = 'aprobada'
    entrega.calificada = True
    entrega.revisada_en = datetime.utcnow()
    db.session.commit()
    actualizar_alertas_ficha(entrega.tarea.ficha_id)
    actualizar_participacion_ficha(entrega.tarea.ficha_id)
    notificar_calificacion(entrega, entrega.tarea.ficha_id)

    flash('Calificación guardada.', 'success')
    return redirect(url_for('instructor.ver_entregas', tarea_id=entrega.tarea_id))


@instructor_bp.route('/fichas/<int:ficha_id>/alertas')
@login_required
def alertas(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    actualizar_alertas_ficha(ficha_id)
    config = ConfiguracionAlertas.query.filter_by(ficha_id=ficha_id).first()
    if not config:
        config = ConfiguracionAlertas(ficha_id=ficha_id)
        db.session.add(config)
        db.session.commit()

    aprendices = Aprendiz.query_en_formacion(ficha_id).order_by(Aprendiz.apellidos).all()

    stats_map, total_sesiones = calcular_semaforo(ficha_id, aprendices, config)

    datos_alertas = []
    for ap in aprendices:
        stats = stats_map[ap.id]
        datos_alertas.append({
            'aprendiz': ap,
            'total_sesiones': total_sesiones,
            'pct_asistencia': stats['pct_asistencia'],
            'tareas_pendientes': stats['tareas_pendientes'],
            'total_faltas': stats['faltas_no_justificadas'] + stats['faltas_justificadas'],
            'no_justificadas': stats['faltas_no_justificadas'],
            'justificadas': stats['faltas_justificadas'],
            'nivel': stats['nivel'],
        })

    from app.services.alertas import obtener_config_comite
    alertas_cronograma = Alerta.query.filter_by(
        ficha_id=ficha_id, aprendiz_id=None, estado='activa'
    ).order_by(Alerta.fecha_generada.desc()).all()
    return render_template('alertas.html', ficha=ficha, config=config,
                           config_comite=obtener_config_comite(ficha_id),
                           datos_alertas=datos_alertas,
                           alertas_cronograma=alertas_cronograma,
                           cronograma=obtener_cronograma(ficha))


@instructor_bp.route('/fichas/<int:ficha_id>/alertas/config', methods=['POST'])
@login_required
def guardar_config_alertas(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    config = ConfiguracionAlertas.query.filter_by(ficha_id=ficha_id).first()
    if not config:
        config = ConfiguracionAlertas(ficha_id=ficha_id)
        db.session.add(config)

    try:
        umbral_amarillo = int(request.form.get('umbral_amarillo', 3))
        umbral_rojo = int(request.form.get('umbral_rojo', 6))
        max_fallas = int(request.form.get('max_fallas_trimestre', 3))
    except (TypeError, ValueError):
        flash('Los umbrales deben ser números enteros.', 'error')
        return redirect(url_for('instructor.alertas', ficha_id=ficha_id))
    if min(umbral_amarillo, umbral_rojo, max_fallas) < 1:
        flash('Los umbrales deben ser mayores que cero.', 'error')
        return redirect(url_for('instructor.alertas', ficha_id=ficha_id))
    if umbral_rojo <= umbral_amarillo:
        flash('La alerta roja debe activarse después de la alerta amarilla.', 'error')
        return redirect(url_for('instructor.alertas', ficha_id=ficha_id))

    config.umbral_amarillo = umbral_amarillo
    config.umbral_rojo = umbral_rojo
    config.max_fallas_trimestre_laboral = max_fallas
    db.session.commit()
    actualizar_alertas_ficha(ficha_id)

    flash('Configuración de alertas actualizada.', 'success')
    return redirect(url_for('instructor.alertas', ficha_id=ficha_id))


@instructor_bp.route('/fichas/<int:ficha_id>/reporte-asistencia')
@login_required
def reporte_asistencia(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    formato = request.args.get('formato', 'excel')
    fecha_inicio_str = request.args.get('fecha_inicio')
    fecha_fin_str = request.args.get('fecha_fin')

    aprendices = Aprendiz.query_en_formacion(ficha_id).order_by(Aprendiz.apellidos).all()

    query_sesiones = (
        SesionAsistencia.query
        .join(RegistroAsistencia)
        .filter(SesionAsistencia.ficha_id == ficha_id)
        .distinct()
    )
    
    if fecha_inicio_str:
        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            query_sesiones = query_sesiones.filter(SesionAsistencia.fecha >= fecha_inicio)
        except ValueError:
            pass
            
    if fecha_fin_str:
        try:
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
            query_sesiones = query_sesiones.filter(SesionAsistencia.fecha <= fecha_fin)
        except ValueError:
            pass
            
    sesiones = query_sesiones.order_by(SesionAsistencia.fecha).all()

    if formato == 'pdf':
        return _generar_pdf_asistencia(ficha, aprendices, sesiones)
    return _generar_excel_asistencia(ficha, aprendices, sesiones)


def _generar_excel_asistencia(ficha, aprendices, sesiones):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Asistencia'

    ws.append(['Ficha', ficha.codigo, ficha.nombre_programa])
    ws.append([])

    encabezado = ['Documento', 'Nombre', 'Apellidos']
    for s in sesiones:
        encabezado.append(s.fecha.strftime('%Y-%m-%d'))
    encabezado.extend(['Total Faltas', 'Justificadas', 'No Justificadas', '% Asistencia'])
    ws.append(encabezado)

    sesiones_ids = [s.id for s in sesiones]

    for ap in aprendices:
        fila = [ap.documento, ap.nombre, ap.apellidos]
        total_faltas = 0
        justificadas = 0

        for s in sesiones:
            registro = RegistroAsistencia.query.filter_by(sesion_id=s.id, aprendiz_id=ap.id).first()
            estado = registro.estado if registro else '-'
            fila.append(estado)
            if registro and registro.estado in ('FALTA', 'FALTA_JUSTIFICADA', 'EXCUSA_MEDICA'):
                total_faltas += 1
                if registro.estado in ('FALTA_JUSTIFICADA', 'EXCUSA_MEDICA'):
                    justificadas += 1

        no_justificadas = total_faltas - justificadas
        pct = ((len(sesiones) - total_faltas) / len(sesiones) * 100) if sesiones else 100
        fila.extend([total_faltas, justificadas, no_justificadas, f'{pct:.1f}%'])
        ws.append(fila)

    from flask import send_file
    import io
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True,
                     download_name=f'reporte_asistencia_{ficha.codigo}.xlsx')


def _generar_pdf_asistencia(ficha, aprendices, sesiones):
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    import io

    from reportlab.lib.enums import TA_CENTER
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    styles['Title'].alignment = TA_CENTER
    styles['Normal'].alignment = TA_CENTER
    elements = []

    elements.append(Paragraph(f'Reporte de Asistencia - Ficha {ficha.codigo}', styles['Title']))
    elements.append(Paragraph(f'{ficha.nombre_programa}', styles['Normal']))
    
    if sesiones:
        rango = f'Desde: {sesiones[0].fecha.strftime("%Y-%m-%d")} Hasta: {sesiones[-1].fecha.strftime("%Y-%m-%d")}'
        elements.append(Paragraph(rango, styles['Normal']))
        
    elements.append(Spacer(1, 12))

    datos = [['Documento', 'Nombre', 'Apellidos', 'Faltas', 'Justif.', 'No Justif.', '% Asist.']]
    sesiones_ids = [s.id for s in sesiones] if sesiones else []

    for ap in aprendices:
        if not sesiones_ids:
            total = just = no_just = 0
            pct = 100
        else:
            total = RegistroAsistencia.query.filter(
                RegistroAsistencia.sesion_id.in_(sesiones_ids),
                RegistroAsistencia.aprendiz_id == ap.id,
                RegistroAsistencia.estado.in_(['FALTA', 'FALTA_JUSTIFICADA', 'EXCUSA_MEDICA']),
            ).count()
            just = RegistroAsistencia.query.filter(
                RegistroAsistencia.sesion_id.in_(sesiones_ids),
                RegistroAsistencia.aprendiz_id == ap.id,
                RegistroAsistencia.estado.in_(['FALTA_JUSTIFICADA', 'EXCUSA_MEDICA']),
            ).count()
            no_just = total - just
            pct = ((len(sesiones) - total) / len(sesiones) * 100)
            
        datos.append([ap.documento, ap.nombre, ap.apellidos, str(total), str(just), str(no_just), f'{pct:.1f}%'])

    ancho_util = doc.width
    tabla = Table(datos, colWidths=[ancho_util*0.15, ancho_util*0.25, ancho_util*0.25, ancho_util*0.08, ancho_util*0.09, ancho_util*0.09, ancho_util*0.09], hAlign='CENTER')
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#39A900')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
    ]))
    elements.append(tabla)

    doc.build(elements)
    buffer.seek(0)

    from flask import send_file
    return send_file(buffer, mimetype='application/pdf', as_attachment=True,
                     download_name=f'reporte_asistencia_{ficha.codigo}.pdf')


@instructor_bp.route('/fichas/<int:ficha_id>/materiales', methods=['GET', 'POST'])
@login_required
def materiales(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    if request.method == 'POST':
        archivo = request.files.get('archivo')
        descripcion = request.form.get('descripcion', '').strip()

        try:
            resultado = ArchivoService.guardar(
                archivo=archivo,
                carpeta=TiposCarpeta.MATERIALES_FICHA,
                subcarpeta=str(ficha_id),
                check_magic=True,
            )
        except ErrorArchivo as exc:
            flash(str(exc), 'error')
            return redirect(url_for('instructor.materiales', ficha_id=ficha_id))

        material = MaterialFicha(
            ficha_id=ficha_id,
            instructor_id=current_user.id,
            nombre_archivo=resultado.nombre_original,
            url_archivo=resultado.url,
            descripcion=descripcion,
        )
        db.session.add(material)
        db.session.commit()
        flash('Material subido exitosamente.', 'success')
        return redirect(url_for('instructor.materiales', ficha_id=ficha_id))

    materiales_db = MaterialFicha.query.filter_by(ficha_id=ficha_id).order_by(MaterialFicha.subido_en.desc()).all()
    tamanos = {m.id: ArchivoService.obtener_tamano(m.url_archivo) for m in materiales_db}
    return render_template('materiales.html', ficha=ficha, materiales=materiales_db, tamanos=tamanos,
                           cronograma=obtener_cronograma(ficha))


@instructor_bp.route('/fichas/<int:ficha_id>/materiales/<int:material_id>/eliminar', methods=['POST'])
@login_required
def eliminar_material(ficha_id, material_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    material = db.session.get(MaterialFicha, material_id)
    if not material or material.ficha_id != ficha_id:
        flash('Material no encontrado.', 'error')
        return redirect(url_for('instructor.materiales', ficha_id=ficha_id))
        
    if material.instructor_id != current_user.id and not current_user.es_admin and ficha.instructor_id != current_user.id:
        flash('No tienes permiso para eliminar este material.', 'error')
        return redirect(url_for('instructor.materiales', ficha_id=ficha_id))

    ArchivoService.eliminar(material.url_archivo)
    db.session.delete(material)
    db.session.commit()
    flash('Material eliminado.', 'success')
    return redirect(url_for('instructor.materiales', ficha_id=ficha_id))


@instructor_bp.route('/fichas/<int:ficha_id>/juicios')
@login_required
def juicios(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    # Estadísticas globales. La vista recorre `todos` varias veces leyendo
    # `j.aprendiz`, asi que se carga la relacion de una vez: sin joinedload
    # cada aprendiz distinto dispara un SELECT extra al construir la tabla.
    todos = (
        JuicioEvaluativo.query
        .options(joinedload(JuicioEvaluativo.aprendiz))
        .join(Aprendiz, JuicioEvaluativo.aprendiz_id == Aprendiz.id)
        .filter(
            JuicioEvaluativo.ficha_id == ficha_id,
            Aprendiz.estado.in_(ESTADOS_EN_FORMACION),
        )
        .all()
    )

    _tipo_prioridad = {'tecnica': 0, 'transversal': 1, 'ingles': 2}
    estadisticas = {
        'total': 0, 'aprobados': 0, 'por_evaluar': 0,
        'tecnica': 0, 'transversal': 0, 'ingles': 0,
    }
    aprendices_dict = {}
    competencias_summary = {}
    instructores_resumen = {}
    rango_aprobacion = {'100%': 0, '75-99%': 0, '50-74%': 0, '25-49%': 0, '0-24%': 0}
    primera_evaluacion = None
    ultima_evaluacion = None

    for j in todos:
        juicio_upper = j.juicio.upper() if j.juicio else ''
        es_aprobado_global = bool(j.juicio and 'APROBADO' in juicio_upper)
        es_aprobado_comp = es_aprobado_global and 'AUN NO' not in juicio_upper
        tipo = j.tipo_competencia or 'tecnica'
        func = j.funcionario_registro or 'Sin registro'

        estadisticas['total'] += 1
        if es_aprobado_global:
            estadisticas['aprobados'] += 1
        if not j.juicio or 'EVALUAR' in juicio_upper:
            estadisticas['por_evaluar'] += 1
        if tipo in estadisticas:
            estadisticas[tipo] += 1

        if j.aprendiz_id not in aprendices_dict:
            aprendices_dict[j.aprendiz_id] = {
                'aprendiz': j.aprendiz,
                'total': 0, 'aprobados': 0,
                'tecnica': 0, 'tecnica_aprobada': 0,
                'transversal': 0, 'transversal_aprobada': 0,
                'ingles': 0, 'ingles_aprobada': 0,
            }
        datos = aprendices_dict[j.aprendiz_id]
        datos['total'] += 1
        if es_aprobado_global:
            datos['aprobados'] += 1
        datos[tipo] += 1
        if es_aprobado_global:
            datos[f"{tipo}_aprobada"] += 1
        if j.funcionario_registro:
            datos.setdefault('evaluadores', set()).add(j.funcionario_registro)

        comp = j.competencia or 'Sin nombre'
        if comp not in competencias_summary:
            competencias_summary[comp] = {
                'nombre': comp, 'tipo': tipo,
                'total': 0, 'aprobados': 0, 'pendientes': 0,
                'detalles': [],
            }
        competencias_summary[comp]['total'] += 1
        if es_aprobado_comp:
            competencias_summary[comp]['aprobados'] += 1
        else:
            competencias_summary[comp]['pendientes'] += 1
        competencias_summary[comp]['detalles'].append({
            'documento': j.aprendiz.documento if j.aprendiz else '-',
            'nombre': f"{j.aprendiz.apellidos} {j.aprendiz.nombre}" if j.aprendiz else '-',
            'rap': j.resultado_aprendizaje or '-',
            'estado': 'APROBADO' if es_aprobado_comp else 'POR EVALUAR',
            'fecha': j.fecha_juicio.strftime('%d/%m/%Y') if j.fecha_juicio else '-',
            'evaluador': j.funcionario_registro or '-',
        })

        if func not in instructores_resumen:
            instructores_resumen[func] = {'total': 0, 'aprobados': 0, 'pendientes': 0}
        instructores_resumen[func]['total'] += 1
        if es_aprobado_comp:
            instructores_resumen[func]['aprobados'] += 1
        else:
            instructores_resumen[func]['pendientes'] += 1

        if j.fecha_juicio:
            if primera_evaluacion is None or j.fecha_juicio < primera_evaluacion:
                primera_evaluacion = j.fecha_juicio
            if ultima_evaluacion is None or j.fecha_juicio > ultima_evaluacion:
                ultima_evaluacion = j.fecha_juicio

    for d in aprendices_dict.values():
        d['pct_total'] = round((d['aprobados'] / d['total'] * 100)) if d['total'] > 0 else 0
        d['pct_tecnica'] = round((d['tecnica_aprobada'] / d['tecnica'] * 100)) if d['tecnica'] > 0 else 0
        d['pct_transversal'] = round((d['transversal_aprobada'] / d['transversal'] * 100)) if d['transversal'] > 0 else 0
        d['pct_ingles'] = round((d['ingles_aprobada'] / d['ingles'] * 100)) if d['ingles'] > 0 else 0
        if 'evaluadores' in d:
            d['evaluadores'] = sorted(d['evaluadores'])
        pct = d['pct_total']
        if pct == 100:
            rango_aprobacion['100%'] += 1
        elif pct >= 75:
            rango_aprobacion['75-99%'] += 1
        elif pct >= 50:
            rango_aprobacion['50-74%'] += 1
        elif pct >= 25:
            rango_aprobacion['25-49%'] += 1
        else:
            rango_aprobacion['0-24%'] += 1

    aprendices_stats = sorted(aprendices_dict.values(), key=lambda x: x['aprendiz'].apellidos)
    pct_global_juicios = round((estadisticas['aprobados'] / estadisticas['total'] * 100)) if estadisticas['total'] > 0 else 0

    for comp in competencias_summary.values():
        comp['pct'] = round((comp['aprobados'] / comp['total'] * 100)) if comp['total'] > 0 else 0
        comp['detalles'] = sorted(comp['detalles'], key=lambda x: x['nombre'])

    competencias_ordenadas_juicios = sorted(
        competencias_summary.values(),
        key=lambda x: (
            0 if x['aprobados'] > 0 else 1,
            -x['pct'],
            -x['aprobados'],
            _tipo_prioridad.get(x.get('tipo') or 'tecnica', 99),
            -x['total'],
        ),
    )

    for func in instructores_resumen.values():
        func['pct'] = round((func['aprobados'] / func['total'] * 100)) if func['total'] > 0 else 0

    instructores_ordenados = sorted(instructores_resumen.items(), key=lambda x: x[1]['total'], reverse=True)

    return render_template('juicios.html', ficha=ficha, estadisticas=estadisticas, 
                           aprendices_stats=aprendices_stats, cronograma=obtener_cronograma(ficha),
                           pct_global_juicios=pct_global_juicios,
                           competencias_summary=competencias_ordenadas_juicios,
                           instructores_resumen=instructores_ordenados,
                           rango_aprobacion=rango_aprobacion,
                           primera_evaluacion=primera_evaluacion,
                           ultima_evaluacion=ultima_evaluacion)

@instructor_bp.route('/fichas/<int:ficha_id>/estadisticas')
@login_required
def estadisticas(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    # 1. Estadísticas de estado de los aprendices (el desglose incluye a todos
    # porque su propósito es mostrar cuántos siguen o salieron de la formación).
    todos_los_aprendices = Aprendiz.query.filter_by(ficha_id=ficha_id).all()
    estados = {}
    total_aprendices = len(todos_los_aprendices)
    for a in todos_los_aprendices:
        estados[a.estado] = estados.get(a.estado, 0) + 1

    # El resto de métricas académicas solo considera a quienes están en formación.
    aprendices = [a for a in todos_los_aprendices if a.en_formacion]
    ids_en_formacion = {a.id for a in aprendices}

    # 2. Historial de juicios por instructor
    # Traemos todos los juicios y relacionamos con instructores si es posible.
    # Dado que un juicio puede tener varios instructores que lo importaron (en JuicioEvaluativoInstructor),
    # o usamos el funcionario_registro de JuicioEvaluativo.
    juicios = [
        j for j in JuicioEvaluativo.query.filter_by(ficha_id=ficha_id).all()
        if j.aprendiz_id in ids_en_formacion
    ]

    # Agrupar por funcionario_registro que viene en el excel
    instructores_stats = {}
    aprendices_riesgo_dict = {}
    resultados_criticos_dict = {}
    
    total_juicios_ficha = len(juicios)
    total_aprobados_ficha = 0

    for j in juicios:
        func = j.funcionario_registro or 'Sin Registro'
        if func not in instructores_stats:
            instructores_stats[func] = {
                'total': 0, 'aprobados': 0, 'no_aprobados': 0,
                'tecnica': 0, 'transversal': 0, 'ingles': 0,
                'aprendices_evaluados': set(),
                'aprendices_aprobados': set(),
            }
        
        instructores_stats[func]['total'] += 1
        instructores_stats[func]['aprendices_evaluados'].add(j.aprendiz_id)
        es_aprobado = bool(j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
        if es_aprobado:
            instructores_stats[func]['aprobados'] += 1
            instructores_stats[func]['aprendices_aprobados'].add(j.aprendiz_id)
            total_aprobados_ficha += 1
        else:
            instructores_stats[func]['no_aprobados'] += 1
            
            # Contabilizar para aprendices en riesgo
            if j.aprendiz_id not in aprendices_riesgo_dict:
                aprendices_riesgo_dict[j.aprendiz_id] = 0
            aprendices_riesgo_dict[j.aprendiz_id] += 1
            
            # Contabilizar para resultados críticos
            res = j.resultado_aprendizaje
            if res not in resultados_criticos_dict:
                resultados_criticos_dict[res] = 0
            resultados_criticos_dict[res] += 1
            
        tipo = j.tipo_competencia or 'tecnica'
        instructores_stats[func][tipo] += 1
        
    # Convertir sets a conteos para serialización en template
    for func, stats in instructores_stats.items():
        stats['total_aprendices'] = len(stats['aprendices_evaluados'])
        stats['total_aprendices_aprobados'] = len(stats['aprendices_aprobados'])
        del stats['aprendices_evaluados']
        del stats['aprendices_aprobados']
        
    # Obtener los top 5 aprendices en riesgo
    top_aprendices_riesgo = []
    for a_id, count in sorted(aprendices_riesgo_dict.items(), key=lambda x: x[1], reverse=True)[:10]:
        ap = db.session.get(Aprendiz, a_id)
        if ap:
            top_aprendices_riesgo.append({
                'aprendiz': ap,
                'pendientes': count
            })
            
    # Obtener los top 5 resultados críticos
    top_resultados = sorted(resultados_criticos_dict.items(), key=lambda x: x[1], reverse=True)[:5]
    
    pct_aprobacion_global = round((total_aprobados_ficha / total_juicios_ficha * 100) if total_juicios_ficha > 0 else 0)

    # ---- NUEVAS ESTADÍSTICAS ----

    # 3. Estadísticas por competencia
    competencias_stats = {}
    aprendices_dict = {a.id: a for a in aprendices}
    
    for j in juicios:
        comp = j.competencia or 'Sin nombre'
        if comp not in competencias_stats:
            competencias_stats[comp] = {
                'nombre': comp,
                'tipo': j.tipo_competencia or 'tecnica',
                'total': 0, 'aprobados': 0, 'aprendices': set(),
                'resultados': set(),
                'aprendices_aprobados_ids': set()
            }
        competencias_stats[comp]['total'] += 1
        competencias_stats[comp]['aprendices'].add(j.aprendiz_id)
        if j.resultado_aprendizaje:
            competencias_stats[comp]['resultados'].add(j.resultado_aprendizaje)
            
        if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper():
            competencias_stats[comp]['aprobados'] += 1
            competencias_stats[comp]['aprendices_aprobados_ids'].add(j.aprendiz_id)

    for comp in competencias_stats.values():
        comp['pct'] = round((comp['aprobados'] / comp['total'] * 100)) if comp['total'] > 0 else 0
        comp['num_aprendices'] = len(comp['aprendices'])
        comp['pendientes'] = comp['total'] - comp['aprobados']
        
        comp['resultados_lista'] = sorted(list(comp['resultados']))
        
        aprendices_aprob_objs = []
        for a_id in comp['aprendices_aprobados_ids']:
            ap = aprendices_dict.get(a_id)
            if ap:
                aprendices_aprob_objs.append({
                    'id': ap.id,
                    'nombre_completo': f"{ap.nombre} {ap.apellidos}",
                    'documento': ap.documento
                })
        comp['aprendices_aprobados_lista'] = sorted(aprendices_aprob_objs, key=lambda x: x['nombre_completo'])
        
        del comp['aprendices']
        del comp['resultados']
        del comp['aprendices_aprobados_ids']

    competencias_ordenadas = sorted(competencias_stats.values(), key=lambda x: (-x['pendientes'], x['pct']))

    # 4. Timeline de evaluaciones por mes
    timeline = {}
    for j in juicios:
        if j.fecha_juicio:
            mes = j.fecha_juicio.strftime('%Y-%m')
            if mes not in timeline:
                timeline[mes] = {'total': 0, 'aprobados': 0}
            timeline[mes]['total'] += 1
            if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper():
                timeline[mes]['aprobados'] += 1
    timeline_ordenado = sorted(timeline.items())

    # 5. Resumen general
    aprendices_ids = {j.aprendiz_id for j in juicios}
    aprendices_con_todos = 0
    aprendices_sin_ninguno = 0
    for a_id in aprendices_ids:
        juicios_ap = [j for j in juicios if j.aprendiz_id == a_id]
        total_ap = len(juicios_ap)
        aprobados_ap = sum(1 for j in juicios_ap if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
        if aprobados_ap == total_ap:
            aprendices_con_todos += 1
        elif aprobados_ap == 0:
            aprendices_sin_ninguno += 1

    juicios_transversales = [j for j in juicios if j.tipo_competencia == 'transversal']
    transversales_aprobados = sum(1 for j in juicios_transversales if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
    transversales_faltantes = len(juicios_transversales) - transversales_aprobados

    juicios_ingles = [j for j in juicios if j.tipo_competencia == 'ingles']
    ingles_aprobados = sum(1 for j in juicios_ingles if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
    ingles_faltantes = len(juicios_ingles) - ingles_aprobados

    resumen = {
        'total_aprendices_con_juicios': len(aprendices_ids),
        'total_competencias': len(competencias_stats),
        'total_resultados': len({j.resultado_aprendizaje for j in juicios if j.resultado_aprendizaje}),
        'aprendices_con_todos': aprendices_con_todos,
        'aprendices_sin_ninguno': aprendices_sin_ninguno,
        'promedio_juicios_por_aprendiz': round(total_juicios_ficha / len(aprendices_ids), 1) if aprendices_ids else 0,
        'transversales_vistas': len(juicios_transversales),
        'transversales_faltantes': transversales_faltantes,
        'ingles_aprobados': ingles_aprobados,
        'ingles_faltantes': ingles_faltantes,
    }

    # 6. Distribución de aprobación entre aprendices
    distribucion_aprobacion = {'0-25': 0, '26-50': 0, '51-75': 0, '76-99': 0, '100': 0}
    for a_id in aprendices_ids:
        juicios_ap = [j for j in juicios if j.aprendiz_id == a_id]
        total_ap = len(juicios_ap)
        if total_ap == 0:
            continue
        aprobados_ap = sum(1 for j in juicios_ap if j.juicio and 'APROBADO' in j.juicio.upper() and 'AUN NO' not in j.juicio.upper())
        pct_ap = round(aprobados_ap / total_ap * 100)
        if pct_ap == 100:
            distribucion_aprobacion['100'] += 1
        elif pct_ap >= 76:
            distribucion_aprobacion['76-99'] += 1
        elif pct_ap >= 51:
            distribucion_aprobacion['51-75'] += 1
        elif pct_ap >= 26:
            distribucion_aprobacion['26-50'] += 1
        else:
            distribucion_aprobacion['0-25'] += 1

    # 7. Top 3 mejores competencias (más aprobadas)
    mejores_competencias = sorted(competencias_stats.values(), key=lambda x: x['pct'], reverse=True)[:5]
    peores_competencias = sorted(competencias_stats.values(), key=lambda x: x['pct'])[:5]

    return render_template(
        'estadisticas.html', 
        ficha=ficha, 
        cronograma=obtener_cronograma(ficha),
        estados=estados,
        total_aprendices=total_aprendices,
        instructores_stats=instructores_stats,
        top_aprendices=top_aprendices_riesgo,
        top_resultados=top_resultados,
        pct_global=pct_aprobacion_global,
        competencias_stats=competencias_ordenadas,
        timeline=timeline_ordenado,
        resumen=resumen,
        distribucion_aprobacion=distribucion_aprobacion,
        mejores_competencias=mejores_competencias,
        peores_competencias=peores_competencias,
    )
