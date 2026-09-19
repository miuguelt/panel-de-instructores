"""delegación operativa para un aprendiz por ficha

Revision ID: l33aprendizadmin
Revises: k32archivos
Create Date: 2026-09-10 00:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'l33aprendizadmin'
down_revision = 'k32archivos'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('aprendices', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'rol_administrativo',
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )


def downgrade():
    with op.batch_alter_table('aprendices', schema=None) as batch_op:
        batch_op.drop_column('rol_administrativo')
