from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager
from datetime import datetime


class Instructor(UserMixin, db.Model):
    __tablename__ = 'instructores'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    correo = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default='colaborador')
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    fichas = db.relationship('Ficha', backref='instructor', lazy='dynamic')
    fichas_asociadas = db.relationship('FichaInstructor', back_populates='instructor',
                                       lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def es_admin(self):
        return self.rol == 'admin'

    def __repr__(self):
        return f'<Instructor {self.nombre}>'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Instructor, int(user_id))
