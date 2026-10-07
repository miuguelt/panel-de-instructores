"""Preferencias y foto privadas del panel del aprendiz con revisión de concurrencia."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'q40personalizacionaprendiz'
down_revision = 'p39portafolioaprendiz'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'personalizaciones_aprendiz',
        sa.Column('aprendiz_id', sa.Integer(), nullable=False),
        sa.Column('preferencias', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=False),
        sa.Column('foto', sa.LargeBinary(), nullable=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.CheckConstraint('revision >= 1', name='ck_personalizacion_revision_positiva'),
        sa.ForeignKeyConstraint(['aprendiz_id'], ['aprendices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('aprendiz_id'),
    )


def downgrade():
    op.drop_table('personalizaciones_aprendiz')
