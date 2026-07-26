from app import db
from datetime import datetime


class Tarea(db.Model):
    __tablename__ = 'tareas'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=False, index=True)
    titulo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    enlace_externo = db.Column(db.String(500), nullable=True)
    material_apoyo_url = db.Column(db.String(500), nullable=True)
    fecha_limite = db.Column(db.DateTime, nullable=True)
    requiere_archivo = db.Column(db.Boolean, default=True)
    creada_en = db.Column(db.DateTime, default=datetime.utcnow)

    entregas = db.relationship('Entrega', backref='tarea', lazy='dynamic',
                               cascade='all, delete-orphan')
    creador = db.relationship(
        'Instructor',
        foreign_keys=[instructor_id],
        backref=db.backref('tareas_creadas', lazy='dynamic'),
    )

    def __repr__(self):
        return f'<Tarea {self.titulo}>'


class Entrega(db.Model):
    __tablename__ = 'entregas'

    id = db.Column(db.Integer, primary_key=True)
    tarea_id = db.Column(db.Integer, db.ForeignKey('tareas.id'), nullable=False, index=True)
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id'), nullable=False, index=True)
    archivo_url = db.Column(db.String(500), nullable=True)
    enlace_repositorio = db.Column(db.String(500), nullable=True)
    fecha_entrega = db.Column(db.DateTime, default=datetime.utcnow)
    calificada = db.Column(db.Boolean, default=False)
    calificacion = db.Column(db.String(10), nullable=True)
    feedback = db.Column(db.Text, nullable=True)
    estado_revision = db.Column(db.String(20), nullable=False, default='pendiente')
    revisada_en = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            'tarea_id',
            'aprendiz_id',
            name='uq_entrega_tarea_aprendiz',
        ),
    )

    @property
    def entregada_a_tiempo(self):
        if not self.tarea.fecha_limite:
            return True
        return self.fecha_entrega <= self.tarea.fecha_limite

    @property
    def entregada_con_retraso(self):
        if not self.tarea.fecha_limite:
            return False
        return self.fecha_entrega > self.tarea.fecha_limite
