from app.helpers import utc_now

from app import db


class Corte(db.Model):
    """Periodo independiente de trabajo dentro de una ficha compartida."""

    __tablename__ = 'cortes'

    ESTADO_ACTIVO = 'activo'
    ESTADO_CERRADO = 'cerrado'
    ESTADO_ARCHIVADO = 'archivado'
    ESTADOS = (ESTADO_ACTIVO, ESTADO_CERRADO, ESTADO_ARCHIVADO)

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=False, index=True)
    nombre = db.Column(db.String(120), nullable=False)
    fecha_inicio = db.Column(db.DateTime, nullable=False, default=utc_now)
    fecha_fin = db.Column(db.DateTime, nullable=True)
    compartido = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    estado = db.Column(db.String(20), nullable=False, default=ESTADO_ACTIVO, server_default=ESTADO_ACTIVO, index=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=utc_now)

    ficha = db.relationship('Ficha', back_populates='cortes')
    creador = db.relationship('Instructor', backref=db.backref('cortes_creados', lazy='dynamic'))
    tareas = db.relationship('Tarea', back_populates='corte', lazy='dynamic')
    sesiones = db.relationship('SesionAsistencia', back_populates='corte', lazy='dynamic')

    __table_args__ = (
        db.Index('ix_cortes_ficha_inicio', 'ficha_id', 'fecha_inicio'),
    )

    def __repr__(self):
        return f'<Corte {self.nombre} - Ficha {self.ficha_id}>'

    @property
    def esta_activo(self):
        return self.estado == self.ESTADO_ACTIVO

    @property
    def es_consultable(self):
        return self.estado in self.ESTADOS
