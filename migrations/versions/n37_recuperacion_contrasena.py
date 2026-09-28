"""Add one-time password recovery state and session versioning."""

from alembic import op
import sqlalchemy as sa


revision = 'n37passwordreset'
down_revision = 'm36indicesfrecuentes'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'instructores',
        sa.Column('auth_version', sa.Integer(), server_default='1', nullable=False),
    )
    op.add_column(
        'instructores',
        sa.Column('password_reset_token_hash', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'instructores',
        sa.Column('password_reset_expires_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'ix_instructores_password_reset_token_hash',
        'instructores',
        ['password_reset_token_hash'],
        unique=True,
    )


def downgrade():
    op.drop_index(
        'ix_instructores_password_reset_token_hash', table_name='instructores'
    )
    op.drop_column('instructores', 'password_reset_expires_at')
    op.drop_column('instructores', 'password_reset_token_hash')
    op.drop_column('instructores', 'auth_version')
