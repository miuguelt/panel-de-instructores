"""fichas compartidas e historial de juicios evaluativos

Revision ID: e42f7b1c9d20
Revises: d17a4c9e6b30
"""
from alembic import op
import sqlalchemy as sa


revision = 'e42f7b1c9d20'
down_revision = 'd17a4c9e6b30'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('fichas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('codigo_ficha', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('codigo_programa', sa.String(length=30), nullable=True))
    op.create_index('ix_fichas_codigo_ficha', 'fichas', ['codigo_ficha'], unique=False)
    op.create_index('ix_fichas_codigo_programa', 'fichas', ['codigo_programa'], unique=False)

    op.create_table(
        'fichas_instructores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('instructor_id', sa.Integer(), nullable=False),
        sa.Column('fecha_asignacion', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.ForeignKeyConstraint(['instructor_id'], ['instructores.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ficha_id', 'instructor_id', name='uq_ficha_instructor'),
    )
    op.create_index('ix_fichas_instructores_ficha_id', 'fichas_instructores', ['ficha_id'], unique=False)
    op.create_index('ix_fichas_instructores_instructor_id', 'fichas_instructores', ['instructor_id'], unique=False)

    op.create_table(
        'juicios_evaluativos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('aprendiz_id', sa.Integer(), nullable=False),
        sa.Column('competencia', sa.String(length=300), nullable=True),
        sa.Column('resultado_aprendizaje', sa.Text(), nullable=True),
        sa.Column('juicio', sa.String(length=80), nullable=True),
        sa.Column('fecha_juicio', sa.DateTime(), nullable=True),
        sa.Column('fecha_fuente_texto', sa.String(length=80), nullable=True),
        sa.Column('funcionario_registro', sa.String(length=200), nullable=True),
        sa.Column('fuente_archivo', sa.String(length=255), nullable=True),
        sa.Column('huella', sa.String(length=64), nullable=False),
        sa.Column('importado_en', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.ForeignKeyConstraint(['aprendiz_id'], ['aprendices.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('huella'),
    )
    op.create_index('ix_juicios_evaluativos_ficha_id', 'juicios_evaluativos', ['ficha_id'], unique=False)
    op.create_index('ix_juicios_evaluativos_aprendiz_id', 'juicios_evaluativos', ['aprendiz_id'], unique=False)
    op.create_index('ix_juicios_evaluativos_fecha_juicio', 'juicios_evaluativos', ['fecha_juicio'], unique=False)
    op.create_index('ix_juicios_evaluativos_huella', 'juicios_evaluativos', ['huella'], unique=False)

    op.create_table(
        'juicios_evaluativos_instructores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('juicio_id', sa.Integer(), nullable=False),
        sa.Column('instructor_id', sa.Integer(), nullable=False),
        sa.Column('fecha_importacion', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['juicio_id'], ['juicios_evaluativos.id']),
        sa.ForeignKeyConstraint(['instructor_id'], ['instructores.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('juicio_id', 'instructor_id', name='uq_juicio_instructor'),
    )
    op.create_index('ix_juicios_evaluativos_instructores_juicio_id', 'juicios_evaluativos_instructores', ['juicio_id'], unique=False)
    op.create_index('ix_juicios_evaluativos_instructores_instructor_id', 'juicios_evaluativos_instructores', ['instructor_id'], unique=False)


def downgrade():
    op.drop_table('juicios_evaluativos_instructores')
    op.drop_table('juicios_evaluativos')
    op.drop_table('fichas_instructores')
    op.drop_index('ix_fichas_codigo_programa', table_name='fichas')
    op.drop_index('ix_fichas_codigo_ficha', table_name='fichas')
    with op.batch_alter_table('fichas', schema=None) as batch_op:
        batch_op.drop_column('codigo_programa')
        batch_op.drop_column('codigo_ficha')
