"""Alertas de la ficha y materiales de apoyo."""

from app import db
from app.models.alertas import Alerta, ConfiguracionAlertas
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.material import MaterialFicha
from app.services.alertas import actualizar_alertas_ficha
from app.services.archivos import ArchivoService, ErrorArchivo, TiposCarpeta
from app.services.cronograma import obtener_cronograma
from app.services.permisos import puede_gestionar_ficha
from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from . import (  # noqa: E402
    calcular_semaforo,
    instructor_bp,
)


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
    if max(umbral_amarillo, umbral_rojo, max_fallas) > 2_147_483_647:
        flash('Los umbrales superan el máximo permitido. Ingrese valores menores.', 'error')
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
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            ArchivoService.eliminar(resultado.url)
            current_app.logger.exception('No se pudo registrar el material de la ficha.')
            flash('No fue posible registrar el material. Vuelva a seleccionar el archivo e inténtelo de nuevo.', 'error')
            return redirect(url_for('instructor.materiales', ficha_id=ficha_id))
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

    archivo_anterior = material.url_archivo
    try:
        db.session.delete(material)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('No fue posible eliminar el material %s.', material_id)
        flash('No fue posible eliminar el material. El archivo se conserva; vuelva a intentarlo.', 'error')
        return redirect(url_for('instructor.materiales', ficha_id=ficha_id))
    ArchivoService.eliminar(archivo_anterior)
    flash('Material eliminado.', 'success')
    return redirect(url_for('instructor.materiales', ficha_id=ficha_id))
