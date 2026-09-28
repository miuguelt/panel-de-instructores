from app import db
from datetime import datetime

ESTADOS_TURNO_ATENCION = ('esperando', 'en_atencion', 'atendido', 'cancelado', 'ausente')

class TurnoAtencion(db.Model):
    __tablename__ = 'turnos_atencion'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id'), nullable=False, index=True)
    
    estado = db.Column(db.String(20), nullable=False, default='esperando')
    motivo = db.Column(db.String(255), nullable=True) # De qué quiere hablar el aprendiz
    
    # Timestamps para métricas
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atendido_en = db.Column(db.DateTime, nullable=True)
    completado_en = db.Column(db.DateTime, nullable=True)

    # Relaciones
    aprendiz = db.relationship('Aprendiz', backref=db.backref('turnos_atencion', lazy='dynamic', cascade='all, delete-orphan'))
    # La ficha ya tiene backref via lazy='dynamic' si queremos, o usamos query explícita.

    __table_args__ = (
        db.CheckConstraint(f"estado IN {ESTADOS_TURNO_ATENCION}", name='ck_estado_turno_atencion'),
    )

    def __repr__(self):
        return f"<TurnoAtencion {self.id} - Ficha {self.ficha_id} - Aprendiz {self.aprendiz_id} - {self.estado}>"
