"""Gestión de fichas, importación del reporte y visión general."""
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
from sqlalchemy import or_

import app.routes.instructor as _pkg
from app import db
from app.models.alertas import ConfiguracionAlertas
from app.models.archivo_ficha import (
    TIPO_REPORTE_JUICIOS,
)
from app.models.aseo import ConfiguracionAseo
from app.models.ficha import Ficha
from app.models.ficha_instructor import FichaInstructor
from app.models.ranking import ConfiguracionRanking
from app.services.archivos import ArchivoDuplicado, ArchivoService
from app.services.cortes import corte_actual, corte_visible, cortes_visibles
from app.services.cronograma import obtener_cronograma
from app.services.importacion_ficha import (
    ErrorImportacion,
)
from app.services.permisos import puede_gestionar_ficha
from app.services.resumen_ficha import obtener_resumen_ficha_360
from app.services.versiones_archivos import (
    actualizar_estado,
)

from . import _actualizar_indicadores_carga, instructor_bp, obtener_fichas


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
