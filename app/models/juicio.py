from datetime import datetime

from app import db


class JuicioEvaluativo(db.Model):
    __tablename__ = 'juicios_evaluativos'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id'), nullable=False, index=True)
    competencia = db.Column(db.String(300), nullable=True)
    tipo_competencia = db.Column(db.String(20), nullable=True)
    resultado_aprendizaje = db.Column(db.Text, nullable=True)
    juicio = db.Column(db.String(80), nullable=True)
    fecha_juicio = db.Column(db.DateTime, nullable=True, index=True)
    fecha_fuente_texto = db.Column(db.String(80), nullable=True)
    funcionario_registro = db.Column(db.String(200), nullable=True)
    fuente_archivo = db.Column(db.String(255), nullable=True)
    huella = db.Column(db.String(64), nullable=False, unique=True, index=True)
    importado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    ficha = db.relationship('Ficha', back_populates='juicios_evaluativos')
    aprendiz = db.relationship('Aprendiz', backref=db.backref('juicios_evaluativos', lazy='dynamic'))
    instructores = db.relationship('JuicioEvaluativoInstructor', back_populates='juicio',
                                    lazy='dynamic', cascade='all, delete-orphan')


class JuicioEvaluativoInstructor(db.Model):
    __tablename__ = 'juicios_evaluativos_instructores'

    id = db.Column(db.Integer, primary_key=True)
    juicio_id = db.Column(db.Integer, db.ForeignKey('juicios_evaluativos.id'), nullable=False, index=True)
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=False, index=True)
    fecha_importacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    juicio = db.relationship('JuicioEvaluativo', back_populates='instructores')
    instructor = db.relationship('Instructor', backref=db.backref('juicios_importados', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('juicio_id', 'instructor_id', name='uq_juicio_instructor'),
    )


class FichaCompetenciaSeleccionada(db.Model):
    __tablename__ = 'fichas_competencias_seleccionadas'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    competencia = db.Column(db.String(300), nullable=False)
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=False, index=True)
    fecha_seleccion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    ficha = db.relationship('Ficha', backref=db.backref('competencias_seleccionadas', lazy='dynamic', cascade='all, delete-orphan'))
    instructor = db.relationship('Instructor', backref=db.backref('competencias_seleccionadas', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('ficha_id', 'competencia', name='uq_ficha_competencia_sel'),
    )

