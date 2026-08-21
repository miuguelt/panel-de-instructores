from app.helpers import utc_now

from app import db


TIPO_PLANEACION = 'planeacion'
TIPO_REPORTE_JUICIOS = 'reporte_juicios'
TIPO_PROGRAMA = 'programa_formacion'

ETIQUETAS_TIPO = {
    TIPO_PLANEACION: 'Planeación pedagógica',
    TIPO_REPORTE_JUICIOS: 'Reporte de juicios evaluativos',
    TIPO_PROGRAMA: 'Programa de formación',
}


class ArchivoFichaVersion(db.Model):
    """Versión persistente de un archivo que alimenta el seguimiento de una ficha."""

    __tablename__ = 'archivos_ficha_versiones'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(db.Integer, db.ForeignKey('fichas.id'), nullable=False, index=True)
    instructor_id = db.Column(db.Integer, db.ForeignKey('instructores.id'), nullable=False, index=True)
    tipo = db.Column(db.String(30), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    nombre_archivo = db.Column(db.String(255), nullable=False)
    ruta_archivo = db.Column(db.String(500), nullable=False)
    hash_sha256 = db.Column(db.String(64), nullable=True, index=True)
    tamano_bytes = db.Column(db.Integer, nullable=False, default=0)
    estado = db.Column(db.String(20), nullable=False, default='procesado')
    detalle = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=utc_now)

    ficha = db.relationship('Ficha', back_populates='archivos_versionados')
    instructor = db.relationship('Instructor', backref=db.backref('archivos_ficha', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('ficha_id', 'tipo', 'version', name='uq_archivo_ficha_tipo_version'),
    )

