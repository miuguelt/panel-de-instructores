"""ranking de participacion e insignias

Revision ID: 8f2c91d4a7b1
Revises: 39ecddf454ad
Create Date: 2026-07-23 23:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = '8f2c91d4a7b1'
down_revision = '39ecddf454ad'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'configuracion_ranking',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('peso_asistencia', sa.Float(), server_default='40', nullable=False),
        sa.Column('peso_evidencias', sa.Float(), server_default='60', nullable=False),
        sa.Column('modo_visibilidad', sa.String(length=20), server_default='privado', nullable=False),
        sa.Column('modo_anonimo_parcial', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('periodo_corte', sa.String(length=20), server_default='trimestral', nullable=False),
        sa.Column('inicio_corte', sa.DateTime(), nullable=True),
        sa.Column('bonus_entrega_anticipada', sa.Float(), server_default='1', nullable=False),
        sa.Column('horas_entrega_anticipada', sa.Integer(), server_default='24', nullable=False),
        sa.Column('bonus_racha_asistencia', sa.Float(), server_default='3', nullable=False),
        sa.Column('semanas_racha', sa.Integer(), server_default='4', nullable=False),
        sa.Column('bonus_calificacion_alta', sa.Float(), server_default='1', nullable=False),
        sa.Column('umbral_calificacion_alta', sa.Float(), server_default='4', nullable=False),
        sa.Column('penalizacion_falla_injustificada', sa.Float(), server_default='1', nullable=False),
        sa.Column('actualizada_en', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ficha_id'),
    )
    op.execute(
        sa.text(
            'INSERT INTO configuracion_ranking (ficha_id, actualizada_en) '
            'SELECT id, CURRENT_TIMESTAMP FROM fichas'
        )
    )

    op.create_table(
        'insignias',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('codigo', sa.String(length=60), nullable=True),
        sa.Column('nombre', sa.String(length=100), nullable=False),
        sa.Column('descripcion', sa.String(length=300), nullable=False),
        sa.Column('icono', sa.String(length=20), server_default='🏅', nullable=False),
        sa.Column('tipo', sa.String(length=20), server_default='manual', nullable=False),
        sa.Column('condicion_json', sa.JSON(), nullable=True),
        sa.Column('activa', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('creada_en', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ficha_id', 'codigo', name='uq_insignia_ficha_codigo'),
    )
    op.create_index(op.f('ix_insignias_ficha_id'), 'insignias', ['ficha_id'], unique=False)

    op.create_table(
        'puntajes_historicos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('aprendiz_id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('fecha_corte', sa.DateTime(), nullable=False),
        sa.Column('tipo_corte', sa.String(length=20), server_default='automatico', nullable=False),
        sa.Column('puntaje_total', sa.Float(), server_default='0', nullable=False),
        sa.Column('puntaje_asistencia', sa.Float(), server_default='0', nullable=False),
        sa.Column('puntaje_evidencias', sa.Float(), server_default='0', nullable=False),
        sa.Column('posicion', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['aprendiz_id'], ['aprendices.id']),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_puntajes_historicos_aprendiz_id'), 'puntajes_historicos', ['aprendiz_id'], unique=False)
    op.create_index(op.f('ix_puntajes_historicos_fecha_corte'), 'puntajes_historicos', ['fecha_corte'], unique=False)
    op.create_index(op.f('ix_puntajes_historicos_ficha_id'), 'puntajes_historicos', ['ficha_id'], unique=False)

    op.create_table(
        'insignias_otorgadas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('aprendiz_id', sa.Integer(), nullable=False),
        sa.Column('insignia_id', sa.Integer(), nullable=False),
        sa.Column('fecha_obtencion', sa.DateTime(), nullable=False),
        sa.Column('otorgada_por', sa.String(length=30), server_default='sistema', nullable=False),
        sa.Column('instructor_id', sa.Integer(), nullable=True),
        sa.Column('notificada', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(['aprendiz_id'], ['aprendices.id']),
        sa.ForeignKeyConstraint(['insignia_id'], ['insignias.id']),
        sa.ForeignKeyConstraint(['instructor_id'], ['instructores.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('aprendiz_id', 'insignia_id', name='uq_aprendiz_insignia'),
    )
    op.create_index(op.f('ix_insignias_otorgadas_aprendiz_id'), 'insignias_otorgadas', ['aprendiz_id'], unique=False)
    op.create_index(op.f('ix_insignias_otorgadas_insignia_id'), 'insignias_otorgadas', ['insignia_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_insignias_otorgadas_insignia_id'), table_name='insignias_otorgadas')
    op.drop_index(op.f('ix_insignias_otorgadas_aprendiz_id'), table_name='insignias_otorgadas')
    op.drop_table('insignias_otorgadas')

    op.drop_index(op.f('ix_puntajes_historicos_ficha_id'), table_name='puntajes_historicos')
    op.drop_index(op.f('ix_puntajes_historicos_fecha_corte'), table_name='puntajes_historicos')
    op.drop_index(op.f('ix_puntajes_historicos_aprendiz_id'), table_name='puntajes_historicos')
    op.drop_table('puntajes_historicos')

    op.drop_index(op.f('ix_insignias_ficha_id'), table_name='insignias')
    op.drop_table('insignias')
    op.drop_table('configuracion_ranking')
