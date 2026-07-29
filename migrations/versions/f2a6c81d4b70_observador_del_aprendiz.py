"""bitacora del observador del aprendiz

Revision ID: f2a6c81d4b70
Revises: e18b3c7a5d92
"""

from alembic import op
import sqlalchemy as sa


revision = 'f2a6c81d4b70'
down_revision = 'e18b3c7a5d92'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notas_observador',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('aprendiz_id', sa.Integer(), nullable=False),
        sa.Column('instructor_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('categoria', sa.String(length=30), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('creada_en', sa.DateTime(), nullable=False),
        sa.Column('actualizada_en', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['aprendiz_id'], ['aprendices.id'],
                                name='fk_notas_observador_aprendiz_id_aprendices'),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id'],
                                name='fk_notas_observador_ficha_id_fichas'),
        sa.ForeignKeyConstraint(['instructor_id'], ['instructores.id'],
                                name='fk_notas_observador_instructor_id_instructores'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('notas_observador', schema=None) as batch_op:
        batch_op.create_index('ix_notas_observador_ficha_id', ['ficha_id'], unique=False)
        batch_op.create_index('ix_notas_observador_aprendiz_id', ['aprendiz_id'], unique=False)
        batch_op.create_index('ix_notas_observador_instructor_id', ['instructor_id'], unique=False)
        batch_op.create_index('ix_notas_observador_tipo', ['tipo'], unique=False)
        batch_op.create_index('ix_notas_observador_fecha', ['fecha'], unique=False)


def downgrade():
    with op.batch_alter_table('notas_observador', schema=None) as batch_op:
        batch_op.drop_index('ix_notas_observador_fecha')
        batch_op.drop_index('ix_notas_observador_tipo')
        batch_op.drop_index('ix_notas_observador_instructor_id')
        batch_op.drop_index('ix_notas_observador_aprendiz_id')
        batch_op.drop_index('ix_notas_observador_ficha_id')
    op.drop_table('notas_observador')
