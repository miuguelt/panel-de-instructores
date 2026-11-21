"""Llamado a lista y modal de asistencia por aprendiz."""
from datetime import date, datetime

from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from sqlalchemy.exc import IntegrityError, OperationalError

import app.routes.instructor as _pkg
from app import db
from app.models.alertas import ConfiguracionAlertas
from app.models.aprendiz import Aprendiz
from app.models.asistencia import (
    CAUSALES_JUSTIFICADAS,
    ESTADOS_ASISTENCIA,
    RegistroAsistencia,
    SesionAsistencia,
)
from app.models.corte import Corte
from app.models.ficha import Ficha
from app.services.asistencia import (
    construir_calendario_mes,
    contar_sesiones_registradas,
    guardar_asistencia,
    mapa_asistencia_por_fecha,
    mes_inicial_calendario,
    serie_asistencia,
)
from app.services.cortes import corte_actual, cortes_visibles
from app.services.permisos import puede_gestionar_asistencia, puede_gestionar_ficha

from . import calcular_semaforo, instructor_bp


@instructor_bp.route('/fichas/<int:ficha_id>/asistencia', methods=['GET', 'POST'])
@login_required
def asistencia(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    corte_id = request.values.get('corte_id', type=int)
    corte = corte_actual(ficha_id, corte_id=corte_id)
    if corte_id and not corte:
        flash('El corte no existe o no está compartido contigo.', 'error')
        return redirect(url_for('instructor.asistencia', ficha_id=ficha_id))
    corte_id = corte.id if corte else None
    parametros_corte = {'corte_id': corte_id} if corte_id else {}

    if request.method == 'POST':
        if corte and not puede_gestionar_asistencia(corte, ficha):
            flash('Puedes consultar este corte, pero no está habilitado para modificar la asistencia.', 'error')
            return redirect(url_for('instructor.asistencia', ficha_id=ficha_id, **parametros_corte))
        fecha_str = request.form.get('fecha', '')
        if not fecha_str:
            flash('Debes indicar la fecha de la sesión.', 'error')
            return redirect(url_for('instructor.asistencia', ficha_id=ficha_id, **parametros_corte))

        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            flash('La fecha de la sesión no tiene un formato válido.', 'error')
            return redirect(url_for('instructor.asistencia', ficha_id=ficha_id, **parametros_corte))

        aprendices = Aprendiz.query_llamado_lista(ficha_id).order_by(Aprendiz.apellidos).all()
        estados_validos = {valor for valor, _etiqueta in ESTADOS_ASISTENCIA}
        causales_validas = {valor for valor, _etiqueta in CAUSALES_JUSTIFICADAS}
        for aprendiz in aprendices:
            estado = request.form.get(f'asistencia_{aprendiz.id}')
            causal = request.form.get(f'causal_{aprendiz.id}', '')
            if estado not in estados_validos:
                flash(f'Selecciona la asistencia de {aprendiz.nombre} {aprendiz.apellidos}.', 'error')
                return redirect(url_for('instructor.asistencia', ficha_id=ficha_id, fecha=fecha.isoformat(), **parametros_corte))
            if estado in ('FALTA_JUSTIFICADA', 'EXCUSA_MEDICA') and causal not in causales_validas:
                flash(f'Selecciona una causal válida para {aprendiz.nombre} {aprendiz.apellidos}.', 'error')
                return redirect(url_for('instructor.asistencia', ficha_id=ficha_id, fecha=fecha.isoformat(), **parametros_corte))

        registros = {
            aprendiz.id: (
                request.form.get(f'asistencia_{aprendiz.id}'),
                request.form.get(f'causal_{aprendiz.id}', '') or None,
            )
            for aprendiz in aprendices
        }

        try:
            guardar_asistencia(ficha_id, fecha, registros, corte_id=corte_id)
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
                # Ajusta el turno de aseo de la fecha (reemplaza ausentes y recalcula)
                turno_aseo = _pkg.ajustar_turno_por_asistencia(ficha_id, fecha)
                db.session.commit()
            except Exception:
                db.session.rollback()
                tareas_secundarias_fallidas.append('turnos de aseo')
                current_app.logger.exception(
                    'La asistencia quedó guardada, pero falló el ajuste de aseo '
                    'para ficha %s y fecha %s', ficha_id, fecha
                )

            try:
                _pkg.actualizar_alertas_ficha(ficha_id)
            except Exception:
                db.session.rollback()
                tareas_secundarias_fallidas.append('alertas')
                current_app.logger.exception(
                    'La asistencia quedó guardada, pero falló la actualización '
                    'de alertas para ficha %s', ficha_id
                )

            try:
                _pkg.actualizar_participacion_ficha(ficha_id, corte_id=corte_id)
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

        return redirect(url_for('instructor.asistencia', ficha_id=ficha_id, fecha=fecha.isoformat(), **parametros_corte))

    fecha_param = request.args.get('fecha', date.today().isoformat())
    consulta_sesion = SesionAsistencia.query.filter_by(ficha_id=ficha_id, fecha=fecha_param)
    if corte_id is not None:
        consulta_sesion = consulta_sesion.filter(SesionAsistencia.corte_id == corte_id)
    sesion = consulta_sesion.first()

    registros_map = {}
    if sesion:
        for r in sesion.registros:
            registros_map[r.aprendiz_id] = r

    consulta_sesiones = (
        SesionAsistencia.query
        .join(RegistroAsistencia)
        .filter(SesionAsistencia.ficha_id == ficha_id)
    )
    if corte_id is not None:
        consulta_sesiones = consulta_sesiones.filter(SesionAsistencia.corte_id == corte_id)
    sesiones_recientes = consulta_sesiones.distinct().order_by(
        SesionAsistencia.fecha.desc()
    ).limit(10).all()

    config = ConfiguracionAlertas.query.filter_by(ficha_id=ficha_id).first()
    if not config:
        config = ConfiguracionAlertas(ficha_id=ficha_id)
        db.session.add(config)
        db.session.commit()

    # Los aprendices se cargan despues del commit: al confirmar la sesion
    # SQLAlchemy expira los objetos vivos y volver a leer aprendiz.id
    # recargaria cada fila una por una. Incluye condicionados.
    aprendices = Aprendiz.query_llamado_lista(ficha_id).order_by(Aprendiz.apellidos).all()

    stats_map, total_sesiones = calcular_semaforo(
        ficha_id, aprendices, config, corte_id=corte_id
    )

    serie = serie_asistencia(ficha_id, corte_id=corte_id)

    return render_template('asistencia.html',
                           ficha=ficha,
                           serie_asistencia=serie,
                           aprendices=aprendices,
                           registros_map=registros_map,
                           sesiones_recientes=sesiones_recientes,
                           stats_map=stats_map,
                           fecha_actual=fecha_param,
                           estados_asistencia=ESTADOS_ASISTENCIA,
                           causales_justificadas=CAUSALES_JUSTIFICADAS,
                           config=config,
                           sesion=sesion,
                           total_sesiones=total_sesiones,
                           cortes=cortes_visibles(ficha_id).order_by(
                               Corte.fecha_inicio.desc(), Corte.id.desc()
                           ).all(),
                           corte_actual=corte,
                           puede_editar_corte=puede_gestionar_asistencia(corte, ficha))


@instructor_bp.route('/fichas/<int:ficha_id>/asistencia/aprendiz/<int:aprendiz_id>/modal')
@login_required
def asistencia_aprendiz_modal(ficha_id, aprendiz_id):
    ficha = db.session.get(Ficha, ficha_id)
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not puede_gestionar_ficha(ficha) or not aprendiz or aprendiz.ficha_id != ficha_id:
        return 'Aprendiz no encontrado', 404

    corte_id = request.args.get('corte_id', type=int)
    corte = corte_actual(ficha_id, corte_id=corte_id)
    if corte_id and not corte:
        return 'Corte no encontrado', 404
    corte_id = corte.id if corte else None

    consulta_registros = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        RegistroAsistencia.aprendiz_id == aprendiz.id
    )
    if corte_id is not None:
        consulta_registros = consulta_registros.filter(SesionAsistencia.corte_id == corte_id)
    registros = consulta_registros.order_by(SesionAsistencia.fecha.asc()).all()

    config_alertas = ConfiguracionAlertas.query.filter_by(ficha_id=ficha_id).first()

    asistencia_map = mapa_asistencia_por_fecha(registros)
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

    for fecha_iso, evento in sorted(asistencia_map.items()):
        fecha_obj = date.fromisoformat(fecha_iso)
        dia_nom = DIAS_SEMANA_ES[fecha_obj.weekday()]
        fecha_fmt = f"{dia_nom}, {fecha_obj.day} de {MESES_ES[fecha_obj.month]} de {fecha_obj.year}"

        causal_label = CAUSALES_DICT.get(
            evento['causal_justificacion'], evento['causal_justificacion'] or ''
        )
        evento['causal'] = causal_label
        evento['fecha_fmt'] = fecha_fmt
        evento.pop('causal_justificacion', None)
        estado = evento['estado']

        if estado == 'ASISTE':
            total_asistencias += 1
        elif estado == 'TARDANZA':
            total_tardanzas += 1
            total_asistencias += 1
        elif estado == 'FALTA':
            total_faltas_nj += 1
            conteo_dias_falta[dia_nom] = conteo_dias_falta.get(dia_nom, 0) + 1
            faltas[fecha_iso] = {'estado': estado, 'causal': causal_label}
            faltas_detalladas.append({
                'fecha_iso': fecha_iso,
                'fecha_fmt': fecha_fmt,
                'dia_semana': dia_nom,
                'estado': estado,
                'causal': causal_label,
                'nota': evento['nota'],
            })
        elif estado in ('FALTA_JUSTIFICADA', 'EXCUSA_MEDICA'):
            total_faltas_j += 1
            conteo_dias_falta[dia_nom] = conteo_dias_falta.get(dia_nom, 0) + 1
            faltas[fecha_iso] = {'estado': estado, 'causal': causal_label}
            faltas_detalladas.append({
                'fecha_iso': fecha_iso,
                'fecha_fmt': fecha_fmt,
                'dia_semana': dia_nom,
                'estado': estado,
                'causal': causal_label,
                'nota': evento['nota'],
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

    total_sesiones = contar_sesiones_registradas(ficha_id, corte_id=corte_id)
    total_faltas = total_faltas_nj + total_faltas_j
    pct_asistencia = ((total_sesiones - total_faltas) / total_sesiones * 100) if total_sesiones > 0 else 100.0

    # El mes visible se arma en el servidor: la primera pintura ya sale con los
    # colores de este aprendiz, sin esperar a JavaScript.
    anio_inicial, mes_inicial = mes_inicial_calendario(asistencia_map)
    calendario = construir_calendario_mes(asistencia_map, anio_inicial, mes_inicial)

    return render_template('instructor/asistencia_modal_aprendiz.html',
                           ficha=ficha, aprendiz=aprendiz,
                           asistencia_map=asistencia_map,
                           calendario=calendario,
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
