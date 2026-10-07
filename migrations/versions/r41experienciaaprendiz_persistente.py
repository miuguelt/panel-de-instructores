"""Preferencias de experiencia e hitos permanentes del aprendiz."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'r41experienciaaprendiz'
down_revision = 'q40personalizacionaprendiz'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'experiencias_aprendiz',
        sa.Column('aprendiz_id', sa.Integer(), nullable=False),
        sa.Column('preferences', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('logros', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=False),
        sa.CheckConstraint('revision >= 1', name='ck_experiencia_revision_positiva'),
        sa.ForeignKeyConstraint(['aprendiz_id'], ['aprendices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('aprendiz_id'),
    )


def downgrade():
    op.drop_table('experiencias_aprendiz')
