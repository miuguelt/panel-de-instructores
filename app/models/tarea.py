from app import db
from datetime import datetime


# Modalidades de trabajo de una tarea.
#   evidencia -> el aprendiz entrega algo (archivo y/o enlace) desde su panel.
#   clase     -> la actividad se revisa presencialmente; el instructor aprueba
#                en el sistema y el aprendiz no sube nada.
MODALIDAD_EVIDENCIA = 'evidencia'
MODALIDAD_CLASE = 'clase'
MODALIDADES_TAREA = (MODALIDAD_EVIDENCIA, MODALIDAD_CLASE)


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
    modalidad = db.Column(
        db.String(20), nullable=False, default=MODALIDAD_EVIDENCIA, server_default=MODALIDAD_EVIDENCIA
    )
    creada_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizada_en = db.Column(db.DateTime, nullable=True)

    entregas = db.relationship('Entrega', backref='tarea', lazy='dynamic',
                               cascade='all, delete-orphan')
    creador = db.relationship(
        'Instructor',
        foreign_keys=[instructor_id],
        backref=db.backref('tareas_creadas', lazy='dynamic'),
    )

    @property
    def es_actividad_clase(self):
        """La actividad se aprueba en el aula y no admite entregas del aprendiz."""
        return self.modalidad == MODALIDAD_CLASE

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
    # Registro creado por el instructor al aprobar una actividad de aula, no
    # por una subida del aprendiz. Distingue la evidencia digital del
    # desempeño verificado presencialmente.
    registrada_por_instructor = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false()
    )
    revisada_por_id = db.Column(
        db.Integer, db.ForeignKey('instructores.id'), nullable=True, index=True
    )

    revisor = db.relationship('Instructor', foreign_keys=[revisada_por_id])

    __table_args__ = (
        db.UniqueConstraint(
            'tarea_id',
            'aprendiz_id',
            name='uq_entrega_tarea_aprendiz',
        ),
    )

    @property
    def entregada_a_tiempo(self):
        # La aprobación de una actividad de aula lleva la fecha en que el
        # instructor la registró, no la del desempeño del aprendiz. Marcarla
        # como retraso castigaría al aprendiz por el momento de la revisión.
        if self.registrada_por_instructor:
            return True
        if not self.tarea.fecha_limite:
            return True
        return self.fecha_entrega <= self.tarea.fecha_limite

    @property
    def entregada_con_retraso(self):
        if self.registrada_por_instructor:
            return False
        if not self.tarea.fecha_limite:
            return False
        return self.fecha_entrega > self.tarea.fecha_limite
