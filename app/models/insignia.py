from datetime import datetime

from app import db


class Insignia(db.Model):
    __tablename__ = 'insignias'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    codigo = db.Column(db.String(60), nullable=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.String(300), nullable=False)
    icono = db.Column(db.String(20), nullable=False, default='🏅')
    tipo = db.Column(db.String(20), nullable=False, default='manual')
    condicion_json = db.Column(db.JSON, nullable=True)
    activa = db.Column(db.Boolean, nullable=False, default=True)
    creada_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    otorgamientos = db.relationship(
        'InsigniaOtorgada',
        backref='insignia',
        lazy='dynamic',
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.UniqueConstraint('ficha_id', 'codigo', name='uq_insignia_ficha_codigo'),
    )


class InsigniaOtorgada(db.Model):
    __tablename__ = 'insignias_otorgadas'

    id = db.Column(db.Integer, primary_key=True)
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id'), nullable=False, index=True)
    insignia_id = db.Column(db.Integer, db.ForeignKey('insignias.id'), nullable=False, index=True)
    fecha_obtencion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    otorgada_por = db.Column(db.String(30), nullable=False, default='sistema')
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=True)
    notificada = db.Column(db.Boolean, nullable=False, default=False)

    aprendiz = db.relationship(
        'Aprendiz',
        backref=db.backref('insignias_otorgadas', cascade='all, delete-orphan'),
    )
    instructor = db.relationship('Instructor')

    __table_args__ = (
        db.UniqueConstraint('aprendiz_id', 'insignia_id', name='uq_aprendiz_insignia'),
    )
