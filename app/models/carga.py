"""Sesiones de transferencia y confirmaciones durables de formularios."""

from app import db
from app.helpers import utc_now


class CargaArchivo(db.Model):
    __tablename__ = 'cargas_archivos'
    id = db.Column(db.String(32), primary_key=True)
    propietario = db.Column(db.String(80), nullable=False, index=True)
    destino = db.Column(db.String(500), nullable=False)
    campo = db.Column(db.String(80), nullable=False)
    nombre = db.Column(db.String(255), nullable=False)
    tipo = db.Column(db.String(150), nullable=False)
    tamano = db.Column(db.BigInteger, nullable=False)
    offset = db.Column(db.BigInteger, nullable=False, default=0)
    bloque_bytes = db.Column(db.Integer, nullable=False)
    estado = db.Column(db.String(30), nullable=False, default='subiendo', index=True)
    huellas = db.Column(db.JSON, nullable=False, default=list)
    hash_sha256 = db.Column(db.String(64))
    vence_en = db.Column(db.DateTime, nullable=False, index=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=utc_now)
    envio_id = db.Column(db.String(100), db.ForeignKey('cargas_envios.id'), index=True)


class EnvioCarga(db.Model):
    __tablename__ = 'cargas_envios'
    id = db.Column(db.String(100), primary_key=True)
    propietario = db.Column(db.String(80), nullable=False, index=True)
    destino = db.Column(db.String(500), nullable=False)
    endpoint = db.Column(db.String(100), nullable=False)
    argumentos = db.Column(db.JSON, nullable=False, default=dict)
    referencias = db.Column(db.JSON, nullable=False)
    campos = db.Column(db.JSON, nullable=False, default=dict)
    estado = db.Column(db.String(30), nullable=False, default='confirmando', index=True)
    resultado = db.Column(db.JSON)
    creado_en = db.Column(db.DateTime, nullable=False, default=utc_now)
    iniciado_en = db.Column(db.DateTime)
    lease_hasta = db.Column(db.DateTime, index=True)
    intentos = db.Column(db.Integer, nullable=False, default=0)
    datos_confirmados = db.Column(db.Boolean, nullable=False, default=False)
