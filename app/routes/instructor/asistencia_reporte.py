"""Reportes de asistencia en Excel y PDF."""
import io
from datetime import datetime

import openpyxl
from flask import flash, redirect, request, send_file, url_for
from flask_login import login_required

from app import db
from app.models.aprendiz import Aprendiz
from app.models.asistencia import (
    RegistroAsistencia,
    SesionAsistencia,
)
from app.models.ficha import Ficha
from app.services.cortes import corte_actual
from app.services.permisos import puede_gestionar_ficha

from . import instructor_bp


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
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

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
