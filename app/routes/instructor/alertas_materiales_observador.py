"""Alertas, materiales de apoyo y observador de la ficha."""

from app import db
from app.models.alertas import Alerta, ConfiguracionAlertas
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.material import MaterialFicha
from app.models.observador import (
    CATEGORIAS_NOTA,
    CLAVES_CATEGORIA,
    NotaObservador,
    TIPOS_NOTA,
    TIPO_NEGATIVA,
    TIPO_NEUTRA,
)
from app.services.alertas import actualizar_alertas_ficha, registrar_notificacion
from app.services.archivos import ArchivoService, ErrorArchivo, TiposCarpeta
from app.services.cronograma import obtener_cronograma
from app.services.permisos import puede_gestionar_ficha
from datetime import date, datetime
from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

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


class _DatosNotaInvalidos(Exception):
    """El formulario del observador no cumple las validaciones mínimas."""


def _leer_datos_nota(form, ids_aprendices):
    """Valida el formulario del observador y devuelve los campos normalizados."""
    try:
        aprendiz_id = int(form.get('aprendiz_id', ''))
    except (TypeError, ValueError):
        raise _DatosNotaInvalidos('Selecciona un aprendiz de la ficha.')
    if aprendiz_id not in ids_aprendices:
        raise _DatosNotaInvalidos('El aprendiz no pertenece a esta ficha.')

    descripcion = form.get('descripcion', '').strip()
    if not descripcion:
        raise _DatosNotaInvalidos('Describe el hecho observado.')

    tipo = form.get('tipo', TIPO_NEUTRA).strip()
    if tipo not in TIPOS_NOTA:
        tipo = TIPO_NEUTRA
    categoria = form.get('categoria', 'otra').strip()
    if categoria not in CLAVES_CATEGORIA:
        categoria = 'otra'

    fecha_str = form.get('fecha', '').strip()
    fecha_nota = date.today()
    if fecha_str:
        try:
            fecha_nota = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            raise _DatosNotaInvalidos('La fecha del hecho no tiene un formato válido.')
    if fecha_nota > date.today():
        # Una bitácora registra lo ocurrido; una fecha futura la vuelve
        # inservible como evidencia ante el comité.
        raise _DatosNotaInvalidos('No se puede registrar una observación con fecha futura.')

    return {
        'aprendiz_id': aprendiz_id,
        'tipo': tipo,
        'categoria': categoria,
        'descripcion': descripcion,
        'fecha': fecha_nota,
    }


def puede_gestionar_nota(nota):
    """Solo el autor de la observación o un administrador pueden tocarla."""
    if not nota or not current_user.is_authenticated:
        return False
    return current_user.es_admin or nota.instructor_id == current_user.id


def _ids_aprendices_ficha(ficha_id):
    """Todos los aprendices de la ficha, retirados incluidos.

    La bitácora conserva las notas de quien ya salió: si la validación solo
    aceptara a los activos, corregir la redacción de una nota vieja sería
    imposible justo cuando el caso llega a comité.
    """
    return {
        fila[0]
        for fila in Aprendiz.query.filter_by(ficha_id=ficha_id).with_entities(Aprendiz.id).all()
    }


