"""fichas competencias seleccionadas por instructor

Revision ID: g18c9e4088ef
Revises: f73a1c8d5b40
Create Date: 2026-07-30 11:15:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'g18c9e4088ef'
down_revision = 'c83d1e7f4a92'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fichas_competencias_seleccionadas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('competencia', sa.String(length=300), nullable=False),
        sa.Column('instructor_id', sa.Integer(), nullable=False),
        sa.Column('fecha_seleccion', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.ForeignKeyConstraint(['instructor_id'], ['instructores.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ficha_id', 'competencia', name='uq_ficha_competencia_sel')
    )
    with op.batch_alter_table('fichas_competencias_seleccionadas', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_fichas_competencias_seleccionadas_ficha_id'),
            ['ficha_id'],
            unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_fichas_competencias_seleccionadas_instructor_id'),
            ['instructor_id'],
            unique=False
        )


def downgrade():
    with op.batch_alter_table('fichas_competencias_seleccionadas', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_fichas_competencias_seleccionadas_instructor_id'))
        batch_op.drop_index(batch_op.f('ix_fichas_competencias_seleccionadas_ficha_id'))
    op.drop_table('fichas_competencias_seleccionadas')
