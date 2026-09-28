from app.helpers import utc_now
from app import db


class Grupo(db.Model):
    __tablename__ = 'grupos'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False)
    creado_en = db.Column(db.DateTime, nullable=False, default=utc_now)
    activo = db.Column(db.Boolean, nullable=False, default=True)

    # Relaciones
    ficha = db.relationship('Ficha', backref=db.backref('grupos', lazy='dynamic', cascade='all, delete-orphan'))
    aprendices = db.relationship('Aprendiz', secondary='grupo_aprendiz', backref=db.backref('grupos_asignados', lazy='dynamic'))


class GrupoAprendiz(db.Model):
    __tablename__ = 'grupo_aprendiz'

    grupo_id = db.Column(db.Integer, db.ForeignKey('grupos.id', ondelete='CASCADE'), primary_key=True)
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id', ondelete='CASCADE'), primary_key=True)
    asignado_en = db.Column(db.DateTime, nullable=False, default=utc_now)
