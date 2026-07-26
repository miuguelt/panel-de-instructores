from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlsplit
from sqlalchemy.exc import OperationalError

from app import db
from app.models.instructor import Instructor

auth_bp = Blueprint('auth', __name__, template_folder='../templates/auth')


def _destino_interno(destino):
    """Acepta únicamente rutas locales para evitar redirecciones fuera de la app."""
    if not destino:
        return None
    partes = urlsplit(destino)
    if partes.scheme or partes.netloc or not partes.path.startswith('/') or partes.path.startswith('//'):
        return None
    return destino


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('instructor.dashboard'))

    if request.method == 'POST':
        correo = request.form.get('correo', '').strip().lower()
        password = request.form.get('password', '')

        try:
            instructor = Instructor.query.filter_by(correo=correo).first()
        except OperationalError:
            flash('Error de conexión con la base de datos. Verifica que PostgreSQL esté corriendo en puerto 5434.', 'error')
            return render_template('login.html')
        if instructor and instructor.check_password(password):
            if not instructor.activo:
                flash('Tu cuenta está desactivada. Contacta al administrador.', 'error')
                return render_template('login.html')
            login_user(instructor, remember=True)
            next_page = _destino_interno(request.args.get('next'))
            return redirect(next_page or url_for('instructor.dashboard'))
        flash('Correo o contraseña incorrectos.', 'error')

    return render_template('login.html')


@auth_bp.route('/registro', methods=['GET', 'POST'])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for('instructor.dashboard'))

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        correo = request.form.get('correo', '').strip().lower()
        password = request.form.get('password', '')

        if not nombre or not correo or not password:
            flash('Todos los campos son obligatorios.', 'error')
            return render_template('registro.html')

        if not correo.endswith('@sena.edu.co'):
            flash('Debes usar tu correo institucional SENA (@sena.edu.co).', 'error')
            return render_template('registro.html')

        if Instructor.query.filter_by(correo=correo).first():
            flash('Ya existe una cuenta con ese correo.', 'error')
            return render_template('registro.html')

        if len(password) < 6:
            flash('La contraseña debe tener mínimo 6 caracteres.', 'error')
            return render_template('registro.html')

        instructor = Instructor(nombre=nombre, correo=correo, rol='colaborador')
        instructor.set_password(password)
        db.session.add(instructor)
        db.session.commit()

        flash('Registro exitoso. Ya puedes iniciar sesión.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('registro.html')


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada correctamente.', 'success')
    return redirect(url_for('auth.login'))
