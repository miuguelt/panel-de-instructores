import hashlib
import hmac
import secrets
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func
from sqlalchemy.exc import OperationalError

from app import db, limiter
from app.helpers import utc_now
from app.models.instructor import Instructor

auth_bp = Blueprint('auth', __name__, template_folder='../templates/auth')
_RESET_EXPIRACION = timedelta(minutes=30)
_TOKEN_URLSAFE = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-')


@auth_bp.after_request
def _proteger_respuestas_de_recuperacion(response):
    if request.endpoint in ('auth.solicitar_recuperacion', 'auth.restablecer_contrasena'):
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = (
            "default-src 'none'; style-src 'self'; script-src 'self'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "img-src 'self' data:"
        )
    return response


def _clave_limite_por_correo():
    correo = (request.form.get('correo') or '').strip().lower()
    secreto = str(current_app.config.get('SECRET_KEY') or '').encode('utf-8')
    digest = hmac.new(secreto, correo.encode('utf-8'), hashlib.sha256).hexdigest()
    return f'recuperacion:{digest}'


def _url_publica_configurada():
    base_url = current_app.config.get('PUBLIC_BASE_URL') or ''
    try:
        partes = urlsplit(base_url)
    except ValueError:
        return None
    if (
        partes.scheme not in ('https', 'http')
        or not partes.netloc
        or partes.username
        or partes.password
        or not partes.hostname
        or any(caracter in partes.netloc for caracter in '<> \r\n\t')
        or partes.query
        or partes.fragment
        or partes.path not in ('', '/')
    ):
        return None
    try:
        partes.port
    except ValueError:
        return None
    if current_app.config.get('FLASK_ENV') == 'production' and partes.scheme != 'https':
        return None
    return f'{partes.scheme}://{partes.netloc}'


def _enviar_correo_recuperacion(instructor, enlace):
    host = current_app.config.get('SMTP_HOST')
    remitente = current_app.config.get('SMTP_FROM') or current_app.config.get('SMTP_USER')
    usuario = current_app.config.get('SMTP_USER')
    clave_smtp = current_app.config.get('SMTP_PASSWORD')
    if not host or not remitente or not _url_publica_configurada():
        return False
    if bool(usuario) != bool(clave_smtp):
        return False

    try:
        mensaje = EmailMessage()
        mensaje['Subject'] = 'Recuperación de contraseña - SENA Control Académico'
        mensaje['From'] = remitente
        mensaje['To'] = instructor.correo
        mensaje.set_content(
            f'Hola {instructor.nombre},\n\n'
            'Recibimos una solicitud para cambiar la contraseña de tu cuenta. '
            'Usa este enlace en los próximos 30 minutos:\n\n'
            f'{enlace}\n\n'
            'Si no solicitaste el cambio, ignora este mensaje. Tu contraseña no cambiará.'
        )

        puerto = int(current_app.config.get('SMTP_PORT') or 587)
        contexto_tls = ssl.create_default_context()
        if puerto == 465:
            servidor = smtplib.SMTP_SSL(
                host, puerto, timeout=8, context=contexto_tls
            )
        else:
            servidor = smtplib.SMTP(host, puerto, timeout=8)
        with servidor:
            if puerto != 465:
                servidor.starttls(context=contexto_tls)
            if usuario and clave_smtp:
                servidor.login(usuario, clave_smtp)
            servidor.send_message(mensaje)
        return True
    except Exception as error:
        current_app.logger.warning(
            'No se pudo enviar el correo de recuperación (%s).', type(error).__name__
        )
        return False


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


@auth_bp.route('/recuperar-contrasena', methods=['GET', 'POST'])
@limiter.limit('10 per hour', methods=['POST'])
@limiter.limit('3 per hour', key_func=_clave_limite_por_correo, methods=['POST'])
def solicitar_recuperacion():
    if request.method == 'POST':
        correo = request.form.get('correo', '').strip().lower()
        base_url = _url_publica_configurada()
        usuario_smtp = current_app.config.get('SMTP_USER')
        clave_smtp = current_app.config.get('SMTP_PASSWORD')
        smtp_configurado = bool(
            current_app.config.get('SMTP_HOST')
            and (current_app.config.get('SMTP_FROM') or current_app.config.get('SMTP_USER'))
            and base_url
            and (bool(usuario_smtp) == bool(clave_smtp))
        )

        if correo and len(correo) <= 150 and smtp_configurado:
            instructor = Instructor.query.filter(
                func.lower(Instructor.correo) == correo
            ).first()
            if instructor and instructor.activo:
                token = secrets.token_urlsafe(32)
                instructor.password_reset_token_hash = hashlib.sha256(
                    token.encode('ascii')
                ).hexdigest()
                instructor.password_reset_expires_at = utc_now() + _RESET_EXPIRACION
                db.session.commit()

                enlace = f'{base_url}{url_for("auth.restablecer_contrasena")}#{token}'
                if not _enviar_correo_recuperacion(instructor, enlace):
                    instructor.password_reset_token_hash = None
                    instructor.password_reset_expires_at = None
                    db.session.commit()
        elif not smtp_configurado:
            current_app.logger.warning(
                'Recuperación no disponible: configure SMTP y PUBLIC_BASE_URL HTTPS.'
            )

        # El mismo mensaje para cuentas existentes, inactivas, inexistentes y
        # cuando el correo no se puede entregar, evitando revelar la identidad.
        flash(
            'Si existe una cuenta activa con ese correo, recibirás un enlace para cambiar la contraseña.',
            'success',
        )

    return render_template('recuperar_contrasena.html')


@auth_bp.route('/restablecer-contrasena', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'])
def restablecer_contrasena():
    token = request.form.get('token', '') if request.method == 'POST' else ''

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirmacion = request.form.get('confirmacion', '')
        if len(password) < 12:
            flash('La nueva contraseña debe tener al menos 12 caracteres.', 'error')
            return render_template('restablecer_contrasena.html', token=token)
        if len(password) > 128:
            flash('La contraseña no puede superar 128 caracteres.', 'error')
            return render_template('restablecer_contrasena.html', token=token)
        if password != confirmacion:
            flash('Las contraseñas no coinciden.', 'error')
            return render_template('restablecer_contrasena.html', token=token)

        token_valido = (
            20 <= len(token) <= 128 and all(caracter in _TOKEN_URLSAFE for caracter in token)
        )
        if token_valido:
            huella = hashlib.sha256(token.encode('ascii')).hexdigest()
            instructor = (
                Instructor.query.filter_by(password_reset_token_hash=huella)
                .with_for_update()
                .first()
            )
        else:
            instructor = None

        ahora = utc_now()
        if (
            not instructor
            or not instructor.activo
            or not instructor.password_reset_expires_at
            or instructor.password_reset_expires_at <= ahora
        ):
            flash('El enlace no es válido o venció. Solicita uno nuevo.', 'error')
            return render_template('restablecer_contrasena.html', token='')

        instructor.set_password(password)
        instructor.auth_version += 1
        instructor.password_reset_token_hash = None
        instructor.password_reset_expires_at = None
        db.session.commit()
        logout_user()
        flash('Contraseña actualizada. Ya puedes iniciar sesión.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('restablecer_contrasena.html', token='')


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
