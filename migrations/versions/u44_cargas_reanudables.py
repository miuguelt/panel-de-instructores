"""Sesiones de carga reanudable y confirmaciones idempotentes."""

from alembic import op
import sqlalchemy as sa

revision = 'u44cargasreanudables'
down_revision = 't43optimizacionmodelos'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('cargas_envios',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('propietario', sa.String(80), nullable=False),
        sa.Column('destino', sa.String(500), nullable=False),
        sa.Column('endpoint', sa.String(100), nullable=False),
        sa.Column('argumentos', sa.JSON(), nullable=False),
        sa.Column('referencias', sa.JSON(), nullable=False),
        sa.Column('campos', sa.JSON(), nullable=False),
        sa.Column('estado', sa.String(30), nullable=False),
        sa.Column('resultado', sa.JSON()),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('iniciado_en', sa.DateTime()),
        sa.Column('lease_hasta', sa.DateTime()),
        sa.Column('intentos', sa.Integer(), nullable=False),
        sa.Column('datos_confirmados', sa.Boolean(), nullable=False))
    for columna in ('propietario', 'estado', 'lease_hasta'):
        op.create_index('ix_cargas_envios_' + columna, 'cargas_envios', [columna])
    op.create_table('cargas_archivos',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('propietario', sa.String(80), nullable=False),
        sa.Column('destino', sa.String(500), nullable=False),
        sa.Column('campo', sa.String(80), nullable=False),
        sa.Column('nombre', sa.String(255), nullable=False),
        sa.Column('tipo', sa.String(150), nullable=False),
        sa.Column('tamano', sa.BigInteger(), nullable=False),
        sa.Column('offset', sa.BigInteger(), nullable=False),
        sa.Column('bloque_bytes', sa.Integer(), nullable=False),
        sa.Column('estado', sa.String(30), nullable=False),
        sa.Column('huellas', sa.JSON(), nullable=False),
        sa.Column('hash_sha256', sa.String(64)),
        sa.Column('vence_en', sa.DateTime(), nullable=False),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('envio_id', sa.String(100), sa.ForeignKey('cargas_envios.id')))
    for columna in ('propietario', 'estado', 'vence_en', 'envio_id'):
        op.create_index('ix_cargas_archivos_' + columna, 'cargas_archivos', [columna])


def downgrade():
    op.drop_table('cargas_archivos')
    op.drop_table('cargas_envios')
