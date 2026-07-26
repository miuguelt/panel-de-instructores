"""permitir alertas generales de cronograma

Revision ID: a19c7e4d5f60
Revises: a14c9e7b2d60
"""
from alembic import op
import sqlalchemy as sa

revision = 'a19c7e4d5f60'
down_revision = 'a14c9e7b2d60'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('alertas', schema=None) as batch_op:
        batch_op.alter_column('aprendiz_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    with op.batch_alter_table('alertas', schema=None) as batch_op:
        batch_op.alter_column('aprendiz_id', existing_type=sa.Integer(), nullable=False)
