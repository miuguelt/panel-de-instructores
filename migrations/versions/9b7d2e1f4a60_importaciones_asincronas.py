"""cola durable para importaciones de reportes Excel

Revision ID: 9b7d2e1f4a60
Revises: f73a1c8d5b40
Create Date: 2026-07-29 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '9b7d2e1f4a60'
down_revision = 'c9e7a1b4d2f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'importaciones_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('instructor_id', sa.Integer(), nullable=False),
        sa.Column('archivo_path', sa.String(length=500), nullable=False),
        sa.Column('nombre_archivo', sa.String(length=255), nullable=False),
        sa.Column('estado', sa.String(length=20), nullable=False),
        sa.Column('resultado', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('iniciado_en', sa.DateTime(), nullable=True),
        sa.Column('terminado_en', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.ForeignKeyConstraint(['instructor_id'], ['instructores.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('importaciones_jobs') as batch_op:
        batch_op.create_index('ix_importaciones_jobs_ficha_id', ['ficha_id'])
        batch_op.create_index('ix_importaciones_jobs_instructor_id', ['instructor_id'])
        batch_op.create_index('ix_importaciones_jobs_estado', ['estado'])


def downgrade():
    op.drop_table('importaciones_jobs')
