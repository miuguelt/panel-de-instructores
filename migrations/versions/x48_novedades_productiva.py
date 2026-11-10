"""novedades del aprendiz y etapa productiva (Acuerdo 009 de 2024, Art. 18 y 30)

Revision ID: x48novedadesproductiva
Revises: w47llamadosatencion
Create Date: 2026-11-09 15:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'x48novedadesproductiva'
down_revision = 'w47llamadosatencion'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'novedades_aprendiz',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('aprendiz_id', sa.Integer(), sa.ForeignKey('aprendices.id'), nullable=False),
        sa.Column('ficha_id', sa.Integer(), sa.ForeignKey('fichas.id'), nullable=False),
        sa.Column('tipo', sa.String(length=30), nullable=False),
        sa.Column('estado', sa.String(length=20), nullable=False, server_default='solicitada'),
        sa.Column('fecha_solicitud', sa.Date(), nullable=False),
        sa.Column('fecha_inicio', sa.Date(), nullable=True),
        sa.Column('fecha_fin', sa.Date(), nullable=True),
        sa.Column('causa', sa.String(length=30), nullable=True),
        sa.Column('ampliacion', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('observacion', sa.Text(), nullable=True),
        sa.Column('creado_por', sa.Integer(), sa.ForeignKey('instructores.id'), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_novedades_aprendiz_aprendiz_id', 'novedades_aprendiz', ['aprendiz_id'])
    op.create_index('ix_novedades_aprendiz_ficha_id', 'novedades_aprendiz', ['ficha_id'])
    op.create_table(
        'etapas_productivas',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('aprendiz_id', sa.Integer(), sa.ForeignKey('aprendices.id'), nullable=False),
        sa.Column('ficha_id', sa.Integer(), sa.ForeignKey('fichas.id'), nullable=False),
        sa.Column('alternativa', sa.String(length=30), nullable=False),
        sa.Column('empresa', sa.String(length=200), nullable=True),
        sa.Column('fecha_inicio', sa.Date(), nullable=True),
        sa.Column('fecha_fin_estimada', sa.Date(), nullable=True),
        sa.Column('planeacion_avalada', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('fecha_aval', sa.Date(), nullable=True),
        sa.Column('instructor_seguimiento', sa.String(length=150), nullable=True),
        sa.Column('estado', sa.String(length=20), nullable=False, server_default='por_iniciar'),
        sa.Column('actualizado_en', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('aprendiz_id', 'ficha_id', name='uq_etapa_productiva_aprendiz_ficha'),
    )
    op.create_index('ix_etapas_productivas_aprendiz_id', 'etapas_productivas', ['aprendiz_id'])
    op.create_index('ix_etapas_productivas_ficha_id', 'etapas_productivas', ['ficha_id'])
    op.create_table(
        'seguimientos_productiva',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('etapa_id', sa.Integer(), sa.ForeignKey('etapas_productivas.id'), nullable=False),
        sa.Column('momento', sa.String(length=20), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('observacion', sa.Text(), nullable=True),
        sa.Column('creado_por', sa.Integer(), sa.ForeignKey('instructores.id'), nullable=True),
        sa.UniqueConstraint('etapa_id', 'momento', name='uq_seguimiento_etapa_momento'),
    )
    op.create_index('ix_seguimientos_productiva_etapa_id', 'seguimientos_productiva', ['etapa_id'])


def downgrade():
    op.drop_index('ix_seguimientos_productiva_etapa_id', table_name='seguimientos_productiva')
    op.drop_table('seguimientos_productiva')
    op.drop_index('ix_etapas_productivas_ficha_id', table_name='etapas_productivas')
    op.drop_index('ix_etapas_productivas_aprendiz_id', table_name='etapas_productivas')
    op.drop_table('etapas_productivas')
    op.drop_index('ix_novedades_aprendiz_ficha_id', table_name='novedades_aprendiz')
    op.drop_index('ix_novedades_aprendiz_aprendiz_id', table_name='novedades_aprendiz')
    op.drop_table('novedades_aprendiz')
