from datetime import date, datetime
import io

from flask import current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import login_required
import openpyxl
from sqlalchemy.exc import IntegrityError, OperationalError

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
)
from app.services.cortes import corte_actual, cortes_visibles
from app.services.permisos import puede_gestionar_asistencia, puede_gestionar_ficha
import app.routes.instructor as _pkg

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


@instructor_bp.route('/fichas/<int:ficha_id>/reporte-asistencia')
@login_required
def reporte_asistencia(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    corte_id = request.args.get('corte_id', type=int)
    corte = corte_actual(ficha_id, corte_id=corte_id)
    if corte_id and not corte:
        flash('El corte no existe o no está compartido contigo.', 'error')
        return redirect(url_for('instructor.asistencia', ficha_id=ficha_id))
    corte_id = corte.id if corte else None

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
    if corte_id is not None:
        query_sesiones = query_sesiones.filter(SesionAsistencia.corte_id == corte_id)

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
    registros_map = {}
    if sesiones_ids:
        registros_bulk = RegistroAsistencia.query.filter(
            RegistroAsistencia.sesion_id.in_(sesiones_ids)
        ).all()
        registros_map = {
            (r.sesion_id, r.aprendiz_id): r.estado
            for r in registros_bulk
        }

    for ap in aprendices:
        fila = [ap.documento, ap.nombre, ap.apellidos]
        total_faltas = 0
        justificadas = 0

        for s in sesiones:
            estado_reg = registros_map.get((s.id, ap.id))
            estado = estado_reg if estado_reg else '-'
            fila.append(estado)
            if estado_reg in ('FALTA', 'FALTA_JUSTIFICADA', 'EXCUSA_MEDICA'):
                total_faltas += 1
                if estado_reg in ('FALTA_JUSTIFICADA', 'EXCUSA_MEDICA'):
                    justificadas += 1

        no_justificadas = total_faltas - justificadas
        pct = ((len(sesiones) - total_faltas) / len(sesiones) * 100) if sesiones else 100
        fila.extend([total_faltas, justificadas, no_justificadas, f'{pct:.1f}%'])
        ws.append(fila)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True,
                     download_name=f'reporte_asistencia_{ficha.codigo}.xlsx')


def _generar_pdf_asistencia(ficha, aprendices, sesiones):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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

    faltas_por_aprendiz = {}
    justificadas_por_aprendiz = {}
    if sesiones_ids:
        registros_faltas = RegistroAsistencia.query.filter(
            RegistroAsistencia.sesion_id.in_(sesiones_ids),
            RegistroAsistencia.estado.in_(['FALTA', 'FALTA_JUSTIFICADA', 'EXCUSA_MEDICA']),
        ).all()
        for reg in registros_faltas:
            faltas_por_aprendiz[reg.aprendiz_id] = faltas_por_aprendiz.get(reg.aprendiz_id, 0) + 1
            if reg.estado in ('FALTA_JUSTIFICADA', 'EXCUSA_MEDICA'):
                justificadas_por_aprendiz[reg.aprendiz_id] = justificadas_por_aprendiz.get(reg.aprendiz_id, 0) + 1

    for ap in aprendices:
        if not sesiones_ids:
            total = just = no_just = 0
            pct = 100
        else:
            total = faltas_por_aprendiz.get(ap.id, 0)
            just = justificadas_por_aprendiz.get(ap.id, 0)
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

    return send_file(buffer, mimetype='application/pdf', as_attachment=True,
                     download_name=f'reporte_asistencia_{ficha.codigo}.pdf')
