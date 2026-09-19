"""Store the learner selected during an asynchronous report import."""

from alembic import op
import sqlalchemy as sa


revision = 'l34importapradmin'
down_revision = 'l33aprendizadmin'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'importaciones_jobs',
        sa.Column('aprendiz_administrativo_id', sa.Integer(), nullable=True),
    )
    op.create_index(
        'ix_importaciones_jobs_aprendiz_administrativo_id',
        'importaciones_jobs',
        ['aprendiz_administrativo_id'],
    )
    op.create_foreign_key(
        'fk_importaciones_jobs_aprendiz_administrativo',
        'importaciones_jobs',
        'aprendices',
        ['aprendiz_administrativo_id'],
        ['id'],
    )


def downgrade():
    op.drop_constraint(
        'fk_importaciones_jobs_aprendiz_administrativo',
        'importaciones_jobs',
        type_='foreignkey',
    )
    op.drop_index(
        'ix_importaciones_jobs_aprendiz_administrativo_id',
        table_name='importaciones_jobs',
    )
    op.drop_column('importaciones_jobs', 'aprendiz_administrativo_id')
