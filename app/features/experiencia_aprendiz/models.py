"""Preferencias de experiencia e hitos separados de los resultados académicos."""

from sqlalchemy.orm import backref

from app import db
from app.models.archivo_ficha import TIPO_JSON_ESTRUCTURADO


class ExperienciaAprendiz(db.Model):
    __tablename__ = 'experiencias_aprendiz'

    aprendiz_id = db.Column(
        db.Integer, db.ForeignKey('aprendices.id', ondelete='CASCADE'), primary_key=True,
    )
    preferences = db.Column(TIPO_JSON_ESTRUCTURADO, nullable=False)
    revision = db.Column(db.Integer, nullable=False)
    logros = db.Column(TIPO_JSON_ESTRUCTURADO, nullable=False, default=list)
    aprendiz = db.relationship(
        'Aprendiz', backref=backref('experiencia', uselist=False, cascade='all, delete-orphan'),
    )

    __table_args__ = (
        db.CheckConstraint('revision >= 1', name='ck_experiencia_revision_positiva'),
    )
