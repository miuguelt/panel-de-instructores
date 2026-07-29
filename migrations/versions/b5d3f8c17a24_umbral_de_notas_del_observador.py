"""umbral de llamados de atencion del observador

Revision ID: b5d3f8c17a24
Revises: f2a6c81d4b70
"""

from alembic import op
import sqlalchemy as sa


revision = 'b5d3f8c17a24'
down_revision = 'f2a6c81d4b70'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('configuracion_alertas_comite', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'umbral_notas_negativas',
                sa.Integer(),
                nullable=False,
                server_default='3',
            )
        )
        batch_op.add_column(
            sa.Column(
                'periodo_dias_notas',
                sa.Integer(),
                nullable=False,
                server_default='30',
            )
        )


def downgrade():
    with op.batch_alter_table('configuracion_alertas_comite', schema=None) as batch_op:
        batch_op.drop_column('periodo_dias_notas')
        batch_op.drop_column('umbral_notas_negativas')
