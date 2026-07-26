from app import db
from datetime import datetime

class MaterialFicha(db.Model):
    __tablename__ = 'materiales_ficha'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=False, index=True)
    nombre_archivo = db.Column(db.String(255), nullable=False)
    url_archivo = db.Column(db.String(500), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    subido_en = db.Column(db.DateTime, default=datetime.utcnow)

    # Relación con el instructor que lo subió
    subido_por = db.relationship('Instructor', backref=db.backref('materiales_subidos', lazy='dynamic'))

    def __repr__(self):
        return f'<MaterialFicha {self.nombre_archivo}>'
