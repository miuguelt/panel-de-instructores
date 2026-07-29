"""evidencia documental de los planes de mejoramiento

Revision ID: c83d1e7f4a92
Revises: b5d3f8c17a24
"""

from alembic import op
import sqlalchemy as sa


revision = 'c83d1e7f4a92'
down_revision = 'b5d3f8c17a24'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('planes_mejoramiento', schema=None) as batch_op:
        batch_op.add_column(sa.Column('evidencia_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('evidencia_enviada_en', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('planes_mejoramiento', schema=None) as batch_op:
        batch_op.drop_column('evidencia_enviada_en')
        batch_op.drop_column('evidencia_url')
