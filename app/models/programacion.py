"""Asignaciones de programación: qué instructor orienta qué competencia, en qué ficha y cuándo."""

from app import db
from app.helpers import utc_now

# Días de la semana como máscara de bits (lunes=0 ... sábado=5). El domingo no se programa.
DIAS_SEMANA = (
    (0, 'L', 'Lunes'), (1, 'M', 'Martes'), (2, 'X', 'Miércoles'),
    (3, 'J', 'Jueves'), (4, 'V', 'Viernes'), (5, 'S', 'Sábado'),
)
MASCARA_LUNES_A_VIERNES = 0b011111
MASCARA_MAXIMA = 0b111111

JORNADAS = {'manana': 'Mañana', 'tarde': 'Tarde', 'noche': 'Noche'}


class AsignacionProgramacion(db.Model):
    __tablename__ = 'asignaciones_programacion'

    id = db.Column(db.Integer, primary_key=True)
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=False, index=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    competencia = db.Column(db.String(300), nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=False, index=True)
    fecha_fin = db.Column(db.Date, nullable=False, index=True)
    dias_semana = db.Column(db.Integer, nullable=False, default=MASCARA_LUNES_A_VIERNES)
    jornada = db.Column(db.String(10), nullable=False, default='manana')
    observacion = db.Column(db.String(300), nullable=True)
    creado_por_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=utc_now)
    actualizado_en = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    instructor = db.relationship('Instructor', foreign_keys=[instructor_id],
                                 backref=db.backref('asignaciones', lazy='dynamic'))
    creado_por = db.relationship('Instructor', foreign_keys=[creado_por_id])
    ficha = db.relationship('Ficha', backref=db.backref(
        'asignaciones_programacion', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.CheckConstraint('fecha_fin >= fecha_inicio', name='ck_asignacion_fechas'),
        db.CheckConstraint('dias_semana > 0 AND dias_semana < 64', name='ck_asignacion_dias'),
        db.CheckConstraint("jornada IN ('manana', 'tarde', 'noche')", name='ck_asignacion_jornada'),
    )

    def incluye_dia(self, dia_semana: int) -> bool:
        """Indica si el día (0=lunes) está marcado en la máscara."""
        return 0 <= dia_semana <= 5 and bool(self.dias_semana & (1 << dia_semana))

    @property
    def jornada_etiqueta(self) -> str:
        return JORNADAS.get(self.jornada, self.jornada)

    @property
    def dias_etiqueta(self) -> str:
        return ' '.join(letra for bit, letra, _ in DIAS_SEMANA if self.dias_semana & (1 << bit))
