from datetime import datetime

from app import db


class ImportacionJob(db.Model):
    """Trabajo durable para procesar reportes Excel fuera de Gunicorn."""

    __tablename__ = 'importaciones_jobs'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=False, index=True)
    archivo_path = db.Column(db.String(500), nullable=False)
    nombre_archivo = db.Column(db.String(255), nullable=False)
    estado = db.Column(db.String(20), nullable=False, default='encolado', index=True)
    resultado = db.Column(db.Text, nullable=True)
    error = db.Column(db.Text, nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    iniciado_en = db.Column(db.DateTime, nullable=True)
    terminado_en = db.Column(db.DateTime, nullable=True)

    ficha = db.relationship('Ficha', backref=db.backref('importaciones', lazy='dynamic'))
    instructor = db.relationship('Instructor', backref=db.backref('importaciones', lazy='dynamic'))
