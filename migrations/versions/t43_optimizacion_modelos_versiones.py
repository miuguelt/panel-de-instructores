"""Optimizacion de modelos y versionamiento: indices y check constraints

Revision ID: t43optimizacionmodelos
Revises: s42competenciasprogramacion
Create Date: 2026-10-10 15:50:00

"""
from alembic import op
import sqlalchemy as sa


revision = 't43optimizacionmodelos'
down_revision = 's42competenciasprogramacion'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Agregar columna de observación pedagógica en programación de competencias
    op.add_column(
        'fichas_competencias_programacion',
        sa.Column('observacion', sa.Text(), nullable=True)
    )

    # 2. Agregar CheckConstraint para garantizar integridad temporal (fecha_fin >= fecha_inicio)
    op.create_check_constraint(
        'ck_ficha_comp_prog_fechas',
        'fichas_competencias_programacion',
        'fecha_fin IS NULL OR fecha_inicio IS NULL OR fecha_fin >= fecha_inicio'
    )

    # 3. Índice compuesto de cobertura para recuperación rápida de la versión activa de archivos
    op.create_index(
        'ix_archivos_ficha_lookup_version',
        'archivos_ficha_versiones',
        ['ficha_id', 'tipo', 'estado', 'version'],
        unique=False
    )


def downgrade():
    op.drop_index('ix_archivos_ficha_lookup_version', table_name='archivos_ficha_versiones')
    op.drop_constraint('ck_ficha_comp_prog_fechas', 'fichas_competencias_programacion', type_='check')
    op.drop_column('fichas_competencias_programacion', 'observacion')
