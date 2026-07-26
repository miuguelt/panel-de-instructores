from app import db
from datetime import datetime


ESTADOS_ASISTENCIA = [
    ('ASISTE', 'Asiste'),
    ('FALTA', 'Falta'),
    ('FALTA_JUSTIFICADA', 'Falta justificada'),
    ('EXCUSA_MEDICA', 'Excusa medica'),
    ('TARDANZA', 'Tardanza'),
]

CAUSALES_JUSTIFICADAS = [
    ('CITA_MEDICA', 'Cita medica'),
    ('DILIGENCIA_ELECTORAL', 'Diligencia electoral/gubernamental'),
    ('REQUERIMIENTO_LABORAL', 'Requerimiento laboral excepcional'),
    ('OTRA', 'Otra causal justificada'),
]


class SesionAsistencia(db.Model):
    __tablename__ = 'sesiones_asistencia'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    fecha = db.Column(db.Date, nullable=False)
    observaciones = db.Column(db.Text, nullable=True)
    creada_en = db.Column(db.DateTime, default=datetime.utcnow)

    registros = db.relationship('RegistroAsistencia', backref='sesion', lazy='dynamic',
                                cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('ficha_id', 'fecha', name='uq_sesion_ficha_fecha'),
    )

    def __repr__(self):
        return f'<Sesion {self.fecha} - Ficha {self.ficha_id}>'


class RegistroAsistencia(db.Model):
    __tablename__ = 'registros_asistencia'

    id = db.Column(db.Integer, primary_key=True)
    sesion_id = db.Column(db.Integer, db.ForeignKey('sesiones_asistencia.id'), nullable=False)
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id'), nullable=False)
    estado = db.Column(db.String(25), nullable=False, default='ASISTE')
    causal_justificacion = db.Column(db.String(30), nullable=True)
    nota = db.Column(db.Text, nullable=True)
    soporte_url = db.Column(db.String(500), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('sesion_id', 'aprendiz_id', name='uq_registro_sesion_aprendiz'),
    )
