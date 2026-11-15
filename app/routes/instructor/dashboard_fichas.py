from datetime import datetime
import json
from pathlib import Path

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
import openpyxl
from sqlalchemy import func, or_
from werkzeug.utils import secure_filename

from app import db
from app.helpers import utc_now
from app.models.alertas import Alerta, ConfiguracionAlertas, PlanMejoramiento
from app.models.aprendiz import ESTADOS_EN_FORMACION, Aprendiz
from app.models.archivo_ficha import ArchivoFichaVersion, TIPO_PLANEACION, TIPO_REPORTE_JUICIOS
from app.models.aseo import ConfiguracionAseo
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.models.ficha import Ficha
from app.models.ficha_instructor import FichaInstructor
from app.models.importacion import ImportacionJob
from app.models.juicio import JuicioEvaluativo
from app.models.observador import NotaObservador
from app.models.ranking import ConfiguracionRanking
from app.models.tarea import Entrega, Tarea
from app.services.alertas import notificar_juicios_importados
from app.services.archivos import ArchivoDuplicado, ArchivoService, ErrorArchivo
from app.services.cortes import corte_actual, corte_visible, cortes_visibles
from app.services.cronograma import obtener_cronograma
from app.services.fases_dashboard import obtener_seguimiento_fases_dashboard
from app.services.importacion_ficha import (
    ErrorImportacion,
    es_reporte_oficial,
    leer_metadata_archivo,
    validar_reporte_ficha,
)
from app.services.importacion_jobs import ColaImportacionesNoDisponible, encolar_importacion
from app.services.permisos import configurar_rol_aprendiz, puede_gestionar_ficha
from app.services.resumen_ficha import obtener_resumen_ficha_360
from app.services.versiones_archivos import actualizar_estado, ultimas_versiones_por_fichas
import app.routes.instructor as _pkg

from . import _actualizar_indicadores_carga, instructor_bp, obtener_fichas


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
                               recomendaciones_fichas={})


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

        # --- Juicios evaluativos y avance de certificación ---
        # Un solo agregado por aprendiz alimenta el resumen global y el conteo
        # de certificados, evitando recorrer de nuevo toda la tabla de juicios.
        juicios_por_ficha = {}
        es_aprobado_sql = (
            func.upper(JuicioEvaluativo.juicio).like('%APROBADO%') &
            ~func.upper(JuicioEvaluativo.juicio).like('%AUN NO%')
        )
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
            pct_asistencia = round(((posibles - faltas) / posibles * 100), 1) if posibles else 100.0

            tareas_data = tareas_por_ficha.get(fid, {'total': 0, 'entregas': 0, 'pendientes': 0})
            if tareas_data['total'] and n_ap:
                pct_entregas = round((tareas_data['entregas'] / (tareas_data['total'] * n_ap) * 100))
            else:
                pct_entregas = 100

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

    def get_order(fase):
        return {'lectiva': 1, 'por_iniciar': 2, 'productiva': 3, 'finalizada': 4, 'sin_fechas': 5}.get(fase, 99)

    fichas.sort(key=lambda f: get_order(cronogramas[f.id]['fase']))

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
        from app.tyt.consulta import obtener_seguimiento_por_fichas
        from flask import g
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
                           recomendaciones_fichas=recomendaciones_fichas)


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
    partes = []
    if resultado.get('nuevos', 0):
        partes.append(f"{resultado['nuevos']} aprendices nuevos")
    if resultado.get('actualizados', 0):
        partes.append(f"{resultado['actualizados']} aprendices actualizados")
    if resultado.get('juicios_nuevos', 0):
        partes.append(f"{resultado['juicios_nuevos']} juicios evaluativos incorporados")
    if resultado.get('juicios_actualizados', 0):
        partes.append(f"{resultado['juicios_actualizados']} juicios evaluativos actualizados")

    repetidos = resultado.get('juicios_repetidos', 0)
    if repetidos:
        if not resultado.get('juicios_nuevos', 0) and not resultado.get('juicios_actualizados', 0):
            partes.append(f"{repetidos} juicios evaluativos verificados y conservados al día")
        else:
            partes.append(f"{repetidos} juicios ya estaban en el historial")

    sesiones = resultado.get('sesiones_creadas', 0)
    if sesiones:
        partes.append(f"{sesiones} sesiones de clase creadas automáticamente")

    if not partes:
        return "El archivo fue procesado correctamente."
    return " · ".join(partes) + "."


