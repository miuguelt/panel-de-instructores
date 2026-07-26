from datetime import datetime

from app import db


class ConfiguracionRanking(db.Model):
    __tablename__ = 'configuracion_ranking'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, unique=True)
    peso_asistencia = db.Column(db.Float, nullable=False, default=30.0)
    peso_evidencias = db.Column(db.Float, nullable=False, default=40.0)
    peso_juicios = db.Column(db.Float, nullable=False, default=0.0)
    modo_visibilidad = db.Column(db.String(20), nullable=False, default='privado')
    modo_anonimo_parcial = db.Column(db.Boolean, nullable=False, default=False)
    periodo_corte = db.Column(db.String(20), nullable=False, default='trimestral')
    inicio_corte = db.Column(db.DateTime, nullable=True)
    bonus_entrega_anticipada = db.Column(db.Float, nullable=False, default=1.0)
    horas_entrega_anticipada = db.Column(db.Integer, nullable=False, default=24)
    bonus_racha_asistencia = db.Column(db.Float, nullable=False, default=3.0)
    semanas_racha = db.Column(db.Integer, nullable=False, default=4)
    bonus_calificacion_alta = db.Column(db.Float, nullable=False, default=1.0)
    umbral_calificacion_alta = db.Column(db.Float, nullable=False, default=4.0)
    penalizacion_falla_injustificada = db.Column(db.Float, nullable=False, default=1.0)
    actualizada_en = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PuntajeHistorico(db.Model):
    __tablename__ = 'puntajes_historicos'

    id = db.Column(db.Integer, primary_key=True)
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id'), nullable=False, index=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    fecha_corte = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    tipo_corte = db.Column(db.String(20), nullable=False, default='automatico')
    puntaje_total = db.Column(db.Float, nullable=False, default=0.0)
    puntaje_asistencia = db.Column(db.Float, nullable=False, default=0.0)
    puntaje_evidencias = db.Column(db.Float, nullable=False, default=0.0)
    puntaje_juicios = db.Column(db.Float, nullable=False, default=0.0)
    posicion = db.Column(db.Integer, nullable=False)

    aprendiz = db.relationship(
        'Aprendiz',
        backref=db.backref('puntajes_historicos', cascade='all, delete-orphan'),
    )
    ficha = db.relationship('Ficha', back_populates='puntajes_historicos')
