"""Normativa descargable y remisiones a comité de fichas terminadas por fecha."""

import csv
import io
from datetime import date

from flask import Blueprint, abort, flash, make_response, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app import db
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.services.comite_productiva import analizar_fichas_terminadas
from app.services.debido_proceso import ReglaDebidoProceso, anular_llamado, registrar_llamado
from app.services.permisos import puede_gestionar_ficha
from app.services.normativa_sena import CATALOGO_NORMAS, FUNDAMENTOS, obtener_fundamento, ruta_archivo

comite_bp = Blueprint('comite', __name__, template_folder='../templates/instructor')

COLUMNAS_CSV = (
    'Ficha', 'Fecha fin ficha', 'Documento', 'Aprendiz', 'Estado', 'Días desde el cierre',
    'Acción recomendada', 'Motivo', 'Fundamento principal', 'Página PDF',
)

ACCIONES = {
    'remitir_comite': 'Remitir a comité de evaluación y seguimiento',
    'cancelacion_administrativa': 'Recomendación: cancelación por vía administrativa',
}


def _fichas_del_usuario():
    from app.routes.instructor import obtener_fichas
    return obtener_fichas()


def filas_csv(analisis):
    """Filas planas para el acta: una por aprendiz recomendado."""
    filas = []
    for item in analisis:
        for r in item['recomendaciones']:
            principal = r['fundamentos'][0]
            filas.append((
                r['ficha_codigo'], r['fecha_fin_ficha'].strftime('%d/%m/%Y'), r['documento'],
                r['nombre'], r['estado_etiqueta'], r['dias_vencida'], ACCIONES[r['accion']],
                r['motivo'], principal['referencia'], principal['pagina'],
            ))
    return filas


@comite_bp.route('/normativa')
@login_required
def normativa():
    fundamentos, vistas = [], set()
    for clave in FUNDAMENTOS:
        fundamento = obtener_fundamento(clave)
        # Varias reglas comparten artículo y página; la tabla los muestra una vez.
        if fundamento['referencia'] not in vistas:
            vistas.add(fundamento['referencia'])
            fundamentos.append(fundamento)
    return render_template(
        'normativa.html', normas=list(CATALOGO_NORMAS.values()), fundamentos=fundamentos,
    )


@comite_bp.route('/normativa/<norma_id>')
@login_required
def descargar_norma(norma_id):
    ruta = ruta_archivo(norma_id)
    if ruta is None or not ruta.is_file():
        abort(404)
    descargar = request.args.get('descargar') == '1'
    return send_file(
        ruta, mimetype='application/pdf', as_attachment=descargar,
        download_name=CATALOGO_NORMAS[norma_id]['archivo'],
    )


@comite_bp.route('/comite/fichas-terminadas')
@login_required
def fichas_terminadas():
    from app.services.alertas import fecha_colombia
    from datetime import datetime
    hoy = fecha_colombia(datetime.utcnow())
    analisis = analizar_fichas_terminadas(_fichas_del_usuario(), hoy)
    if request.args.get('formato') == 'csv':
        salida = io.StringIO()
        escritor = csv.writer(salida, delimiter=';')
        escritor.writerow(COLUMNAS_CSV)
        escritor.writerows(filas_csv(analisis))
        respuesta = make_response('﻿' + salida.getvalue())
        respuesta.headers['Content-Type'] = 'text/csv; charset=utf-8'
        respuesta.headers['Content-Disposition'] = (
            f'attachment; filename=remisiones_comite_{hoy:%Y%m%d}.csv'
        )
        return respuesta
    total = sum(len(item['recomendaciones']) for item in analisis)
    return render_template(
        'comite_fichas_terminadas.html', analisis=analisis, total=total, hoy=hoy,
        acciones=ACCIONES, es_admin=getattr(current_user, 'es_admin', False),
    )


