"""agrega ciclo de vida a los cortes

Revision ID: i30ciclo
Revises: h29corte
"""

from alembic import op
import sqlalchemy as sa


revision = 'i30ciclo'
down_revision = 'h29corte'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'cortes',
        sa.Column(
            'estado',
            sa.String(length=20),
            nullable=False,
            server_default='activo',
        ),
    )
    op.create_index('ix_cortes_estado', 'cortes', ['estado'], unique=False)
    op.execute(sa.text(
        "UPDATE cortes SET estado = 'cerrado' WHERE fecha_fin IS NOT NULL"
    ))


def downgrade():
    op.drop_index('ix_cortes_estado', table_name='cortes')
    op.drop_column('cortes', 'estado')
