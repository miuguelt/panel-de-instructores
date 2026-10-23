"""Suscripciones Web Push y buzón de despachos de avisos del aprendiz."""

from alembic import op
import sqlalchemy as sa


revision = 'u45avisospush'
down_revision = 'u44cargasreanudables'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'aprendiz_push_subscriptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('aprendiz_id', sa.Integer(), sa.ForeignKey('aprendices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ficha_id', sa.Integer(), sa.ForeignKey('fichas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('endpoint_hash', sa.String(length=64), nullable=False, unique=True),
        sa.Column('endpoint_cifrado', sa.Text(), nullable=False),
        sa.Column('p256dh_cifrado', sa.Text(), nullable=False),
        sa.Column('auth_cifrado', sa.Text(), nullable=False),
        sa.Column('creada_en', sa.DateTime(), nullable=False),
        sa.Column('actualizada_en', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_aprendiz_push_subscriptions_aprendiz_id', 'aprendiz_push_subscriptions', ['aprendiz_id'])
    op.create_index('ix_aprendiz_push_subscriptions_ficha_id', 'aprendiz_push_subscriptions', ['ficha_id'])

    op.create_table(
        'aprendiz_push_dispatches',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('notificacion_id', sa.Integer(), sa.ForeignKey('notificaciones.id', ondelete='CASCADE'), nullable=False),
        sa.Column('aprendiz_id', sa.Integer(), sa.ForeignKey('aprendices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ficha_id', sa.Integer(), sa.ForeignKey('fichas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('suscripcion_id', sa.Integer(), sa.ForeignKey('aprendiz_push_subscriptions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('estado', sa.String(length=20), nullable=False),
        sa.Column('intentos', sa.Integer(), nullable=False),
        sa.Column('disponible_en', sa.DateTime(), nullable=False),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('enviado_en', sa.DateTime(), nullable=True),
        sa.Column('ultimo_error', sa.String(length=80), nullable=True),
        sa.UniqueConstraint('notificacion_id', 'suscripcion_id', name='uq_push_dispatch_notificacion_suscripcion'),
    )
    for column in ('notificacion_id', 'aprendiz_id', 'ficha_id', 'suscripcion_id', 'estado', 'disponible_en'):
        op.create_index(
            f'ix_aprendiz_push_dispatches_{column}',
            'aprendiz_push_dispatches', [column],
        )


def downgrade():
    op.drop_table('aprendiz_push_dispatches')
    op.drop_table('aprendiz_push_subscriptions')
