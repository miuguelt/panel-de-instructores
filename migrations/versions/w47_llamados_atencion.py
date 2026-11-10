"""llamados de atencion escritos (Acuerdo 009 de 2024, Art. 46)

Revision ID: w47llamadosatencion
Revises: v46cambiopassword
Create Date: 2026-11-09 11:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'w47llamadosatencion'
down_revision = 'v46cambiopassword'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'llamados_atencion',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('aprendiz_id', sa.Integer(), sa.ForeignKey('aprendices.id'), nullable=False),
        sa.Column('ficha_id', sa.Integer(), sa.ForeignKey('fichas.id'), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('etapa', sa.String(length=20), nullable=False, server_default='lectiva'),
        sa.Column('fase', sa.String(length=30), nullable=True),
        sa.Column('numero', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=False),
        sa.Column('orientaciones', sa.Text(), nullable=True),
        sa.Column('alerta_id', sa.Integer(), sa.ForeignKey('alertas.id'), nullable=True),
        sa.Column('creado_por', sa.Integer(), sa.ForeignKey('instructores.id'), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_llamados_atencion_aprendiz_id', 'llamados_atencion', ['aprendiz_id'])
    op.create_index('ix_llamados_atencion_ficha_id', 'llamados_atencion', ['ficha_id'])
    op.create_index('ix_llamados_aprendiz_tipo', 'llamados_atencion', ['aprendiz_id', 'tipo'])
    # El reglamento fija cinco días hábiles para justificar (Art. 28, par. 3).
    with op.batch_alter_table('configuracion_alertas_comite', schema=None) as batch_op:
        batch_op.alter_column('dias_plazo_justificacion', server_default='5')
    op.execute(
        'UPDATE configuracion_alertas_comite SET dias_plazo_justificacion = 5 '
        'WHERE dias_plazo_justificacion = 2'
    )


def downgrade():
    with op.batch_alter_table('configuracion_alertas_comite', schema=None) as batch_op:
        batch_op.alter_column('dias_plazo_justificacion', server_default=None)
    op.drop_index('ix_llamados_aprendiz_tipo', table_name='llamados_atencion')
    op.drop_index('ix_llamados_atencion_ficha_id', table_name='llamados_atencion')
    op.drop_index('ix_llamados_atencion_aprendiz_id', table_name='llamados_atencion')
    op.drop_table('llamados_atencion')
