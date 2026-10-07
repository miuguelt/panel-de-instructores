"""Almacenamiento independiente de las preferencias visuales del aprendiz."""

from sqlalchemy.orm import backref

from app import db
from app.models.archivo_ficha import TIPO_JSON_ESTRUCTURADO


class PersonalizacionAprendiz(db.Model):
    __tablename__ = 'personalizaciones_aprendiz'

    aprendiz_id = db.Column(
        db.Integer, db.ForeignKey('aprendices.id', ondelete='CASCADE'), primary_key=True,
    )
    preferencias = db.Column(TIPO_JSON_ESTRUCTURADO, nullable=False)
    foto = db.Column(db.LargeBinary, nullable=True)
    revision = db.Column(db.Integer, nullable=False)
    aprendiz = db.relationship(
        'Aprendiz', backref=backref('personalizacion', uselist=False, cascade='all, delete-orphan'),
    )

    __table_args__ = (
        db.CheckConstraint('revision >= 1', name='ck_personalizacion_revision_positiva'),
    )
