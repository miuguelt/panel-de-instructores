from datetime import datetime

from app import db


class FichaInstructor(db.Model):
    """Vincula instructores colaboradores a una ficha compartida."""

    __tablename__ = 'fichas_instructores'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=False, index=True)
    fecha_asignacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    ficha = db.relationship('Ficha', back_populates='instructores_asociados')
    instructor = db.relationship('Instructor', back_populates='fichas_asociadas')

    __table_args__ = (
        db.UniqueConstraint('ficha_id', 'instructor_id', name='uq_ficha_instructor'),
    )

