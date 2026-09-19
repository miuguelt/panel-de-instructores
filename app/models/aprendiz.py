from app import db
import re
import unicodedata


# Estados que cuentan como "en formacion": unicos habilitados para llamado a
# lista, turnos de aseo y ranking.
ESTADOS_EN_FORMACION = ('EN', 'EN_FORMACION')

# Estados que deben conservarse en la lectura académica de la planeación.
# Esta lista es deliberadamente explícita: si el reporte oficial incorpora un
# estado nuevo, una prueba debe obligar a decidir si entra o no en el avance.
ESTADOS_PLANEACION = (
    'EN',
    'EN_FORMACION',
    'INDUCCION',
    'CONDICIONADO',
    'POR_CERTIFICAR',
    'CERTIFICADO',
    'APLAZADO',
)

# Estados que todavía pueden recibir o cerrar resultados en el seguimiento.
# Certificado y Aplazado se conservan en el análisis histórico, pero no se
# presentan como aprendices actualmente activos.
ESTADOS_PLANEACION_ACTIVOS = (
    'EN',
    'EN_FORMACION',
    'INDUCCION',
    'CONDICIONADO',
    'POR_CERTIFICAR',
)

# Los condicionados siguen asistiendo a clase: entran al llamado a lista,
# aunque no cuentan como "en formacion" para ranking, aseo ni alertas.
ESTADOS_LLAMADO_LISTA = ESTADOS_EN_FORMACION + ('CONDICIONADO',)

# Etiquetas legibles para los estados que trae el reporte oficial de SENA.
ETIQUETAS_ESTADO = {
    'EN': 'En formación',
    'EN_FORMACION': 'En formación',
    'INDUCCION': 'Inducción',
    'CONDICIONADO': 'Condicionado',
    'POR_CERTIFICAR': 'Por certificar',
    'CERTIFICADO': 'Certificado',
    'RETIRO_VOLUNTARIO': 'Retiro voluntario',
    'RETIRADO': 'Retirado',
    'CANCELADO': 'Cancelado',
    'APLAZADO': 'Aplazado',
    'EN_APLAZAMIENTO': 'En aplazamiento',
}

# Tono de badge por estado para las vistas de gestion.
TONOS_ESTADO = {
    'EN': 'success',
    'EN_FORMACION': 'success',
    'INDUCCION': 'info',
    'CONDICIONADO': 'warning',
    'POR_CERTIFICAR': 'info',
    'CERTIFICADO': 'success',
    'RETIRO_VOLUNTARIO': 'danger',
    'RETIRADO': 'danger',
    'CANCELADO': 'danger',
    'APLAZADO': 'secondary',
    'EN_APLAZAMIENTO': 'secondary',
}


def normalizar_estado(estado):
    """Normaliza estados del Excel y de registros antiguos para compararlos."""
    texto = unicodedata.normalize('NFKD', str(estado or '').strip())
    texto = ''.join(caracter for caracter in texto if not unicodedata.combining(caracter))
    return re.sub(r'[^A-Z0-9]+', '_', texto.upper()).strip('_')


def etiqueta_estado(estado):
    """Convierte el estado tecnico en un texto legible para la UI."""
    if not estado:
        return 'Sin estado'
    normalizado = normalizar_estado(estado)
    return ETIQUETAS_ESTADO.get(normalizado, normalizado.replace('_', ' ').title())


def tono_estado(estado):
    """Devuelve la clase de badge adecuada para el estado del aprendiz."""
    return TONOS_ESTADO.get(normalizar_estado(estado), 'secondary')


class Aprendiz(db.Model):
    __tablename__ = 'aprendices'

    id = db.Column(db.Integer, primary_key=True)
    documento = db.Column(db.String(20), nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False)
    apellidos = db.Column(db.String(150), nullable=False)
    tipo_documento = db.Column(db.String(5), default='CC')
    correo = db.Column(db.String(150), nullable=True)
    estado = db.Column(db.String(20), default='EN_FORMACION')
    # Este rol es deliberadamente independiente del usuario instructor. Solo
    # habilita operaciones operativas acotadas dentro de la ficha.
    rol_administrativo = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false()
    )
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

    @classmethod
    def query_llamado_lista(cls, ficha_id):
        """Query de aprendices que participan en el llamado a lista:
        en formacion y condicionados (siguen asistiendo a clase)."""
        return cls.query.filter(
            cls.ficha_id == ficha_id,
            cls.estado.in_(ESTADOS_LLAMADO_LISTA),
        )

    @property
    def en_formacion(self):
        return self.estado in ESTADOS_EN_FORMACION

    @property
    def es_aprendiz_administrador(self):
        """Indica si el aprendiz tiene herramientas operativas delegadas."""
        return bool(self.rol_administrativo)

    @property
    def estado_normalizado(self):
        return normalizar_estado(self.estado)

    @property
    def incluido_en_planeacion(self):
        return self.estado_normalizado in ESTADOS_PLANEACION

    @property
    def activo_en_planeacion(self):
        return self.estado_normalizado in ESTADOS_PLANEACION_ACTIVOS

    @property
    def nombre_completo(self):
        return f'{self.nombre} {self.apellidos}'

    def __repr__(self):
        return f'<Aprendiz {self.documento} - {self.nombre} {self.apellidos}>'
