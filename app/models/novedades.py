"""Novedades académicas y etapa productiva del aprendiz (Acuerdo 009 de 2024, Art. 18)."""

from app import db
from app.helpers import utc_now

TIPOS_NOVEDAD = {
    'aplazamiento': 'Aplazamiento',
    'traslado': 'Traslado',
    'retiro_voluntario': 'Retiro voluntario',
    'reintegro': 'Reintegro',
}
ESTADOS_NOVEDAD = {'solicitada': 'Solicitada', 'autorizada': 'Autorizada', 'negada': 'Negada'}
# Art. 18, num. 2, literales a) a f) (pág. 22).
CAUSAS_APLAZAMIENTO = {
    'incapacidad': 'a) Incapacidad médica igual o superior a 20 días',
    'licencia': 'b) Licencia de maternidad o paternidad',
    'calamidad': 'c) Calamidad doméstica',
    'judicial': 'd) Asuntos judiciales',
    'representacion': 'e) Representación del SENA o del país',
    'servicio_militar': 'f) Prestación del servicio militar',
}
ALTERNATIVAS_PRODUCTIVA = {
    'contrato_aprendizaje': 'Contrato de aprendizaje',
    'vinculo_laboral': 'Vínculo laboral',
    'pasantia': 'Pasantía',
    'proyecto_productivo': 'Proyecto productivo',
    'monitoria': 'Monitoría',
    'otra': 'Otra alternativa',
}
ESTADOS_PRODUCTIVA = {'por_iniciar': 'Por iniciar', 'en_curso': 'En curso', 'finalizada': 'Finalizada'}
MOMENTOS_SEGUIMIENTO = {'concertacion': 'Concertación', 'parcial': 'Seguimiento parcial', 'final': 'Evaluación final'}


class NovedadAprendiz(db.Model):
    __tablename__ = 'novedades_aprendiz'

    id = db.Column(db.Integer, primary_key=True)
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id'), nullable=False, index=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    tipo = db.Column(db.String(30), nullable=False)
    estado = db.Column(db.String(20), nullable=False, default='solicitada')
    fecha_solicitud = db.Column(db.Date, nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=True)
    fecha_fin = db.Column(db.Date, nullable=True)
    causa = db.Column(db.String(30), nullable=True)
    ampliacion = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    observacion = db.Column(db.Text, nullable=True)
    creado_por = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=utc_now)
    # La ampliación del aplazamiento la recomienda el comité (Art. 18, num. 2).
    acta_comite = db.Column(db.String(60), nullable=True)
    estado_cambiado_en = db.Column(db.DateTime, nullable=True)
    estado_cambiado_por = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=True)

    aprendiz = db.relationship('Aprendiz', backref=db.backref('novedades', lazy='dynamic'))

    @property
    def etiqueta_tipo(self):
        return TIPOS_NOVEDAD.get(self.tipo, self.tipo)

    @property
    def etiqueta_estado(self):
        return ESTADOS_NOVEDAD.get(self.estado, self.estado)


class EtapaProductiva(db.Model):
    __tablename__ = 'etapas_productivas'

    id = db.Column(db.Integer, primary_key=True)
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id'), nullable=False, index=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    alternativa = db.Column(db.String(30), nullable=False)
    empresa = db.Column(db.String(200), nullable=True)
    fecha_inicio = db.Column(db.Date, nullable=True)
    fecha_fin_estimada = db.Column(db.Date, nullable=True)
    planeacion_avalada = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    fecha_aval = db.Column(db.Date, nullable=True)
    instructor_seguimiento = db.Column(db.String(150), nullable=True)
    estado = db.Column(db.String(20), nullable=False, default='por_iniciar')
    actualizado_en = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    aprendiz = db.relationship('Aprendiz', backref=db.backref('etapa_productiva', uselist=False))
    seguimientos = db.relationship('SeguimientoProductiva', backref='etapa', lazy='selectin',
                                   cascade='all, delete-orphan',
                                   order_by='SeguimientoProductiva.fecha')

    __table_args__ = (
        db.UniqueConstraint('aprendiz_id', 'ficha_id', name='uq_etapa_productiva_aprendiz_ficha'),
    )

    @property
    def etiqueta_alternativa(self):
        return ALTERNATIVAS_PRODUCTIVA.get(self.alternativa, self.alternativa)

    @property
    def etiqueta_estado(self):
        return ESTADOS_PRODUCTIVA.get(self.estado, self.estado)


class SeguimientoProductiva(db.Model):
    __tablename__ = 'seguimientos_productiva'

    id = db.Column(db.Integer, primary_key=True)
    etapa_id = db.Column(db.Integer, db.ForeignKey('etapas_productivas.id'), nullable=False, index=True)
    momento = db.Column(db.String(20), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    observacion = db.Column(db.Text, nullable=True)
    creado_por = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('etapa_id', 'momento', name='uq_seguimiento_etapa_momento'),
    )

    @property
    def etiqueta_momento(self):
        return MOMENTOS_SEGUIMIENTO.get(self.momento, self.momento)
