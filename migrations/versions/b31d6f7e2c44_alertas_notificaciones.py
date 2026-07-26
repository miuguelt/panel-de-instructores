"""alertas normativas, casos y notificaciones

Revision ID: b31d6f7e2c44
Revises: 8f2c91d4a7b1
Create Date: 2026-07-24 00:30:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'b31d6f7e2c44'
down_revision = '8f2c91d4a7b1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'configuracion_alertas_comite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('umbral_fallas_consecutivas', sa.Integer(), server_default='3', nullable=False),
        sa.Column('umbral_fallas_acumuladas', sa.Integer(), server_default='5', nullable=False),
        sa.Column('umbral_tareas_incumplidas', sa.Integer(), server_default='3', nullable=False),
        sa.Column('dias_plazo_justificacion', sa.Integer(), server_default='2', nullable=False),
        sa.Column('actualizada_en', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ficha_id'),
    )
    op.execute(
        sa.text(
            'INSERT INTO configuracion_alertas_comite (ficha_id, actualizada_en) '
            'SELECT id, CURRENT_TIMESTAMP FROM fichas'
        )
    )

    op.create_table(
        'alertas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('aprendiz_id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=30), server_default='asistencia', nullable=False),
        sa.Column('nivel', sa.String(length=20), server_default='amarilla', nullable=False),
        sa.Column('titulo', sa.String(length=180), nullable=False),
        sa.Column('mensaje', sa.Text(), nullable=False),
        sa.Column('detalle_json', sa.JSON(), nullable=True),
        sa.Column('fecha_generada', sa.DateTime(), nullable=False),
        sa.Column('estado', sa.String(length=30), server_default='activa', nullable=False),
        sa.Column('observaciones', sa.Text(), nullable=True),
        sa.Column('fecha_resuelta', sa.DateTime(), nullable=True),
        sa.Column('resuelta_por', sa.Integer(), nullable=True),
        sa.Column('fecha_escalada', sa.DateTime(), nullable=True),
        sa.Column('escalada_por', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['aprendiz_id'], ['aprendices.id']),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.ForeignKeyConstraint(['resuelta_por'], ['instructores.id']),
        sa.ForeignKeyConstraint(['escalada_por'], ['instructores.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_alertas_aprendiz_id'), 'alertas', ['aprendiz_id'], unique=False)
    op.create_index(op.f('ix_alertas_ficha_id'), 'alertas', ['ficha_id'], unique=False)
    op.create_index(op.f('ix_alertas_fecha_generada'), 'alertas', ['fecha_generada'], unique=False)
    op.create_index(op.f('ix_alertas_estado'), 'alertas', ['estado'], unique=False)

    op.create_table(
        'notificaciones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('destinatario_tipo', sa.String(length=20), nullable=False),
        sa.Column('destinatario_id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=True),
        sa.Column('mensaje', sa.Text(), nullable=False),
        sa.Column('tipo', sa.String(length=40), server_default='general', nullable=False),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('clave', sa.String(length=180), nullable=False),
        sa.Column('fecha_creada', sa.DateTime(), nullable=False),
        sa.Column('leida', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('leida_en', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('destinatario_tipo', 'destinatario_id', 'clave',
                            name='uq_notificacion_destinatario_clave'),
    )
    op.create_index(op.f('ix_notificaciones_destinatario_tipo'), 'notificaciones', ['destinatario_tipo'], unique=False)
    op.create_index(op.f('ix_notificaciones_destinatario_id'), 'notificaciones', ['destinatario_id'], unique=False)
    op.create_index(op.f('ix_notificaciones_ficha_id'), 'notificaciones', ['ficha_id'], unique=False)
    op.create_index(op.f('ix_notificaciones_fecha_creada'), 'notificaciones', ['fecha_creada'], unique=False)
    op.create_index(op.f('ix_notificaciones_leida'), 'notificaciones', ['leida'], unique=False)

    with op.batch_alter_table('entregas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('estado_revision', sa.String(length=20), server_default='pendiente', nullable=False))


def downgrade():
    with op.batch_alter_table('entregas', schema=None) as batch_op:
        batch_op.drop_column('estado_revision')

    op.drop_index(op.f('ix_notificaciones_leida'), table_name='notificaciones')
    op.drop_index(op.f('ix_notificaciones_fecha_creada'), table_name='notificaciones')
    op.drop_index(op.f('ix_notificaciones_ficha_id'), table_name='notificaciones')
    op.drop_index(op.f('ix_notificaciones_destinatario_id'), table_name='notificaciones')
    op.drop_index(op.f('ix_notificaciones_destinatario_tipo'), table_name='notificaciones')
    op.drop_table('notificaciones')

    op.drop_index(op.f('ix_alertas_estado'), table_name='alertas')
    op.drop_index(op.f('ix_alertas_fecha_generada'), table_name='alertas')
    op.drop_index(op.f('ix_alertas_ficha_id'), table_name='alertas')
    op.drop_index(op.f('ix_alertas_aprendiz_id'), table_name='alertas')
    op.drop_table('alertas')
    op.drop_table('configuracion_alertas_comite')
