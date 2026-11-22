"""Equipos ejecutores: agrupan instructores por área (Sistemas, Agrícola, Contabilidad...)."""

from app import db
from app.helpers import utc_now


class EquipoEjecutor(db.Model):
    __tablename__ = 'equipos_ejecutores'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False, unique=True)
    descripcion = db.Column(db.String(300), nullable=True)
    lider_id = db.Column(
        db.Integer,
        db.ForeignKey('instructores.id', use_alter=True, name='fk_equipo_lider_instructor'),
        nullable=True, index=True,
    )
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=utc_now)

    lider = db.relationship('Instructor', foreign_keys=[lider_id])
    miembros = db.relationship(
        'Instructor', foreign_keys='Instructor.equipo_id', back_populates='equipo',
        lazy='select', order_by='Instructor.nombre',
    )

    def __repr__(self):
        return f'<EquipoEjecutor {self.nombre}>'