@instructor_bp.route('/fichas/importar-reporte', methods=['POST'])
@login_required
def importar_reporte_ficha():
    archivo = request.files.get('archivo')
    if not archivo or not archivo.filename.lower().endswith(('.xlsx', '.xls')):
        flash('Selecciona el Reporte de Juicios Evaluativos en formato .xls o .xlsx.', 'error')
        return redirect(url_for('instructor.fichas'))

    try:
        resultado = _pkg.importar_archivo(
            archivo,
            ficha_actual=None,
            instructor_id=current_user.id,
            crear_ficha=True,
        )
        ficha = resultado['ficha']
        db.session.commit()
        archivos_respaldo = []
        try:
            archivo.stream.seek(0)
            version = _pkg.crear_version(
                archivo,
                ficha.id,
                current_user.id,
                TIPO_REPORTE_JUICIOS,
                metadata=resultado.get('metadata'),
                permitir_existente=True,
                archivos_creados=archivos_respaldo,
            )
            actualizar_estado(version, 'procesado', detalle=_resumen_importacion(resultado))
            db.session.commit()
        except ArchivoDuplicado as exc:
            db.session.rollback()
            flash(str(exc), 'warning')
        except Exception:
            db.session.rollback()
            for ruta_nueva in archivos_respaldo:
                ArchivoService.eliminar(ruta_nueva)
            current_app.logger.exception('La ficha se importó, pero no se pudo guardar la versión del reporte.')
            flash(
                'Los datos de la ficha se importaron, pero no fue posible guardar el reporte original. '
                'Vuelva a cargar el reporte para conservar su respaldo descargable.',
                'warning',
            )
        _actualizar_indicadores_carga(ficha.id)

        accion = 'creada' if resultado['ficha_creada'] else 'vinculada'
        mensaje = (
            f"Ficha {ficha.codigo} {accion} automáticamente. "
            f"{_resumen_importacion(resultado)}"
        )
        if resultado.get('solo_agregar'):
            mensaje += (
                ' La ficha ya pertenecía a otro instructor: quedaste como colaborador y solo '
                'se agregaron aprendices y juicios nuevos, sin cambiar los datos existentes.'
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


@instructor_bp.route('/fichas/<int:ficha_id>')
@instructor_bp.route('/fichas/<int:ficha_id>/resumen')
@login_required
def vision_general(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha or not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada o sin permisos de acceso.', 'error')
        return redirect(url_for('instructor.fichas'))

    corte_id = request.args.get('corte_id', type=int)
    corte_sel = corte_visible(ficha.id, corte_id) if corte_id else corte_actual(ficha.id)

    resumen = obtener_resumen_ficha_360(
        ficha,
        instructor_id=current_user.id,
        corte_id=corte_sel.id if corte_sel else None,
    )
    cortes = cortes_visibles(ficha.id)

    return render_template(
        'vision_general.html',
        ficha=ficha,
        resumen=resumen,
        fases_data=resumen.get('fases_data') if resumen else None,
        cortes=cortes,
        corte_actual=corte_sel,
    )


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
    version = None
    archivos_creados = []
    ruta_temporal = None
    volver_planeacion = request.form.get('retorno') == 'planeacion'
    volver_juicios = request.form.get('retorno') == 'juicios'
    aprendiz_admin_id = request.form.get('aprendiz_administrativo_id', type=int)
    try:
        metadata_reporte = leer_metadata_archivo(archivo)
        if es_reporte_oficial(metadata_reporte):
            validar_reporte_ficha(ficha, metadata_reporte)
        version = _pkg.crear_version(
            archivo,
            ficha.id,
            current_user.id,
            TIPO_REPORTE_JUICIOS,
            metadata=metadata_reporte,
            permitir_existente=True,
            archivos_creados=archivos_creados,
        )
        if current_app.config.get('IMPORTACIONES_ASINCRONAS'):
            archivo.stream.seek(0)
            nombre_archivo = secure_filename(archivo.filename) or 'reporte.xls'
            # Dentro de UPLOAD_FOLDER porque el worker corre en otro contenedor
            # y solo comparte con el web el volumen `uploads`.
            ruta = str(Path(current_app.config['UPLOAD_FOLDER']) / version.ruta_archivo)

            job = ImportacionJob(
                ficha_id=ficha.id,
                instructor_id=current_user.id,
                archivo_version_id=version.id,
                archivo_path=ruta,
                nombre_archivo=nombre_archivo,
                estado='encolado',
                aprendiz_administrativo_id=aprendiz_admin_id,
            )
            db.session.add(job)
            db.session.commit()
            archivos_creados.clear()
            ruta_temporal = None
            importacion_job_id = job.id
            try:
                encolar_importacion(job.id, current_app.config['IMPORT_QUEUE_NAME'])
            except ColaImportacionesNoDisponible as exc:
                db.session.rollback()
                # El trabajo apunta al original versionado; no es un temporal.
                job = db.session.get(ImportacionJob, job.id)
                if job:
                    job.estado = 'error'
                    job.error = 'No fue posible conectar con la cola de procesamiento.'
                    job.terminado_en = utc_now()
                    version = db.session.get(ArchivoFichaVersion, version.id)
                    if version:
                        actualizar_estado(version, 'error', detalle=job.error)
                    db.session.commit()
                importacion_job_id = None
                # Conserva la versión permanente para descarga y diagnóstico.
                raise RuntimeError(
                    'No fue posible poner la importación en cola. '
                    'Revisa REDIS_URL y que el worker esté activo.'
                ) from exc

            flash(
                f'Solicitud recibida correctamente (trabajo #{job.id}). '
                'El archivo quedó en cola y se está procesando en segundo plano; '
                'puedes seguir usando el panel.',
                'success',
            )
        else:
            resultado = _pkg.importar_archivo(archivo, ficha, current_user.id)
            ficha = resultado['ficha']
            if aprendiz_admin_id:
                try:
                    configurar_rol_aprendiz(ficha.id, aprendiz_admin_id, True)
                except ValueError as err:
                    flash(f'No se pudo asignar el rol administrativo: {err}', 'warning')
            actualizar_estado(version, 'procesado', detalle=_resumen_importacion(resultado))
            notificar_juicios_importados(resultado, commit=False)
            db.session.commit()
            archivos_creados.clear()
            _actualizar_indicadores_carga(ficha.id)

            msg = _resumen_importacion(resultado)
            if resultado['errores']:
                flash(msg + f" {len(resultado['errores'])} errores.", 'warning')
                for err in resultado['errores'][:10]:
                    flash(err, 'error')
            else:
                flash(msg, 'success')

    except (ErrorArchivo, ErrorImportacion, RuntimeError) as exc:
        db.session.rollback()
        for ruta_nueva in archivos_creados:
            ArchivoService.eliminar(ruta_nueva)
        if ruta_temporal:
            ArchivoService.eliminar(ruta_temporal)
        flash(str(exc), 'error')
    except Exception:
        db.session.rollback()
        for ruta_nueva in archivos_creados:
            ArchivoService.eliminar(ruta_nueva)
        if ruta_temporal:
            ArchivoService.eliminar(ruta_temporal)
        current_app.logger.exception('Error inesperado al importar aprendices')
        flash('No fue posible procesar el archivo. Verifica el Excel e inténtalo de nuevo.', 'error')

    parametros = {'ficha_id': ficha.id}
    if importacion_job_id:
        parametros['importacion_id'] = importacion_job_id
    if volver_planeacion:
        return redirect(url_for('planeacion.analisis', **parametros))
    if volver_juicios:
        return redirect(url_for('instructor.juicios', **parametros))
    return redirect(url_for('instructor.aprendices', **parametros))


@instructor_bp.route('/fichas/<int:ficha_id>/importaciones/<int:job_id>', methods=['GET'])
@login_required
def estado_importacion(ficha_id, job_id):
    """Estado consultable para una barra de progreso del frontend."""
    ficha = db.session.get(Ficha, ficha_id)
    job = db.session.get(ImportacionJob, job_id)
    if not job or job.ficha_id != ficha_id or not puede_gestionar_ficha(ficha):
        return jsonify({'error': 'Importación no encontrada.'}), 404
    resultado = None
    if job.resultado:
        try:
            resultado = json.loads(job.resultado)
        except (TypeError, ValueError):
            resultado = job.resultado
    return jsonify({
        'id': job.id,
        'estado': job.estado,
        'resultado': resultado,
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
