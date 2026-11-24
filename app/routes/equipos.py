"""Gestión de equipos ejecutores: nombre, líder y miembros (solo coordinación)."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import func

from app import db
from app.models.equipo import EquipoEjecutor
from app.models.ficha import Ficha
from app.models.instructor import Instructor
from app.services.programacion_instructores import asignaciones_fuera_de_equipo
from app.services.permisos import coordinacion_required

equipos_bp = Blueprint('equipos', __name__)


def _texto(campo: str, limite: int) -> str:
    return ' '.join((request.form.get(campo) or '').split())[:limite]


def _instructor_activo(valor) -> Instructor | None:
    try:
        instructor = db.session.get(Instructor, int(valor))
    except (TypeError, ValueError):
        return None
    return instructor if instructor and instructor.activo else None


def _nombre_repetido(nombre: str, excluir_id: int | None = None) -> bool:
    consulta = EquipoEjecutor.query.filter(func.lower(EquipoEjecutor.nombre) == nombre.lower())
    if excluir_id:
        consulta = consulta.filter(EquipoEjecutor.id != excluir_id)
    return consulta.first() is not None


def _aplicar_lider(equipo: EquipoEjecutor) -> None:
    """El líder elegido queda también como miembro del equipo."""
    valor = request.form.get('lider_id')
    if not valor:
        equipo.lider_id = None
        return
    lider = _instructor_activo(valor)
    if lider is None:
        raise ValueError('El líder elegido no existe o está inactivo.')
    equipo.lider_id = lider.id
    lider.equipo_id = equipo.id


@equipos_bp.route('/', methods=['GET'])
@coordinacion_required
def listar():
    equipos = EquipoEjecutor.query.order_by(EquipoEjecutor.activo.desc(), EquipoEjecutor.nombre).all()
    instructores = Instructor.query.filter_by(activo=True).order_by(Instructor.nombre).all()
    fichas = Ficha.query.order_by(Ficha.codigo).all()
    fichas_por_equipo: dict[int | None, list[Ficha]] = {}
    for ficha in fichas:
        fichas_por_equipo.setdefault(ficha.equipo_id, []).append(ficha)
    return render_template('programacion/equipos.html', equipos=equipos, instructores=instructores,
                           sin_equipo=[i for i in instructores if not i.equipo_id],
                           fichas=fichas, fichas_por_equipo=fichas_por_equipo,
                           fichas_sin_equipo=fichas_por_equipo.get(None, []))


@equipos_bp.route('/', methods=['POST'])
@coordinacion_required
def crear():
    nombre = _texto('nombre', 120)
    if not nombre:
        flash('Escribe el nombre del equipo.', 'error')
        return redirect(url_for('equipos.listar'))
    if _nombre_repetido(nombre):
        flash(f'Ya existe un equipo llamado «{nombre}».', 'error')
        return redirect(url_for('equipos.listar'))
    equipo = EquipoEjecutor(nombre=nombre, descripcion=_texto('descripcion', 300) or None)
    db.session.add(equipo)
    db.session.flush()
    try:
        _aplicar_lider(equipo)
    except ValueError as error:
        db.session.rollback()
        flash(str(error), 'error')
        return redirect(url_for('equipos.listar'))
    db.session.commit()
    flash(f'Creaste el equipo {equipo.nombre}.', 'success')
    return redirect(url_for('equipos.listar'))


def _equipo_activo_elegido(valor: str | None) -> tuple[bool, EquipoEjecutor | None]:
    """(válido, equipo): un valor vacío deja sin equipo; si no, debe ser un equipo activo."""
    if not valor:
        return True, None
    equipo = db.session.get(EquipoEjecutor, int(valor)) if valor.isdigit() else None
    return bool(equipo and equipo.activo), equipo


def _equipo(equipo_id: int) -> EquipoEjecutor:
    equipo = db.session.get(EquipoEjecutor, equipo_id)
    if not equipo:
        abort(404)
    return equipo


@equipos_bp.route('/<int:equipo_id>', methods=['POST'])
@coordinacion_required
def editar(equipo_id):
    equipo = _equipo(equipo_id)
    nombre = _texto('nombre', 120)
    if not nombre:
        flash('El nombre del equipo no puede quedar vacío.', 'error')
        return redirect(url_for('equipos.listar'))
    if _nombre_repetido(nombre, equipo.id):
        flash(f'Ya existe un equipo llamado «{nombre}».', 'error')
        return redirect(url_for('equipos.listar'))
    equipo.nombre = nombre
    equipo.descripcion = _texto('descripcion', 300) or None
    try:
        _aplicar_lider(equipo)
    except ValueError as error:
        db.session.rollback()
        flash(str(error), 'error')
        return redirect(url_for('equipos.listar'))
    db.session.commit()
    flash(f'Guardaste los cambios del equipo {equipo.nombre}.', 'success')
    return redirect(url_for('equipos.listar'))


@equipos_bp.route('/<int:equipo_id>/estado', methods=['POST'])
@coordinacion_required
def alternar_estado(equipo_id):
    equipo = _equipo(equipo_id)
    equipo.activo = not equipo.activo
    db.session.commit()
    flash(f'El equipo {equipo.nombre} quedó {"activo" if equipo.activo else "archivado"}.', 'success')
    return redirect(url_for('equipos.listar'))


@equipos_bp.route('/miembros', methods=['POST'])
@coordinacion_required
def asignar_miembro():
    """Cambia el equipo de un instructor (o lo deja sin equipo)."""
    instructor = _instructor_activo(request.form.get('instructor_id'))
    if instructor is None:
        flash('Elige un instructor activo.', 'error')
        return redirect(url_for('equipos.listar'))
    valido, equipo = _equipo_activo_elegido(request.form.get('equipo_id'))
    if not valido:
        flash('Elige un equipo activo.', 'error')
        return redirect(url_for('equipos.listar'))
    instructor.equipo_id = equipo.id if equipo else None
    destino = f'al equipo {equipo.nombre}' if equipo else 'sin equipo'
    # Quien lidera un equipo y sale de él deja de liderarlo.
    for liderado in EquipoEjecutor.query.filter_by(lider_id=instructor.id).all():
        if liderado.id != instructor.equipo_id:
            liderado.lider_id = None
    db.session.commit()
    flash(f'{instructor.nombre} quedó {destino}.', 'success')
    _avisar_asignaciones_fuera_de_equipo(instructor)
    return redirect(url_for('equipos.listar'))


def _avisar_asignaciones_fuera_de_equipo(instructor: Instructor) -> None:
    """Las asignaciones técnicas que quedan en fichas de otro equipo no se borran: se avisan."""
    pendientes = asignaciones_fuera_de_equipo(instructor)
    if not pendientes:
        return
    fichas = ', '.join(sorted({a.ficha.codigo for a in pendientes}))
    flash(f'{instructor.nombre} tiene {len(pendientes)} asignación(es) vigente(s) de competencias '
          f'técnicas en fichas de otro equipo ({fichas}). Revísalas en el calendario: entre equipos '
          'solo se programan transversales.', 'warning')


@equipos_bp.route('/fichas', methods=['POST'])
@coordinacion_required
def asignar_ficha():
    """Define el equipo ejecutor que orienta una ficha (o la deja sin equipo)."""
    valor = request.form.get('ficha_id') or ''
    ficha = db.session.get(Ficha, int(valor)) if valor.isdigit() else None
    if ficha is None:
        flash('Elige una ficha.', 'error')
        return redirect(url_for('equipos.listar'))
    valido, equipo = _equipo_activo_elegido(request.form.get('equipo_id'))
    if not valido:
        flash('Elige un equipo activo.', 'error')
        return redirect(url_for('equipos.listar'))
    ficha.equipo_id = equipo.id if equipo else None
    db.session.commit()
    destino = f'en el equipo {equipo.nombre}' if equipo else 'sin equipo'
    flash(f'La ficha {ficha.codigo} quedó {destino}.', 'success')
    return redirect(url_for('equipos.listar'))
