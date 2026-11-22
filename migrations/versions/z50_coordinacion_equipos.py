"""coordinación: equipos ejecutores y asignaciones de programación de instructores

Revision ID: z50coordinacionequipos
Revises: y49auditoriasena
Create Date: 2026-11-22 09:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'z50coordinacionequipos'
down_revision = 'y49auditoriasena'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'equipos_ejecutores',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('nombre', sa.String(length=120), nullable=False, unique=True),
        sa.Column('descripcion', sa.String(length=300), nullable=True),
        sa.Column('lider_id', sa.Integer(), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('creado_en', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['lider_id'], ['instructores.id'], name='fk_equipo_lider_instructor'),
    )
    op.create_index('ix_equipos_ejecutores_lider_id', 'equipos_ejecutores', ['lider_id'])

    with op.batch_alter_table('instructores') as batch:
        batch.add_column(sa.Column('equipo_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_instructor_equipo', 'equipos_ejecutores', ['equipo_id'], ['id'])
        batch.create_index('ix_instructores_equipo_id', ['equipo_id'])

    op.create_table(
        'asignaciones_programacion',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('instructor_id', sa.Integer(), sa.ForeignKey('instructores.id'), nullable=False),
        sa.Column('ficha_id', sa.Integer(), sa.ForeignKey('fichas.id'), nullable=False),
        sa.Column('competencia', sa.String(length=300), nullable=False),
        sa.Column('fecha_inicio', sa.Date(), nullable=False),
        sa.Column('fecha_fin', sa.Date(), nullable=False),
        sa.Column('dias_semana', sa.Integer(), nullable=False, server_default='31'),
        sa.Column('jornada', sa.String(length=10), nullable=False, server_default='manana'),
        sa.Column('observacion', sa.String(length=300), nullable=True),
        sa.Column('creado_por_id', sa.Integer(), sa.ForeignKey('instructores.id'), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('actualizado_en', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('fecha_fin >= fecha_inicio', name='ck_asignacion_fechas'),
        sa.CheckConstraint('dias_semana > 0 AND dias_semana < 64', name='ck_asignacion_dias'),
        sa.CheckConstraint("jornada IN ('manana', 'tarde', 'noche')", name='ck_asignacion_jornada'),
    )
    for columna in ('instructor_id', 'ficha_id', 'fecha_inicio', 'fecha_fin'):
        op.create_index(f'ix_asignaciones_programacion_{columna}', 'asignaciones_programacion', [columna])


def downgrade():
    op.drop_table('asignaciones_programacion')
    with op.batch_alter_table('instructores') as batch:
        batch.drop_index('ix_instructores_equipo_id')
        batch.drop_constraint('fk_instructor_equipo', type_='foreignkey')
        batch.drop_column('equipo_id')
    op.drop_index('ix_equipos_ejecutores_lider_id', table_name='equipos_ejecutores')
    op.drop_table('equipos_ejecutores')
