"""duración de etapa productiva para cronograma de ficha

Revision ID: f08b6d2c1e34
Revises: e42f7b1c9d20
"""
from alembic import op
import sqlalchemy as sa

revision = 'f08b6d2c1e34'
down_revision = 'e42f7b1c9d20'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('fichas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('duracion_productiva_meses', sa.Integer(), nullable=False, server_default='6'))


def downgrade():
    with op.batch_alter_table('fichas', schema=None) as batch_op:
        batch_op.drop_column('duracion_productiva_meses')
