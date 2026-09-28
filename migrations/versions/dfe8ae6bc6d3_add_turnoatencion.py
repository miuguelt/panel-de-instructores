"""Add TurnoAtencion

Revision ID: dfe8ae6bc6d3
Revises: 8830d1d5813e
Create Date: 2026-09-25 16:24:50.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'dfe8ae6bc6d3'
down_revision = '8830d1d5813e'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('turnos_atencion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ficha_id', sa.Integer(), nullable=False),
    sa.Column('aprendiz_id', sa.Integer(), nullable=False),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.Column('motivo', sa.String(length=255), nullable=True),
    sa.Column('creado_en', sa.DateTime(), nullable=False),
    sa.Column('atendido_en', sa.DateTime(), nullable=True),
    sa.Column('completado_en', sa.DateTime(), nullable=True),
    sa.CheckConstraint("estado IN ('esperando', 'en_atencion', 'atendido', 'cancelado', 'ausente')", name='ck_estado_turno_atencion'),
    sa.ForeignKeyConstraint(['aprendiz_id'], ['aprendices.id'], ),
    sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('turnos_atencion', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_turnos_atencion_aprendiz_id'), ['aprendiz_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_turnos_atencion_ficha_id'), ['ficha_id'], unique=False)

def downgrade():
    with op.batch_alter_table('turnos_atencion', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_turnos_atencion_ficha_id'))
        batch_op.drop_index(batch_op.f('ix_turnos_atencion_aprendiz_id'))
    op.drop_table('turnos_atencion')
