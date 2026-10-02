"""Lecturas derivadas reutilizables por ficha y fecha de corte."""

from app import db
from app.helpers import utc_now
from app.models.archivo_ficha import TIPO_JSON_ESTRUCTURADO


class ResultadoCalculadoFicha(db.Model):
    """Snapshot JSON de una vista derivada a partir de fuentes versionadas."""

    __tablename__ = 'resultados_calculados_ficha'

    id = db.Column(db.Integer, primary_key=True)
    ficha_id = db.Column(
        db.Integer, db.ForeignKey('fichas.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    tipo = db.Column(db.String(40), nullable=False)
    fecha_corte = db.Column(db.Date, nullable=False)
    revision_calculo = db.Column(db.Integer, nullable=False)
    version_algoritmo = db.Column(db.String(40), nullable=False)
    huella_fuentes = db.Column(db.String(64), nullable=False)
    payload_json = db.Column(TIPO_JSON_ESTRUCTURADO, nullable=False)
    creado_en = db.Column(db.DateTime, nullable=False, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint(
            'ficha_id', 'tipo', 'fecha_corte', 'revision_calculo',
            'version_algoritmo', 'huella_fuentes',
            name='uq_resultado_calculado_ficha_revision',
        ),
        db.Index(
            'ix_resultado_calculado_busqueda',
            'ficha_id', 'tipo', 'fecha_corte', 'revision_calculo',
        ),
    )
