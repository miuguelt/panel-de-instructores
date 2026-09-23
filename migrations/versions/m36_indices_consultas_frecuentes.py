"""Indices compuestos para las consultas de navegación más frecuentes."""

from alembic import op


revision = 'm36indicesfrecuentes'
down_revision = 'm35prorrogastareas'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_alertas_ficha_estado', 'alertas', ['ficha_id', 'estado'], unique=False
    )
    op.create_index(
        'ix_notificaciones_destinatario_leida',
        'notificaciones',
        ['destinatario_tipo', 'destinatario_id', 'leida'],
        unique=False,
    )
    op.create_index(
        'ix_aprendices_ficha_estado', 'aprendices', ['ficha_id', 'estado'], unique=False
    )
    op.create_index(
        'ix_juicios_ficha_aprendiz',
        'juicios_evaluativos',
        ['ficha_id', 'aprendiz_id'],
        unique=False,
    )
    op.create_index(
        'ix_tareas_ficha_instructor',
        'tareas',
        ['ficha_id', 'instructor_id'],
        unique=False,
    )
    op.create_index(
        'ix_sesiones_ficha_fecha', 'sesiones_asistencia', ['ficha_id', 'fecha'], unique=False
    )


def downgrade():
    op.drop_index('ix_sesiones_ficha_fecha', table_name='sesiones_asistencia')
    op.drop_index('ix_tareas_ficha_instructor', table_name='tareas')
    op.drop_index('ix_juicios_ficha_aprendiz', table_name='juicios_evaluativos')
    op.drop_index('ix_aprendices_ficha_estado', table_name='aprendices')
    op.drop_index('ix_notificaciones_destinatario_leida', table_name='notificaciones')
    op.drop_index('ix_alertas_ficha_estado', table_name='alertas')
