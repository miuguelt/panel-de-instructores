from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager
from app.helpers import utc_now


class Instructor(UserMixin, db.Model):
    __tablename__ = 'instructores'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    correo = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    auth_version = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    password_reset_token_hash = db.Column(
        db.String(64), unique=True, index=True, nullable=True
    )
    password_reset_expires_at = db.Column(db.DateTime, nullable=True)
    rol = db.Column(db.String(20), nullable=False, default='colaborador')
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=utc_now)

    fichas = db.relationship('Ficha', backref='instructor', lazy='dynamic')
    fichas_asociadas = db.relationship('FichaInstructor', back_populates='instructor',
                                       lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        """Ata sesiones y cookies recordadas a la versión actual de credenciales."""
        return f'{self.id}:{self.auth_version or 1}'

    @property
    def es_admin(self):
        return self.rol == 'admin'

    def __repr__(self):
        return f'<Instructor {self.nombre}>'


@login_manager.user_loader
def load_user(user_id):
    if not user_id:
        return None

    # Las sesiones emitidas antes de auth_version conservan su formato numérico.
    # Se aceptan mientras la cuenta no haya restablecido su contraseña; al hacerlo,
    # la versión aumenta y también quedan invalidadas esas sesiones antiguas.
    if ':' not in user_id:
        try:
            instructor = db.session.get(Instructor, int(user_id))
        except (TypeError, ValueError):
            return None
        return instructor if instructor and instructor.auth_version == 1 else None

    instructor_id, version = user_id.rsplit(':', 1)
    try:
        instructor = db.session.get(Instructor, int(instructor_id))
        version = int(version)
    except (TypeError, ValueError):
        return None
    if instructor and instructor.auth_version == version:
        return instructor
    return None
