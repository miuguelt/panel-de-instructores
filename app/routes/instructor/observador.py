"""Observador de la ficha: notas de seguimiento por aprendiz."""

from app import db
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.observador import (
    CATEGORIAS_NOTA,
    CLAVES_CATEGORIA,
    NotaObservador,
    TIPOS_NOTA,
    TIPO_NEGATIVA,
    TIPO_NEUTRA,
)
from app.services.alertas import registrar_notificacion
from app.services.permisos import puede_gestionar_ficha
from datetime import date, datetime
from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from . import (  # noqa: E402
    instructor_bp,
)


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
