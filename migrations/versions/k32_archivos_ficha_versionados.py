"""Persist versions of planning and evaluation report files.

Revision ID: k32archivos
Revises: j31juicios
"""

from alembic import op
import sqlalchemy as sa


revision = 'k32archivos'
down_revision = 'j31juicios'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'archivos_ficha_versiones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('instructor_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=30), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('nombre_archivo', sa.String(length=255), nullable=False),
        sa.Column('ruta_archivo', sa.String(length=500), nullable=False),
        sa.Column('hash_sha256', sa.String(length=64), nullable=True),
        sa.Column('tamano_bytes', sa.Integer(), nullable=False),
        sa.Column('estado', sa.String(length=20), nullable=False),
        sa.Column('detalle', sa.Text(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.ForeignKeyConstraint(['instructor_id'], ['instructores.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ficha_id', 'tipo', 'version', name='uq_archivo_ficha_tipo_version'),
    )
    op.create_index('ix_archivos_ficha_versiones_ficha_id', 'archivos_ficha_versiones', ['ficha_id'])
    op.create_index('ix_archivos_ficha_versiones_instructor_id', 'archivos_ficha_versiones', ['instructor_id'])
    op.create_index('ix_archivos_ficha_versiones_tipo', 'archivos_ficha_versiones', ['tipo'])
    op.create_index('ix_archivos_ficha_versiones_hash_sha256', 'archivos_ficha_versiones', ['hash_sha256'])
    op.add_column(
        'importaciones_jobs',
        sa.Column('archivo_version_id', sa.Integer(), nullable=True),
    )
    op.create_index('ix_importaciones_jobs_archivo_version_id', 'importaciones_jobs', ['archivo_version_id'])
    op.create_foreign_key(
        'fk_importaciones_jobs_archivo_version',
        'importaciones_jobs',
        'archivos_ficha_versiones',
        ['archivo_version_id'],
        ['id'],
    )


def downgrade():
    op.drop_constraint('fk_importaciones_jobs_archivo_version', 'importaciones_jobs', type_='foreignkey')
    op.drop_index('ix_importaciones_jobs_archivo_version_id', table_name='importaciones_jobs')
    op.drop_column('importaciones_jobs', 'archivo_version_id')
    op.drop_index('ix_archivos_ficha_versiones_hash_sha256', table_name='archivos_ficha_versiones')
    op.drop_index('ix_archivos_ficha_versiones_tipo', table_name='archivos_ficha_versiones')
    op.drop_index('ix_archivos_ficha_versiones_instructor_id', table_name='archivos_ficha_versiones')
    op.drop_index('ix_archivos_ficha_versiones_ficha_id', table_name='archivos_ficha_versiones')
    op.drop_table('archivos_ficha_versiones')
