"""Agregar enlaces de GitHub y Notion al modelo Aprendiz."""

from alembic import op
import sqlalchemy as sa


revision = 'p39portafolioaprendiz'
down_revision = 'o38persistirdocumentos'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'aprendices',
        sa.Column('enlace_github', sa.String(length=500), nullable=True),
    )
    op.add_column(
        'aprendices',
        sa.Column('enlace_notion', sa.String(length=500), nullable=True),
    )


def downgrade():
    op.drop_column('aprendices', 'enlace_notion')
    op.drop_column('aprendices', 'enlace_github')
