"""asigna cada tarea al instructor que la creó

Revision ID: c7d9e1f2a3b4
Revises: a4ad8b8ede5f
"""

from alembic import op
import sqlalchemy as sa


revision = 'c7d9e1f2a3b4'
down_revision = 'a4ad8b8ede5f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tareas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('instructor_id', sa.Integer(), nullable=True))

    # Las tareas históricas quedan a cargo del instructor responsable de su ficha.
    op.execute(
        sa.text(
            'UPDATE tareas '
            'SET instructor_id = ('
            '    SELECT fichas.instructor_id '
            '    FROM fichas '
            '    WHERE fichas.id = tareas.ficha_id'
            ') '
            'WHERE instructor_id IS NULL'
        )
    )

    with op.batch_alter_table('tareas', schema=None) as batch_op:
        batch_op.alter_column(
            'instructor_id',
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_foreign_key(
            'fk_tareas_instructor_id_instructores',
            'instructores',
            ['instructor_id'],
            ['id'],
        )
        batch_op.create_index('ix_tareas_instructor_id', ['instructor_id'], unique=False)


def downgrade():
    with op.batch_alter_table('tareas', schema=None) as batch_op:
        batch_op.drop_index('ix_tareas_instructor_id')
        batch_op.drop_constraint('fk_tareas_instructor_id_instructores', type_='foreignkey')
        batch_op.drop_column('instructor_id')
