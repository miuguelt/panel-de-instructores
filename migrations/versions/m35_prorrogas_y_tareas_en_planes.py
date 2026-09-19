"""Prorrogas de tareas, justificacion extemporanea y tareas en planes de mejoramiento

Revision ID: m35prorrogastareas
Revises: l34importapradmin
"""

from alembic import op
import sqlalchemy as sa


revision = 'm35prorrogastareas'
down_revision = 'l34importapradmin'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Crear tabla prorrogas_tareas
    op.create_table(
        'prorrogas_tareas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tarea_id', sa.Integer(), nullable=False),
        sa.Column('aprendiz_id', sa.Integer(), nullable=False),
        sa.Column('instructor_id', sa.Integer(), nullable=False),
        sa.Column('nueva_fecha_limite', sa.DateTime(), nullable=False),
        sa.Column('motivo', sa.Text(), nullable=True),
        sa.Column('creada_en', sa.DateTime(), nullable=True),
        sa.Column('actualizada_en', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['aprendiz_id'], ['aprendices.id']),
        sa.ForeignKeyConstraint(['instructor_id'], ['instructores.id']),
        sa.ForeignKeyConstraint(['tarea_id'], ['tareas.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tarea_id', 'aprendiz_id', name='uq_prorroga_tarea_aprendiz'),
    )
    op.create_index('ix_prorrogas_tareas_aprendiz_id', 'prorrogas_tareas', ['aprendiz_id'], unique=False)
    op.create_index('ix_prorrogas_tareas_instructor_id', 'prorrogas_tareas', ['instructor_id'], unique=False)
    op.create_index('ix_prorrogas_tareas_tarea_id', 'prorrogas_tareas', ['tarea_id'], unique=False)

    # 2. Agregar justificacion_retraso a entregas
    op.add_column('entregas', sa.Column('justificacion_retraso', sa.Text(), nullable=True))

    # 3. Agregar tarea_id a planes_mejoramiento
    op.add_column('planes_mejoramiento', sa.Column('tarea_id', sa.Integer(), nullable=True))
    op.create_index('ix_planes_mejoramiento_tarea_id', 'planes_mejoramiento', ['tarea_id'], unique=False)
    op.create_foreign_key(
        'fk_planes_mejoramiento_tarea_id',
        'planes_mejoramiento',
        'tareas',
        ['tarea_id'],
        ['id'],
    )


def downgrade():
    op.drop_constraint('fk_planes_mejoramiento_tarea_id', 'planes_mejoramiento', type_='foreignkey')
    op.drop_index('ix_planes_mejoramiento_tarea_id', table_name='planes_mejoramiento')
    op.drop_column('planes_mejoramiento', 'tarea_id')

    op.drop_column('entregas', 'justificacion_retraso')

    op.drop_index('ix_prorrogas_tareas_tarea_id', table_name='prorrogas_tareas')
    op.drop_index('ix_prorrogas_tareas_instructor_id', table_name='prorrogas_tareas')
    op.drop_index('ix_prorrogas_tareas_aprendiz_id', table_name='prorrogas_tareas')
    op.drop_table('prorrogas_tareas')
