"""Gestión de equipos ejecutores: nombre, líder y miembros (solo coordinación)."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import func

from app import db
from app.models.equipo import EquipoEjecutor
from app.models.instructor import Instructor
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
    return render_template('programacion/equipos.html', equipos=equipos, instructores=instructores,
                           sin_equipo=[i for i in instructores if not i.equipo_id])


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
    valor = request.form.get('equipo_id')
    if valor:
        equipo = db.session.get(EquipoEjecutor, int(valor)) if valor.isdigit() else None
        if not equipo or not equipo.activo:
            flash('Elige un equipo activo.', 'error')
            return redirect(url_for('equipos.listar'))
        instructor.equipo_id = equipo.id
        destino = f'al equipo {equipo.nombre}'
    else:
        instructor.equipo_id = None
        destino = 'sin equipo'
    # Quien lidera un equipo y sale de él deja de liderarlo.
    for liderado in EquipoEjecutor.query.filter_by(lider_id=instructor.id).all():
        if liderado.id != instructor.equipo_id:
            liderado.lider_id = None
    db.session.commit()
    flash(f'{instructor.nombre} quedó {destino}.', 'success')
    return redirect(url_for('equipos.listar'))
