"""modalidad de tarea, auditoria de edicion y aprobacion de actividades de aula

Revision ID: e18b3c7a5d92
Revises: 9b7d2e1f4a60
"""

from alembic import op
import sqlalchemy as sa


revision = 'e18b3c7a5d92'
down_revision = '9b7d2e1f4a60'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tareas', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'modalidad',
                sa.String(length=20),
                nullable=False,
                server_default='evidencia',
            )
        )
        batch_op.add_column(sa.Column('actualizada_en', sa.DateTime(), nullable=True))

    with op.batch_alter_table('entregas', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'registrada_por_instructor',
                sa.Boolean(),
                nullable=False,
                # `sa.false()` se traduce a FALSE en PostgreSQL y a 0 en
                # SQLite; un literal '0' rompe el ALTER en PostgreSQL.
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column('revisada_por_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_entregas_revisada_por_id_instructores',
            'instructores',
            ['revisada_por_id'],
            ['id'],
        )
        batch_op.create_index(
            'ix_entregas_revisada_por_id', ['revisada_por_id'], unique=False
        )


def downgrade():
    with op.batch_alter_table('entregas', schema=None) as batch_op:
        batch_op.drop_index('ix_entregas_revisada_por_id')
        batch_op.drop_constraint(
            'fk_entregas_revisada_por_id_instructores', type_='foreignkey'
        )
        batch_op.drop_column('revisada_por_id')
        batch_op.drop_column('registrada_por_instructor')

    with op.batch_alter_table('tareas', schema=None) as batch_op:
        batch_op.drop_column('actualizada_en')
        batch_op.drop_column('modalidad')
