"""ranking: agregar peso_juicios y puntaje_juicios

Revision ID: 6a9b8c5d3e2f
Revises: 5e17e5a4c24a
Create Date: 2026-07-24 01:30:00

"""
from alembic import op
import sqlalchemy as sa


revision = '6a9b8c5d3e2f'
down_revision = '5e17e5a4c24a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('configuracion_ranking', sa.Column('peso_juicios', sa.Float(), server_default='0', nullable=False))
    op.add_column('puntajes_historicos', sa.Column('puntaje_juicios', sa.Float(), server_default='0', nullable=False))


def downgrade():
    op.drop_column('puntajes_historicos', 'puntaje_juicios')
    op.drop_column('configuracion_ranking', 'peso_juicios')
