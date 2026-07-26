from datetime import datetime

from app import db


class ConfiguracionAlertas(db.Model):
    __tablename__ = 'configuracion_alertas'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, unique=True)
    umbral_amarillo = db.Column(db.Integer, default=3)
    umbral_rojo = db.Column(db.Integer, default=6)
    max_fallas_trimestre_laboral = db.Column(db.Integer, default=3)


class ConfiguracionAlertasComite(db.Model):
    __tablename__ = 'configuracion_alertas_comite'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, unique=True)

    # --- Valores fijados por Resolución 009 de 2024 ---
    umbral_fallas_consecutivas = db.Column(db.Integer, nullable=False, default=3)
    umbral_fallas_acumuladas = db.Column(db.Integer, nullable=False, default=5)
    umbral_fallas_esporadicas = db.Column(db.Integer, nullable=False, default=5)
    periodo_dias_esporadicas = db.Column(db.Integer, nullable=False, default=90)
    umbral_tareas_incumplidas = db.Column(db.Integer, nullable=False, default=3)
    dias_plazo_justificacion = db.Column(db.Integer, nullable=False, default=2)

    # --- Nuevos campos Resolución 009 ---
    porcentaje_minimo_asistencia = db.Column(db.Integer, nullable=False, default=75)
    auto_escalar_dias = db.Column(db.Integer, nullable=False, default=15)

    correo_habilitado = db.Column(db.Boolean, nullable=False, default=False)
    actualizada_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                               onupdate=datetime.utcnow)


class Alerta(db.Model):
    __tablename__ = 'alertas'

    id = db.Column(db.Integer, primary_key=True)
    # Puede ser una alerta individual o un aviso general del cronograma de la ficha.
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id'), nullable=True, index=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    tipo = db.Column(db.String(30), nullable=False, default='asistencia')
    nivel = db.Column(db.String(20), nullable=False, default='amarilla')
    titulo = db.Column(db.String(180), nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    detalle_json = db.Column(db.JSON, nullable=True)
    fecha_generada = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    estado = db.Column(db.String(30), nullable=False, default='activa', index=True)
    observaciones = db.Column(db.Text, nullable=True)
    fecha_resuelta = db.Column(db.DateTime, nullable=True)
    resuelta_por = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=True)
    fecha_escalada = db.Column(db.DateTime, nullable=True)
    escalada_por = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=True)
    auto_escalada = db.Column(db.Boolean, nullable=False, default=False)
    fecha_ultima_evaluacion = db.Column(db.DateTime, nullable=True)

    aprendiz = db.relationship('Aprendiz', backref=db.backref('alertas', lazy='dynamic'))
    ficha = db.relationship('Ficha', backref=db.backref('alertas', lazy='dynamic'))


class Notificacion(db.Model):
    __tablename__ = 'notificaciones'

    id = db.Column(db.Integer, primary_key=True)
    destinatario_tipo = db.Column(db.String(20), nullable=False, index=True)
    destinatario_id = db.Column(db.Integer, nullable=False, index=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=True, index=True)
    mensaje = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(40), nullable=False, default='general')
    url = db.Column(db.String(500), nullable=True)
    clave = db.Column(db.String(180), nullable=False)
    fecha_creada = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    leida = db.Column(db.Boolean, nullable=False, default=False, index=True)
    leida_en = db.Column(db.DateTime, nullable=True)

    ficha = db.relationship('Ficha', backref=db.backref('notificaciones', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('destinatario_tipo', 'destinatario_id', 'clave',
                            name='uq_notificacion_destinatario_clave'),
    )


class PlanMejoramiento(db.Model):
    __tablename__ = 'planes_mejoramiento'

    id = db.Column(db.Integer, primary_key=True)
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id'), nullable=False, index=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    alerta_id = db.Column(db.Integer, db.ForeignKey('alertas.id'), nullable=True)
    fecha_creacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    fecha_limite = db.Column(db.DateTime, nullable=True)
    fecha_cumplimiento = db.Column(db.DateTime, nullable=True)
    actividades = db.Column(db.Text, nullable=False)
    estado = db.Column(db.String(20), nullable=False, default='pendiente', index=True)
    observaciones_instructor = db.Column(db.Text, nullable=True)
    observaciones_aprendiz = db.Column(db.Text, nullable=True)
    creado_por = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=True)

    aprendiz = db.relationship('Aprendiz', backref=db.backref('planes_mejoramiento', lazy='dynamic'))
    ficha = db.relationship('Ficha', backref=db.backref('planes_mejoramiento', lazy='dynamic'))
    alerta = db.relationship('Alerta', backref=db.backref('planes_mejoramiento', lazy='dynamic'))
