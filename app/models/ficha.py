from app import db
from app.helpers import utc_now


class Ficha(db.Model):
    __tablename__ = 'fichas'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), nullable=False, index=True)
    codigo_ficha = db.Column(db.String(30), nullable=True, index=True)
    codigo_programa = db.Column(db.String(30), nullable=True, index=True)
    nombre_programa = db.Column(db.String(200), nullable=False)
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=False)
    # Equipo ejecutor que orienta la ficha; entre equipos solo se programan transversales.
    equipo_id = db.Column(db.Integer, db.ForeignKey('equipos_ejecutores.id', ondelete='SET NULL'),
                          nullable=True, index=True)
    fecha_inicio = db.Column(db.Date, nullable=True)
    fecha_fin = db.Column(db.Date, nullable=True)
    duracion_productiva_meses = db.Column(db.Integer, nullable=False, default=6)
    revision_calculos = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    creada_en = db.Column(db.DateTime, default=utc_now)

    __table_args__ = (
        db.Index('uq_ficha_codigo_ficha', 'codigo_ficha', unique=True,
                 postgresql_where=db.text("codigo_ficha IS NOT NULL")),
    )

    equipo = db.relationship('EquipoEjecutor', foreign_keys=[equipo_id])
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
    cortes = db.relationship('Corte', back_populates='ficha', lazy='dynamic',
                             cascade='all, delete-orphan')
    archivos_versionados = db.relationship('ArchivoFichaVersion', back_populates='ficha',
                                           lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Ficha {self.codigo} - {self.nombre_programa}>'


@db.event.listens_for(Ficha, 'before_insert')
def asignar_equipo_del_responsable(_mapper, connection, ficha):
    """Una ficha nueva queda, por defecto, en el equipo ejecutor de su responsable."""
    if ficha.equipo_id is None and ficha.instructor_id:
        from app.models.instructor import Instructor
        ficha.equipo_id = connection.execute(
            db.select(Instructor.equipo_id).where(Instructor.id == ficha.instructor_id)
        ).scalar()
