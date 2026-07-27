from app import db


# Estados que cuentan como "en formacion": unicos habilitados para llamado a
# lista, turnos de aseo y ranking.
ESTADOS_EN_FORMACION = ('EN', 'EN_FORMACION')


class Aprendiz(db.Model):
    __tablename__ = 'aprendices'

    id = db.Column(db.Integer, primary_key=True)
    documento = db.Column(db.String(20), nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False)
    apellidos = db.Column(db.String(150), nullable=False)
    tipo_documento = db.Column(db.String(5), default='CC')
    correo = db.Column(db.String(150), nullable=True)
    estado = db.Column(db.String(20), default='EN_FORMACION')
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)

    registros_asistencia = db.relationship('RegistroAsistencia', backref='aprendiz',
                                           lazy='dynamic', cascade='all, delete-orphan')
    entregas = db.relationship('Entrega', backref='aprendiz', lazy='dynamic',
                               cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('documento', 'ficha_id', name='uq_aprendiz_documento_ficha'),
    )

    @classmethod
    def query_en_formacion(cls, ficha_id):
        """Query de aprendices de la ficha que siguen en formacion."""
        return cls.query.filter(
            cls.ficha_id == ficha_id,
            cls.estado.in_(ESTADOS_EN_FORMACION),
        )

    @property
    def en_formacion(self):
        return self.estado in ESTADOS_EN_FORMACION

    @property
    def nombre_completo(self):
        return f'{self.nombre} {self.apellidos}'

    def __repr__(self):
        return f'<Aprendiz {self.documento} - {self.nombre} {self.apellidos}>'
