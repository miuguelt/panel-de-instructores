"""Calendario de programación de instructores para coordinación y líderes de equipo."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models.equipo import EquipoEjecutor
from app.models.ficha import Ficha
from app.models.instructor import Instructor
from app.models.programacion import DIAS_SEMANA, JORNADAS, AsignacionProgramacion
from app.services import programacion_instructores as pi
from app.services.permisos import puede_entrar_a_coordinacion, puede_programar

programacion_bp = Blueprint('programacion', __name__)

VISTAS = ('semana', 'mes')
NOMBRES_MES = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
               'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')


def rango_de_vista(vista: str, fecha: date) -> tuple[date, date, date, date]:
    """(desde, hasta, anterior, siguiente) para la semana (lunes a sábado) o el mes."""
    if vista == 'mes':
        desde = fecha.replace(day=1)
        hasta = fecha.replace(day=monthrange(fecha.year, fecha.month)[1])
        anterior = (desde - timedelta(days=1)).replace(day=1)
        siguiente = hasta + timedelta(days=1)
        return desde, hasta, anterior, siguiente
    lunes = pi.lunes_de(fecha)
    return lunes, lunes + timedelta(days=5), lunes - timedelta(days=7), lunes + timedelta(days=7)


def titulo_de_rango(vista: str, desde: date, hasta: date) -> str:
    if vista == 'mes':
        return f'{NOMBRES_MES[desde.month - 1].capitalize()} de {desde.year}'
    if desde.month == hasta.month:
        return f'Semana del {desde.day} al {hasta.day} de {NOMBRES_MES[hasta.month - 1]} de {hasta.year}'
    return (f'Semana del {desde.day} de {NOMBRES_MES[desde.month - 1]} '
            f'al {hasta.day} de {NOMBRES_MES[hasta.month - 1]} de {hasta.year}')


def _entero(valor) -> int | None:
    try:
        return int(valor) if valor not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _parametros_vista(fuente) -> dict:
    vista = fuente.get('vista') if fuente.get('vista') in VISTAS else 'semana'
    fecha = pi.parsear_fecha(fuente.get('fecha')) or date.today()
    return {'vista': vista, 'fecha': fecha, 'equipo': _entero(fuente.get('equipo'))}


def _volver(params: dict, fecha: date | None = None):
    return redirect(url_for('programacion.calendario', vista=params['vista'],
                            fecha=(fecha or params['fecha']).isoformat(),
                            equipo=params['equipo'] or None))


def equipos_del_usuario() -> list[EquipoEjecutor]:
    if current_user.es_coordinacion:
        return EquipoEjecutor.query.filter_by(activo=True).order_by(EquipoEjecutor.nombre).all()
    return current_user.equipos_liderados


@programacion_bp.route('/', methods=['GET'])
@login_required
def calendario():
    """Vista panorámica: instructores por equipo, días de la semana o del mes, alertas y barras."""
    if not puede_entrar_a_coordinacion():
        return redirect(url_for('programacion.mi_programacion'))
    params = _parametros_vista(request.args)
    desde, hasta, anterior, siguiente = rango_de_vista(params['vista'], params['fecha'])
    instructores, propios = pi.instructores_visibles(current_user, desde, hasta, params['equipo'])
    filas = pi.ocupacion(instructores, desde, hasta)
    return render_template(
        'programacion/calendario.html',
        params=params, desde=desde, hasta=hasta, anterior=anterior, siguiente=siguiente,
        titulo_rango=titulo_de_rango(params['vista'], desde, hasta),
        dias=pi.dias_del_rango(desde, hasta), grupos=pi.agrupar_por_equipo(filas, propios),
        alertas=pi.alertas(filas), resumen=pi.resumen(filas), equipos=equipos_del_usuario(),
        instructores_form=Instructor.query.filter(Instructor.activo.is_(True), Instructor.rol != 'coordinacion')
        .order_by(Instructor.nombre).all(),
        fichas=Ficha.query.order_by(Ficha.codigo).all(),
        dias_semana=DIAS_SEMANA, jornadas=JORNADAS, hoy=date.today(), puede_programar=puede_programar,
    )


@programacion_bp.route('/mia', methods=['GET'])
@login_required
def mi_programacion():
    """Semana del propio instructor, en solo lectura."""
    params = _parametros_vista(request.args)
    params['vista'] = 'semana'
    desde, hasta, anterior, siguiente = rango_de_vista('semana', params['fecha'])
    fila = pi.ocupacion([current_user], desde, hasta)[0]
    proximas = (AsignacionProgramacion.query
                .filter(AsignacionProgramacion.instructor_id == current_user.id,
                        AsignacionProgramacion.fecha_fin >= date.today())
                .order_by(AsignacionProgramacion.fecha_inicio).limit(20).all())
    return render_template(
        'programacion/mi_programacion.html',
        params=params, desde=desde, hasta=hasta, anterior=anterior, siguiente=siguiente,
        titulo_rango=titulo_de_rango('semana', desde, hasta),
        dias=pi.dias_del_rango(desde, hasta), fila=fila, proximas=proximas, hoy=date.today(),
    )


@programacion_bp.route('/equipo', methods=['GET'])
@login_required
def mi_equipo():
    """Programación del equipo ejecutor del instructor, en solo lectura, para todo el equipo."""
    equipo = current_user.equipo if current_user.equipo and current_user.equipo.activo else None
    if equipo is None:
        return render_template('programacion/sin_equipo.html')
    params = _parametros_vista(request.args)
    params['equipo'] = None
    desde, hasta, anterior, siguiente = rango_de_vista(params['vista'], params['fecha'])
    filas = pi.ocupacion(pi.instructores_del_equipo(equipo.id, desde, hasta), desde, hasta)
    return render_template(
        'programacion/calendario.html', solo_lectura=True, ruta='programacion.mi_equipo',
        equipo_vista=equipo,
        params=params, desde=desde, hasta=hasta, anterior=anterior, siguiente=siguiente,
        titulo_rango=titulo_de_rango(params['vista'], desde, hasta),
        dias=pi.dias_del_rango(desde, hasta), grupos=pi.agrupar_por_equipo(filas, {equipo.id}),
        alertas=pi.alertas(filas), resumen=pi.resumen(filas), equipos=[equipo],
        dias_semana=DIAS_SEMANA, hoy=date.today(), puede_programar=None,
    )


@programacion_bp.route('/fichas/<int:ficha_id>/competencias', methods=['GET'])
@login_required
def competencias_ficha(ficha_id):
    if not puede_entrar_a_coordinacion():
        abort(403)
    if not db.session.get(Ficha, ficha_id):
        abort(404)
    return jsonify(pi.competencias_de_ficha(ficha_id))


def _autorizar(datos) -> None:
    instructor = db.session.get(Instructor, _entero(datos.get('instructor_id')) or 0)
    ficha = db.session.get(Ficha, _entero(datos.get('ficha_id')) or 0)
    if instructor and ficha and not puede_programar(instructor, ficha):
        raise pi.ErrorProgramacion(
            'Solo puedes programar a instructores de tu equipo, o a instructores de otros '
            'equipos en competencias transversales de las fichas de tu equipo. Pide a '
            'coordinación esta asignación.')


def _datos_formulario() -> dict:
    datos = request.form.to_dict()
    datos['dias_semana'] = request.form.getlist('dias_semana')
    return datos


@programacion_bp.route('/asignaciones', methods=['POST'])
@login_required
def crear_asignacion():
    if not puede_entrar_a_coordinacion():
        abort(403)
    params = _parametros_vista(request.form)
    datos = _datos_formulario()
    try:
        _autorizar(datos)
        asignacion = pi.guardar_asignacion(datos, creado_por_id=current_user.id)
    except pi.ErrorProgramacion as error:
        flash(str(error), 'error')
        return _volver(params)
    flash(f'Programaste a {asignacion.instructor.nombre} en la ficha {asignacion.ficha.codigo}.', 'success')
    return _volver(params, asignacion.fecha_inicio if params['vista'] == 'semana' else None)


def _asignacion_autorizada(asignacion_id: int) -> AsignacionProgramacion:
    asignacion = db.session.get(AsignacionProgramacion, asignacion_id)
    if not asignacion:
        abort(404)
    if not puede_programar(asignacion.instructor, asignacion.ficha):
        abort(403)
    return asignacion


@programacion_bp.route('/asignaciones/<int:asignacion_id>', methods=['POST'])
@login_required
def editar_asignacion(asignacion_id):
    asignacion = _asignacion_autorizada(asignacion_id)
    params = _parametros_vista(request.form)
    datos = _datos_formulario()
    try:
        _autorizar(datos)
        pi.guardar_asignacion(datos, creado_por_id=current_user.id, asignacion=asignacion)
    except pi.ErrorProgramacion as error:
        db.session.rollback()
        flash(str(error), 'error')
        return _volver(params)
    flash('Guardaste los cambios de la asignación.', 'success')
    return _volver(params)


@programacion_bp.route('/asignaciones/<int:asignacion_id>/eliminar', methods=['POST'])
@login_required
def eliminar_asignacion(asignacion_id):
    asignacion = _asignacion_autorizada(asignacion_id)
    params = _parametros_vista(request.form)
    nombre = asignacion.instructor.nombre
    pi.eliminar_asignacion(asignacion)
    flash(f'Quitaste la asignación de {nombre}.', 'success')
    return _volver(params)
