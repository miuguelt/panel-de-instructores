"""Agrega el campo activo a la tabla aprendices para permitir deshabilitar aprendices de ranking y aseo.

Revision ID: c8e3f2b1a950
Revises: b7f2c1d9a640
Create Date: 2026-09-30 17:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8e3f2b1a950'
down_revision = 'b7f2c1d9a640'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('aprendices', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'activo',
                sa.Boolean(),
                server_default=sa.true(),
                nullable=False,
            )
        )


def downgrade():
    with op.batch_alter_table('aprendices', schema=None) as batch_op:
        batch_op.drop_column('activo')
