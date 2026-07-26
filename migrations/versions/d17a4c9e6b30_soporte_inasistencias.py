"""soporte documental para inasistencias

Revision ID: d17a4c9e6b30
Revises: c46e91a8d5f2
Create Date: 2026-07-24 01:30:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'd17a4c9e6b30'
down_revision = 'c46e91a8d5f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('registros_asistencia', schema=None) as batch_op:
        batch_op.add_column(sa.Column('soporte_url', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('registros_asistencia', schema=None) as batch_op:
        batch_op.drop_column('soporte_url')

