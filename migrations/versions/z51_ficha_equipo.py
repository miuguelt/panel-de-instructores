"""fichas: equipo ejecutor explícito, inicializado con el equipo del responsable

Revision ID: z51fichaequipo
Revises: z50coordinacionequipos
Create Date: 2026-11-24 09:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'z51fichaequipo'
down_revision = 'z50coordinacionequipos'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('fichas') as batch:
        batch.add_column(sa.Column('equipo_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_ficha_equipo', 'equipos_ejecutores', ['equipo_id'], ['id'],
                                 ondelete='SET NULL')
        batch.create_index('ix_fichas_equipo_id', ['equipo_id'])
    op.execute(
        'UPDATE fichas SET equipo_id = '
        '(SELECT instructores.equipo_id FROM instructores WHERE instructores.id = fichas.instructor_id)'
    )


def downgrade():
    with op.batch_alter_table('fichas') as batch:
        batch.drop_index('ix_fichas_equipo_id')
        batch.drop_constraint('fk_ficha_equipo', type_='foreignkey')
        batch.drop_column('equipo_id')
