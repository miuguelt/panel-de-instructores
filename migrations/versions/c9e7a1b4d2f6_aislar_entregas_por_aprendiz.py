"""garantiza una sola evidencia por tarea y aprendiz

Revision ID: c9e7a1b4d2f6
Revises: c7d9e1f2a3b4
"""

from alembic import op
import sqlalchemy as sa


revision = 'c9e7a1b4d2f6'
down_revision = 'c7d9e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    # Conserva la entrega más reciente por pareja tarea-aprendiz antes de
    # crear la restricción. Así los datos históricos no vuelven ambiguo el
    # enlace que se muestra al instructor.
    op.execute(sa.text(
        """
        DELETE FROM entregas
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY tarea_id, aprendiz_id
                        ORDER BY
                            CASE WHEN fecha_entrega IS NULL THEN 1 ELSE 0 END,
                            fecha_entrega DESC,
                            id DESC
                    ) AS fila
                FROM entregas
            ) repetidas
            WHERE fila > 1
        )
        """
    ))

    with op.batch_alter_table('entregas', schema=None) as batch_op:
        batch_op.create_index(
            'ix_entregas_aprendiz_id',
            ['aprendiz_id'],
            unique=False,
        )
        batch_op.create_unique_constraint(
            'uq_entrega_tarea_aprendiz',
            ['tarea_id', 'aprendiz_id'],
        )


def downgrade():
    with op.batch_alter_table('entregas', schema=None) as batch_op:
        batch_op.drop_constraint('uq_entrega_tarea_aprendiz', type_='unique')
        batch_op.drop_index('ix_entregas_aprendiz_id')
