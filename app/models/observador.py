"""Observador del aprendiz: bitácora de la formación integral.

Registra hechos cortos y fechados sobre las dimensiones que no quedan
capturadas por la asistencia ni por las evidencias: puntualidad, convivencia,
trabajo en equipo, compromiso. Una alerta o un caso de seguimiento nacen de un
incumplimiento; estas notas existen para tener historial *antes* de que algo
escale, y para que un plan de mejoramiento se sustente en hechos con fecha en
lugar de impresiones.
"""

from datetime import date, datetime

from app import db


TIPO_POSITIVA = 'positiva'
TIPO_NEGATIVA = 'negativa'
TIPO_NEUTRA = 'neutra'
TIPOS_NOTA = (TIPO_POSITIVA, TIPO_NEGATIVA, TIPO_NEUTRA)

ETIQUETAS_TIPO = {
    TIPO_POSITIVA: 'Reconocimiento',
    TIPO_NEGATIVA: 'Llamado de atención',
    TIPO_NEUTRA: 'Observación',
}

# Dimensiones de la formación profesional integral. Se guarda la clave, no la
# etiqueta, para poder reescribir el texto sin migrar datos históricos.
CATEGORIAS_NOTA = (
    ('puntualidad', 'Puntualidad y asistencia'),
    ('convivencia', 'Convivencia y respeto'),
    ('trabajo_equipo', 'Trabajo en equipo'),
    ('compromiso', 'Compromiso y autogestión'),
    ('comunicacion', 'Comunicación'),
    ('seguridad', 'Seguridad y cuidado del ambiente'),
    ('desempeno', 'Desempeño técnico'),
    ('otra', 'Otra'),
)
CLAVES_CATEGORIA = tuple(clave for clave, _ in CATEGORIAS_NOTA)
ETIQUETAS_CATEGORIA = dict(CATEGORIAS_NOTA)


class NotaObservador(db.Model):
    __tablename__ = 'notas_observador'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id'), nullable=False, index=True)
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=False, index=True)
    tipo = db.Column(db.String(20), nullable=False, default=TIPO_NEUTRA, index=True)
    categoria = db.Column(db.String(30), nullable=False, default='otra')
    descripcion = db.Column(db.Text, nullable=False)
    # Fecha del hecho, no la del registro: una nota puede escribirse al día
    # siguiente y debe ordenarse por cuándo ocurrió.
    fecha = db.Column(db.Date, nullable=False, default=date.today, index=True)
    creada_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    actualizada_en = db.Column(db.DateTime, nullable=True)

    aprendiz = db.relationship(
        'Aprendiz', backref=db.backref('notas_observador', lazy='dynamic',
                                       cascade='all, delete-orphan')
    )
    ficha = db.relationship('Ficha', backref=db.backref('notas_observador', lazy='dynamic'))
    autor = db.relationship('Instructor', backref=db.backref('notas_observador', lazy='dynamic'))

    @property
    def etiqueta_tipo(self):
        return ETIQUETAS_TIPO.get(self.tipo, 'Observación')

    @property
    def etiqueta_categoria(self):
        return ETIQUETAS_CATEGORIA.get(self.categoria, 'Otra')

    def __repr__(self):
        return f'<NotaObservador {self.tipo} aprendiz={self.aprendiz_id}>'