@comite_bp.route('/fichas/<int:ficha_id>/aprendices/<int:aprendiz_id>/llamados', methods=['POST'])
@login_required
def registrar_llamado_atencion(ficha_id, aprendiz_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        abort(404)
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not aprendiz or aprendiz.ficha_id != ficha_id:
        abort(404)
    try:
        registrar_llamado(
            aprendiz, ficha, request.form.get('tipo', ''), request.form.get('descripcion'),
            instructor_id=current_user.id, orientaciones=request.form.get('orientaciones'),
            fase=request.form.get('fase') or None,
        )
    except ReglaDebidoProceso as error:
        db.session.rollback()
        flash(str(error), 'error')
    else:
        flash('Llamado de atención registrado. El aprendiz recibirá una notificación.', 'success')
    return redirect(url_for('seguimiento.casos_seguimiento', ficha_id=ficha_id))


@comite_bp.route('/fichas/<int:ficha_id>/llamados/<int:llamado_id>/anular', methods=['POST'])
@login_required
def anular_llamado_atencion(ficha_id, llamado_id):
    """Anula con motivo un llamado mal registrado; el registro se conserva."""
    from app.models.alertas import LlamadoAtencion
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        abort(404)
    llamado = db.session.get(LlamadoAtencion, llamado_id)
    if not llamado or llamado.ficha_id != ficha_id:
        abort(404)
    try:
        anular_llamado(llamado, request.form.get('motivo'), instructor_id=current_user.id)
    except ReglaDebidoProceso as error:
        db.session.rollback()
        flash(str(error), 'error')
    else:
        flash('Llamado anulado. Queda en el expediente con su motivo y ya no cuenta en los topes.', 'success')
    return redirect(url_for('seguimiento.casos_seguimiento', ficha_id=ficha_id))


def _ficha_gestionable(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        abort(404)
    return ficha


def _aprendiz_de(ficha, aprendiz_id):
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not aprendiz or aprendiz.ficha_id != ficha.id:
        abort(404)
    return aprendiz


def _fecha(nombre):
    """Fecha ISO del formulario; None si viene vacía o mal formada."""
    valor = (request.form.get(nombre) or '').strip()
    try:
        return date.fromisoformat(valor) if valor else None
    except ValueError:
        return None


def _volver_novedades(ficha_id, aprendiz_id=None):
    destino = url_for('comite.novedades_productiva', ficha_id=ficha_id)
    return redirect(f'{destino}#aprendiz-{aprendiz_id}' if aprendiz_id else destino)


@comite_bp.route('/fichas/<int:ficha_id>/novedades-productiva')
@login_required
def novedades_productiva(ficha_id):
    from app.models.novedades import (
        ALTERNATIVAS_PRODUCTIVA, CAUSAS_APLAZAMIENTO, ESTADOS_NOVEDAD, ESTADOS_PRODUCTIVA,
        MOMENTOS_SEGUIMIENTO, TIPOS_NOVEDAD,
    )
    from app.services.novedades import cargar_datos_ficha, resumen_aprendiz

    ficha = _ficha_gestionable(ficha_id)
    hoy = date.today()
    etapas, novedades = cargar_datos_ficha(ficha.id)
    aprendices = Aprendiz.query.filter_by(ficha_id=ficha.id).order_by(
        Aprendiz.apellidos, Aprendiz.nombre).all()
    filas = [resumen_aprendiz(a, etapas.get(a.id), novedades.get(a.id, []), hoy) for a in aprendices]
    return render_template(
        'novedades_productiva.html', ficha=ficha, filas=filas, hoy=hoy,
        tipos=TIPOS_NOVEDAD, estados_novedad=ESTADOS_NOVEDAD, causas=CAUSAS_APLAZAMIENTO,
        alternativas=ALTERNATIVAS_PRODUCTIVA, estados_productiva=ESTADOS_PRODUCTIVA,
        momentos=MOMENTOS_SEGUIMIENTO,
        fundamentos_novedades=[obtener_fundamento(c) for c in (
            'traslado', 'aplazamiento', 'reintegro_solicitud', 'retiro_voluntario',
            'aplazamiento_vencido', 'productiva_vencida')],
    )


@comite_bp.route('/fichas/<int:ficha_id>/aprendices/<int:aprendiz_id>/novedades', methods=['POST'])
@login_required
def registrar_novedad_aprendiz(ficha_id, aprendiz_id):
    from app.services.novedades import ErrorNovedad, registrar_novedad

    ficha = _ficha_gestionable(ficha_id)
    aprendiz = _aprendiz_de(ficha, aprendiz_id)
    try:
        registrar_novedad(
            aprendiz, ficha, request.form.get('tipo', ''), _fecha('fecha_solicitud'),
            estado=request.form.get('estado', 'solicitada'),
            fecha_inicio=_fecha('fecha_inicio'), fecha_fin=_fecha('fecha_fin'),
            causa=request.form.get('causa') or None,
            ampliacion=request.form.get('ampliacion') == '1',
            observacion=request.form.get('observacion'), instructor_id=current_user.id,
            acta_comite=request.form.get('acta_comite'),
        )
    except ErrorNovedad as error:
        db.session.rollback()
        flash(str(error), 'error')
    else:
        flash('Novedad registrada.', 'success')
    return _volver_novedades(ficha.id, aprendiz.id)


@comite_bp.route('/fichas/<int:ficha_id>/novedades/<int:novedad_id>/estado', methods=['POST'])
@login_required
def cambiar_estado_novedad_aprendiz(ficha_id, novedad_id):
    from app.models.novedades import NovedadAprendiz
    from app.services.novedades import ErrorNovedad, cambiar_estado_novedad

    ficha = _ficha_gestionable(ficha_id)
    novedad = db.session.get(NovedadAprendiz, novedad_id)
    if not novedad or novedad.ficha_id != ficha.id:
        abort(404)
    try:
        cambiar_estado_novedad(
            novedad, request.form.get('estado', ''), instructor_id=current_user.id,
            acta_comite=request.form.get('acta_comite'),
        )
    except ErrorNovedad as error:
        flash(str(error), 'error')
    else:
        flash(f'La novedad quedó «{novedad.etiqueta_estado.lower()}».', 'success')
    return _volver_novedades(ficha.id, novedad.aprendiz_id)


@comite_bp.route('/fichas/<int:ficha_id>/aprendices/<int:aprendiz_id>/etapa-productiva', methods=['POST'])
@login_required
def guardar_etapa_productiva(ficha_id, aprendiz_id):
    from app.services.novedades import ErrorNovedad, registrar_etapa_productiva

    ficha = _ficha_gestionable(ficha_id)
    aprendiz = _aprendiz_de(ficha, aprendiz_id)
    try:
        registrar_etapa_productiva(
            aprendiz, ficha, request.form.get('alternativa', ''),
            estado=request.form.get('estado', 'por_iniciar'),
            empresa=request.form.get('empresa'), fecha_inicio=_fecha('fecha_inicio'),
            fecha_fin_estimada=_fecha('fecha_fin_estimada'),
            planeacion_avalada=request.form.get('planeacion_avalada') == '1',
            fecha_aval=_fecha('fecha_aval'),
            instructor_seguimiento=request.form.get('instructor_seguimiento'),
        )
    except ErrorNovedad as error:
        db.session.rollback()
        flash(str(error), 'error')
    else:
        flash('Etapa productiva guardada.', 'success')
    return _volver_novedades(ficha.id, aprendiz.id)


@comite_bp.route('/fichas/<int:ficha_id>/aprendices/<int:aprendiz_id>/etapa-productiva/seguimiento',
                 methods=['POST'])
@login_required
def registrar_seguimiento_productiva(ficha_id, aprendiz_id):
    from app.models.novedades import EtapaProductiva
    from app.services.novedades import ErrorNovedad, registrar_seguimiento

    ficha = _ficha_gestionable(ficha_id)
    aprendiz = _aprendiz_de(ficha, aprendiz_id)
    etapa = EtapaProductiva.query.filter_by(aprendiz_id=aprendiz.id, ficha_id=ficha.id).first()
    if etapa is None:
        flash('Registra primero la alternativa de etapa productiva del aprendiz.', 'error')
        return _volver_novedades(ficha.id, aprendiz.id)
    try:
        registrar_seguimiento(etapa, request.form.get('momento', ''), _fecha('fecha'),
                              request.form.get('observacion'), current_user.id)
    except ErrorNovedad as error:
        db.session.rollback()
        flash(str(error), 'error')
    else:
        flash('Seguimiento registrado.', 'success')
    return _volver_novedades(ficha.id, aprendiz.id)


@comite_bp.route('/comite/reporte-coordinacion.xlsx')
@login_required
def reporte_coordinacion():
    from app.services.reporte_coordinacion import construir_reporte

    hoy = date.today()
    contenido = construir_reporte(_fichas_del_usuario(), hoy)
    return send_file(
        io.BytesIO(contenido), as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        download_name=f'reporte_coordinacion_{hoy:%Y%m%d}.xlsx',
    )
