"""marca de cambio obligatorio de contrasena para instructores

Revision ID: v46cambiopassword
Revises: u45avisospush
Create Date: 2026-10-27 15:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'v46cambiopassword'
down_revision = 'u45avisospush'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('instructores', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'debe_cambiar_password',
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )


def downgrade():
    with op.batch_alter_table('instructores', schema=None) as batch_op:
        batch_op.drop_column('debe_cambiar_password')
