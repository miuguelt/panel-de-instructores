"""tracking por persona en turnos de aseo

Revision ID: b2e8f1a3c5d7
Revises: a19c7e4d5f60
Create Date: 2026-07-24 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'b2e8f1a3c5d7'
down_revision = 'a19c7e4d5f60'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('turnos_aseo', schema=None) as batch_op:
        batch_op.add_column(sa.Column('completado_1', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('completado_2', sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table('turnos_aseo', schema=None) as batch_op:
        batch_op.drop_column('completado_2')
        batch_op.drop_column('completado_1')
