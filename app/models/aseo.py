from datetime import datetime

from app import db


ESTADOS_TURNO_ASEO = ('programado', 'cumplido', 'intercambiado')
ORIGENES_TURNO_ASEO = ('sistema', 'instructor')
ESTADOS_INTERCAMBIO_ASEO = ('pendiente', 'aceptado', 'rechazado')


class ConfiguracionAseo(db.Model):
    __tablename__ = 'configuracion_aseo'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(
        db.Integer, db.ForeignKey('fichas.id'), nullable=False, unique=True
    )
    excluir_ausentes = db.Column(db.Boolean, nullable=False, default=True)
    aviso_horas = db.Column(db.Integer, nullable=False, default=24)
    actualizada_en = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ContadorAseo(db.Model):
    __tablename__ = 'contador_aseo'

    id = db.Column(db.Integer, primary_key=True)
    aprendiz_id = db.Column(
        db.Integer, db.ForeignKey('aprendices.id'), nullable=False, index=True
    )
    ficha_id = db.Column(
        db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True
    )
    veces_aseo = db.Column(db.Integer, nullable=False, default=0)
    ultima_vez_aseo = db.Column(db.Date, nullable=True)
    excluido_hasta = db.Column(db.Date, nullable=True)
    motivo_exclusion = db.Column(db.String(250), nullable=True)

    aprendiz = db.relationship(
        'Aprendiz', backref=db.backref('contador_aseo', uselist=False)
    )

    __table_args__ = (
        db.UniqueConstraint(
            'aprendiz_id', 'ficha_id', name='uq_contador_aseo_aprendiz_ficha'
        ),
    )


class TurnoAseo(db.Model):
    __tablename__ = 'turnos_aseo'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(
        db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True
    )
    fecha = db.Column(db.Date, nullable=False, index=True)
    aprendiz_1_id = db.Column(
        db.Integer, db.ForeignKey('aprendices.id'), nullable=False
    )
    aprendiz_2_id = db.Column(
        db.Integer, db.ForeignKey('aprendices.id'), nullable=False
    )
    estado = db.Column(db.String(20), nullable=False, default='programado')
    generado_por = db.Column(db.String(20), nullable=False, default='sistema')
    auditoria_1 = db.Column(db.Text, nullable=True)
    auditoria_2 = db.Column(db.Text, nullable=True)
    observacion = db.Column(db.Text, nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    actualizado_en = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completado_en = db.Column(db.DateTime, nullable=True)
    completado_1 = db.Column(db.Boolean, nullable=True)
    completado_2 = db.Column(db.Boolean, nullable=True)

    aprendiz_1 = db.relationship('Aprendiz', foreign_keys=[aprendiz_1_id])
    aprendiz_2 = db.relationship('Aprendiz', foreign_keys=[aprendiz_2_id])
    intercambios = db.relationship(
        'IntercambioAseo',
        back_populates='turno',
        foreign_keys='IntercambioAseo.turno_id',
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.UniqueConstraint('ficha_id', 'fecha', name='uq_turno_aseo_ficha_fecha'),
        db.CheckConstraint(
            'aprendiz_1_id <> aprendiz_2_id',
            name='ck_turno_aseo_aprendices_distintos',
        ),
    )

    @property
    def aprendices(self):
        return (self.aprendiz_1, self.aprendiz_2)

    def incluye(self, aprendiz_id):
        return aprendiz_id in (self.aprendiz_1_id, self.aprendiz_2_id)


class IntercambioAseo(db.Model):
    __tablename__ = 'intercambios_aseo'

    id = db.Column(db.Integer, primary_key=True)
    turno_id = db.Column(
        db.Integer, db.ForeignKey('turnos_aseo.id'), nullable=False, index=True
    )
    turno_reciproco_id = db.Column(
        db.Integer, db.ForeignKey('turnos_aseo.id'), nullable=True
    )
    aprendiz_solicita_id = db.Column(
        db.Integer, db.ForeignKey('aprendices.id'), nullable=False
    )
    aprendiz_recibe_id = db.Column(
        db.Integer, db.ForeignKey('aprendices.id'), nullable=False
    )
    estado = db.Column(db.String(20), nullable=False, default='pendiente')
    confirma_solicita = db.Column(db.Boolean, nullable=False, default=True)
    confirma_recibe = db.Column(db.Boolean, nullable=False, default=False)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    respondido_en = db.Column(db.DateTime, nullable=True)

    turno = db.relationship(
        'TurnoAseo', back_populates='intercambios', foreign_keys=[turno_id]
    )
    turno_reciproco = db.relationship(
        'TurnoAseo', foreign_keys=[turno_reciproco_id]
    )
    aprendiz_solicita = db.relationship(
        'Aprendiz', foreign_keys=[aprendiz_solicita_id]
    )
    aprendiz_recibe = db.relationship(
        'Aprendiz', foreign_keys=[aprendiz_recibe_id]
    )
