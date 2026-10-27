"""Rutas del módulo administrativo de SENA Control."""

import secrets
import string

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from app import db
from app.models.instructor import Instructor
from app.services.permisos import admin_required

admin_bp = Blueprint('admin', __name__)


def generar_clave_temporal(longitud=8):
    """Genera una contraseña temporal segura y legible de caracteres alfanuméricos."""
    caracteres = string.ascii_letters + string.digits
    return ''.join(secrets.choice(caracteres) for _ in range(longitud))


@admin_bp.route('/instructores', methods=['GET'], endpoint='instructores')
@admin_bp.route('/instructores', methods=['GET'], endpoint='listar_instructores')
@admin_required
def listar_instructores():
    """Listado institucional de instructores y su estado de acceso."""
    q = (request.args.get('q') or '').strip()
    consulta = Instructor.query
    if q:
        termino = f'%{q}%'
        consulta = consulta.filter(
            (Instructor.nombre.ilike(termino)) | (Instructor.correo.ilike(termino))
        )
    instructores = consulta.order_by(Instructor.nombre.asc()).all()
    return render_template(
        'admin/instructores.html',
        instructores=instructores,
        q=q,
    )


@admin_bp.route('/instructores/<int:instructor_id>/restablecer-clave', methods=['POST'])
@admin_required
def restablecer_clave_instructor(instructor_id):
    """Restablece la contraseña de un instructor asignando clave temporal y forzando cambio."""
    instructor = db.session.get(Instructor, instructor_id)
    if not instructor:
        abort(404)

    if not instructor.activo:
        flash('No se puede restablecer la contraseña de una cuenta inactiva.', 'error')
        return redirect(url_for('admin.listar_instructores'))

    clave_manual = (request.form.get('clave_temporal') or '').strip()
    if clave_manual:
        if len(clave_manual) < 6:
            flash('La contraseña temporal debe tener al menos 6 caracteres.', 'error')
            return redirect(url_for('admin.listar_instructores'))
        if len(clave_manual) > 128:
            flash('La contraseña temporal no puede superar 128 caracteres.', 'error')
            return redirect(url_for('admin.listar_instructores'))
        clave_temporal = clave_manual
    else:
        clave_temporal = generar_clave_temporal(8)

    instructor.set_password(clave_temporal)
    instructor.debe_cambiar_password = True
    instructor.auth_version = (instructor.auth_version or 1) + 1
    instructor.password_reset_token_hash = None
    instructor.password_reset_expires_at = None
    db.session.commit()

    flash(
        f'Se asignó la contraseña temporal al instructor {instructor.nombre}: {clave_temporal}. '
        'El instructor deberá cambiarla obligatoriamente en su próximo inicio de sesión.',
        'success',
    )
    return redirect(url_for('admin.listar_instructores'))
