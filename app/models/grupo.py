from app.helpers import utc_now
from app import db


tarea_grupo = db.Table(
    'tarea_grupo',
    db.Column(
        'tarea_id',
        db.Integer,
        db.ForeignKey('tareas.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    db.Column(
        'grupo_id',
        db.Integer,
        db.ForeignKey('grupos.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    db.Index('ix_tarea_grupo_grupo_id', 'grupo_id'),
)


class Grupo(db.Model):
    __tablename__ = 'grupos'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False)
    creado_en = db.Column(db.DateTime, nullable=False, default=utc_now)
    activo = db.Column(db.Boolean, nullable=False, default=True)

    # Relaciones
    ficha = db.relationship('Ficha', backref=db.backref('grupos', lazy='dynamic', cascade='all, delete-orphan'))
    aprendices = db.relationship('Aprendiz', secondary='grupo_aprendiz', backref=db.backref('grupos_asignados', lazy='dynamic'))
    tareas_grupales = db.relationship(
        'Tarea', secondary=tarea_grupo, back_populates='grupos'
    )
    mensajes = db.relationship(
        'GrupoMensaje',
        back_populates='grupo',
        lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='GrupoMensaje.creado_en, GrupoMensaje.id',
    )


class GrupoAprendiz(db.Model):
    __tablename__ = 'grupo_aprendiz'

    grupo_id = db.Column(db.Integer, db.ForeignKey('grupos.id', ondelete='CASCADE'), primary_key=True)
    aprendiz_id = db.Column(db.Integer, db.ForeignKey('aprendices.id', ondelete='CASCADE'), primary_key=True)
    asignado_en = db.Column(db.DateTime, nullable=False, default=utc_now)


class GrupoMensaje(db.Model):
    """Mensaje persistente que pueden consultar los integrantes del grupo."""

    __tablename__ = 'grupo_mensajes'

    id = db.Column(db.Integer, primary_key=True)
    grupo_id = db.Column(
        db.Integer,
        db.ForeignKey('grupos.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    aprendiz_id = db.Column(
        db.Integer,
        db.ForeignKey('aprendices.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    contenido = db.Column(db.Text, nullable=False)
    creado_en = db.Column(db.DateTime, nullable=False, default=utc_now)

    grupo = db.relationship('Grupo', back_populates='mensajes')
    aprendiz = db.relationship(
        'Aprendiz',
        backref=db.backref('mensajes_grupo', lazy='dynamic'),
    )

    __table_args__ = (
        db.Index('ix_grupo_mensajes_grupo_fecha', 'grupo_id', 'creado_en', 'id'),
    )
