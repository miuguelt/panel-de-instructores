"""fichas competencias programacion con fechas por instructor

Revision ID: s42competenciasprogramacion
Revises: r41experienciaaprendiz
Create Date: 2026-10-10 10:30:00

"""
from alembic import op
import sqlalchemy as sa


revision = 's42competenciasprogramacion'
down_revision = 'r41experienciaaprendiz'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fichas_competencias_programacion',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('competencia', sa.String(length=300), nullable=False),
        sa.Column('fecha_inicio', sa.Date(), nullable=True),
        sa.Column('fecha_fin', sa.Date(), nullable=True),
        sa.Column('instructor_id', sa.Integer(), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('actualizado_en', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['instructor_id'], ['instructores.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ficha_id', 'competencia', name='uq_ficha_comp_prog')
    )
    with op.batch_alter_table('fichas_competencias_programacion', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_fichas_competencias_programacion_ficha_id'),
            ['ficha_id'],
            unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_fichas_competencias_programacion_instructor_id'),
            ['instructor_id'],
            unique=False
        )


def downgrade():
    with op.batch_alter_table('fichas_competencias_programacion', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_fichas_competencias_programacion_instructor_id'))
        batch_op.drop_index(batch_op.f('ix_fichas_competencias_programacion_ficha_id'))
    op.drop_table('fichas_competencias_programacion')
