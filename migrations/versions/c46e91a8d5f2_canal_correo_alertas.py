"""canal de correo opcional para alertas

Revision ID: c46e91a8d5f2
Revises: b31d6f7e2c44
Create Date: 2026-07-24 01:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'c46e91a8d5f2'
down_revision = 'b31d6f7e2c44'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('aprendices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('correo', sa.String(length=150), nullable=True))
    with op.batch_alter_table('configuracion_alertas_comite', schema=None) as batch_op:
        batch_op.add_column(sa.Column('correo_habilitado', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade():
    with op.batch_alter_table('configuracion_alertas_comite', schema=None) as batch_op:
        batch_op.drop_column('correo_habilitado')
    with op.batch_alter_table('aprendices', schema=None) as batch_op:
        batch_op.drop_column('correo')