@instructor_bp.route('/fichas/<int:ficha_id>/observador', methods=['GET', 'POST'])
@login_required
def observador(ficha_id):
    """Bitácora de la formación integral: hechos cortos, fechados y por aprendiz."""
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    aprendices = Aprendiz.query_en_formacion(ficha_id).order_by(
        Aprendiz.apellidos, Aprendiz.nombre
    ).all()

    if request.method == 'POST':
        try:
            datos = _leer_datos_nota(request.form, _ids_aprendices_ficha(ficha_id))
        except _DatosNotaInvalidos as exc:
            flash(str(exc), 'error')
            return redirect(url_for('instructor.observador', ficha_id=ficha_id))

        nota = NotaObservador(ficha_id=ficha_id, instructor_id=current_user.id, **datos)
        db.session.add(nota)
        db.session.commit()
        if nota.tipo == TIPO_NEGATIVA:
            # Un llamado de atención que el aprendiz descubre semanas después no
            # sirve para corregir nada: se le avisa el día que se registra.
            aprendiz_nota = db.session.get(Aprendiz, nota.aprendiz_id)
            registrar_notificacion(
                'aprendiz', nota.aprendiz_id,
                f'Se registró un llamado de atención en tu observador '
                f'({nota.etiqueta_categoria}, {nota.fecha.strftime("%d/%m/%Y")}). '
                'Revísalo en tu panel y habla con tu instructor.',
                'observador', f'observador:{nota.id}', ficha_id,
                f'/aprendiz/{ficha_id}/panel'
                if aprendiz_nota else None,
            )
            db.session.commit()
        flash('Observación registrada.', 'success')
        return redirect(url_for('instructor.observador', ficha_id=ficha_id))

    consulta = NotaObservador.query.filter_by(ficha_id=ficha_id)

    filtro_aprendiz = request.args.get('aprendiz_id', '').strip()
    if filtro_aprendiz.isdigit():
        consulta = consulta.filter(NotaObservador.aprendiz_id == int(filtro_aprendiz))
    filtro_tipo = request.args.get('tipo', '').strip()
    if filtro_tipo in TIPOS_NOTA:
        consulta = consulta.filter(NotaObservador.tipo == filtro_tipo)

    notas = (
        consulta
        .options(joinedload(NotaObservador.aprendiz), joinedload(NotaObservador.autor))
        .order_by(NotaObservador.fecha.desc(), NotaObservador.id.desc())
        .all()
    )

    # Conteo por aprendiz y tipo en una sola consulta agregada: recorrer la
    # lista aprendiz por aprendiz costaba un COUNT por cada uno.
    filas = (
        db.session.query(
            NotaObservador.aprendiz_id,
            NotaObservador.tipo,
            func.count(NotaObservador.id),
        )
        .filter(NotaObservador.ficha_id == ficha_id)
        .group_by(NotaObservador.aprendiz_id, NotaObservador.tipo)
        .all()
    )

    # El resumen y el filtro incluyen a quien ya no está en formación pero dejó
    # notas: al preparar un comité, el historial del retirado es justo el que se
    # necesita, y desaparecía de la tabla al cambiarle el estado.
    ids_activos = {ap.id for ap in aprendices}
    ids_historicos = {aprendiz_id for aprendiz_id, _tipo, _n in filas} - ids_activos
    historicos = []
    if ids_historicos:
        historicos = (
            Aprendiz.query
            .filter(Aprendiz.id.in_(ids_historicos))
            .order_by(Aprendiz.apellidos, Aprendiz.nombre)
            .all()
        )
    aprendices_bitacora = aprendices + historicos

    resumen = {ap.id: {tipo: 0 for tipo in TIPOS_NOTA} for ap in aprendices_bitacora}
    for aprendiz_id, tipo, cantidad in filas:
        if aprendiz_id in resumen and tipo in resumen[aprendiz_id]:
            resumen[aprendiz_id][tipo] = cantidad

    # Un enlace desde otro módulo puede traer el aprendiz y el tipo ya
    # elegidos. El costo de registrar debe ser un clic y un renglón de texto:
    # si dejar constancia cuesta más que olvidarlo, nadie deja constancia.
    tipo_sugerido = request.args.get('nota_tipo', '').strip()
    if tipo_sugerido not in TIPOS_NOTA:
        tipo_sugerido = TIPO_NEUTRA

    return render_template(
        'observador.html',
        ficha=ficha,
        aprendices=aprendices,
        aprendices_bitacora=aprendices_bitacora,
        notas=notas,
        resumen=resumen,
        categorias=CATEGORIAS_NOTA,
        hoy=date.today(),
        filtro_aprendiz=filtro_aprendiz,
        filtro_tipo=filtro_tipo,
        tipo_sugerido=tipo_sugerido,
        puede_gestionar_nota=puede_gestionar_nota,
    )


@instructor_bp.route('/fichas/<int:ficha_id>/observador/<int:nota_id>/editar', methods=['POST'])
@login_required
def editar_nota_observador(ficha_id, nota_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    nota = db.session.get(NotaObservador, nota_id)
    if not nota or nota.ficha_id != ficha_id or not puede_gestionar_nota(nota):
        flash('Solo el instructor que registró la observación puede editarla.', 'error')
        return redirect(url_for('instructor.observador', ficha_id=ficha_id))

    try:
        datos = _leer_datos_nota(request.form, _ids_aprendices_ficha(ficha_id))
    except _DatosNotaInvalidos as exc:
        flash(str(exc), 'error')
        return redirect(url_for('instructor.observador', ficha_id=ficha_id))

    for campo, valor in datos.items():
        setattr(nota, campo, valor)
    nota.actualizada_en = datetime.utcnow()
    db.session.commit()
    flash('Observación actualizada.', 'success')
    return redirect(url_for('instructor.observador', ficha_id=ficha_id))


@instructor_bp.route('/fichas/<int:ficha_id>/observador/<int:nota_id>/eliminar', methods=['POST'])
@login_required
def eliminar_nota_observador(ficha_id, nota_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.fichas'))

    nota = db.session.get(NotaObservador, nota_id)
    if not nota or nota.ficha_id != ficha_id or not puede_gestionar_nota(nota):
        flash('Solo el instructor que registró la observación puede eliminarla.', 'error')
        return redirect(url_for('instructor.observador', ficha_id=ficha_id))

    db.session.delete(nota)
    db.session.commit()
    flash('Observación eliminada.', 'success')
    return redirect(url_for('instructor.observador', ficha_id=ficha_id))
