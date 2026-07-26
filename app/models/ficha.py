from app import db
from datetime import datetime


class Ficha(db.Model):
    __tablename__ = 'fichas'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), nullable=False, index=True)
    codigo_ficha = db.Column(db.String(30), nullable=True, index=True)
    codigo_programa = db.Column(db.String(30), nullable=True, index=True)
    nombre_programa = db.Column(db.String(200), nullable=False)
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=True)
    fecha_fin = db.Column(db.Date, nullable=True)
    duracion_productiva_meses = db.Column(db.Integer, nullable=False, default=6)
    creada_en = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('uq_ficha_codigo_ficha', 'codigo_ficha', unique=True,
                 postgresql_where=db.text("codigo_ficha IS NOT NULL")),
    )

    aprendices = db.relationship('Aprendiz', backref='ficha', lazy='dynamic',
                                 cascade='all, delete-orphan')
    sesiones = db.relationship('SesionAsistencia', backref='ficha', lazy='dynamic',
                               cascade='all, delete-orphan')
    tareas = db.relationship('Tarea', backref='ficha', lazy='dynamic',
                             cascade='all, delete-orphan')
    configuracion_alertas = db.relationship('ConfiguracionAlertas', backref='ficha',
                                            uselist=False, cascade='all, delete-orphan')
    configuracion_ranking = db.relationship('ConfiguracionRanking', backref='ficha',
                                            uselist=False, cascade='all, delete-orphan')
    insignias = db.relationship('Insignia', backref='ficha', lazy='dynamic',
                                cascade='all, delete-orphan')
    puntajes_historicos = db.relationship('PuntajeHistorico', back_populates='ficha',
                                          lazy='dynamic', cascade='all, delete-orphan')
    turnos_aseo = db.relationship('TurnoAseo', backref='ficha', lazy='dynamic',
                                  cascade='all, delete-orphan')
    contadores_aseo = db.relationship('ContadorAseo', backref='ficha', lazy='dynamic',
                                      cascade='all, delete-orphan')
    configuracion_aseo = db.relationship('ConfiguracionAseo', backref='ficha',
                                         uselist=False, cascade='all, delete-orphan')
    instructores_asociados = db.relationship('FichaInstructor', back_populates='ficha',
                                              lazy='dynamic', cascade='all, delete-orphan')
    juicios_evaluativos = db.relationship('JuicioEvaluativo', back_populates='ficha',
                                          lazy='dynamic', cascade='all, delete-orphan')
    materiales = db.relationship('MaterialFicha', backref='ficha', lazy='dynamic',
                                 cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Ficha {self.codigo} - {self.nombre_programa}>'
