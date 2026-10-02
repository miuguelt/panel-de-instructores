"""Persist document extraction and revisioned analytical snapshots."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


TIPO_JSON_ESTRUCTURADO = sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')


revision = 'o38persistirdocumentos'
down_revision = 'c8e3f2b1a950'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'importaciones_jobs',
        sa.Column('tipo_trabajo', sa.String(length=30), server_default='importar_reporte', nullable=False),
    )
    op.add_column(
        'archivos_ficha_versiones',
        sa.Column('contenido_extraido_json', TIPO_JSON_ESTRUCTURADO, nullable=True),
    )
    op.add_column(
        'archivos_ficha_versiones',
        sa.Column('contenido_extraido_version', sa.String(length=40), nullable=True),
    )
    op.add_column(
        'fichas',
        sa.Column('revision_calculos', sa.Integer(), server_default='1', nullable=False),
    )
    op.create_table(
        'resultados_calculados_ficha',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=40), nullable=False),
        sa.Column('fecha_corte', sa.Date(), nullable=False),
        sa.Column('revision_calculo', sa.Integer(), nullable=False),
        sa.Column('version_algoritmo', sa.String(length=40), nullable=False),
        sa.Column('huella_fuentes', sa.String(length=64), nullable=False),
        sa.Column('payload_json', TIPO_JSON_ESTRUCTURADO, nullable=False),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'ficha_id', 'tipo', 'fecha_corte', 'revision_calculo',
            'version_algoritmo', 'huella_fuentes',
            name='uq_resultado_calculado_ficha_revision',
        ),
    )
    op.create_index(
        'ix_resultados_calculados_ficha_id',
        'resultados_calculados_ficha', ['ficha_id'],
    )
    op.create_index(
        'ix_resultado_calculado_busqueda', 'resultados_calculados_ficha',
        ['ficha_id', 'tipo', 'fecha_corte', 'revision_calculo'],
    )


def downgrade():
    op.drop_index('ix_resultado_calculado_busqueda', table_name='resultados_calculados_ficha')
    op.drop_index('ix_resultados_calculados_ficha_id', table_name='resultados_calculados_ficha')
    op.drop_table('resultados_calculados_ficha')
    op.drop_column('importaciones_jobs', 'tipo_trabajo')
    op.drop_column('fichas', 'revision_calculos')
    op.drop_column('archivos_ficha_versiones', 'contenido_extraido_version')
    op.drop_column('archivos_ficha_versiones', 'contenido_extraido_json')
