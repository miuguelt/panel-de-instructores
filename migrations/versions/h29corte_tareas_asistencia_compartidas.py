"""separa tareas y asistencia por corte compartible

Revision ID: h29corte
Revises: g18c9e4088ef
"""

from alembic import op
import sqlalchemy as sa


revision = 'h29corte'
down_revision = 'g18c9e4088ef'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cortes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('instructor_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('fecha_inicio', sa.DateTime(), nullable=False),
        sa.Column('fecha_fin', sa.DateTime(), nullable=True),
        sa.Column('compartido', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.ForeignKeyConstraint(['instructor_id'], ['instructores.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_cortes_ficha_id', 'cortes', ['ficha_id'], unique=False)
    op.create_index('ix_cortes_instructor_id', 'cortes', ['instructor_id'], unique=False)
    op.create_index('ix_cortes_ficha_inicio', 'cortes', ['ficha_id', 'fecha_inicio'], unique=False)

    with op.batch_alter_table('tareas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('corte_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_tareas_corte_id_cortes', 'cortes', ['corte_id'], ['id'])
        batch_op.create_index('ix_tareas_corte_id', ['corte_id'], unique=False)

    with op.batch_alter_table('sesiones_asistencia', schema=None) as batch_op:
        batch_op.add_column(sa.Column('corte_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_sesiones_corte_id_cortes', 'cortes', ['corte_id'], ['id'])
        batch_op.create_index('ix_sesiones_asistencia_corte_id', ['corte_id'], unique=False)

    with op.batch_alter_table('puntajes_historicos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('corte_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_puntajes_corte_id_cortes', 'cortes', ['corte_id'], ['id'])
        batch_op.create_index('ix_puntajes_historicos_corte_id', ['corte_id'], unique=False)

    # Los datos existentes quedan en un corte inicial del responsable de cada
    # ficha. Al ser compartido, los instructores ya vinculados conservan acceso.
    op.execute(sa.text(
        "INSERT INTO cortes "
        "(ficha_id, instructor_id, nombre, fecha_inicio, fecha_fin, compartido, creado_en) "
        "SELECT id, instructor_id, 'Corte inicial', "
        "COALESCE(creada_en, CURRENT_TIMESTAMP), NULL, TRUE, "
        "COALESCE(creada_en, CURRENT_TIMESTAMP) FROM fichas"
    ))
    # Las tareas históricas ya podían pertenecer a instructores colaboradores.
    # Se crea también un corte inicial para cada uno de ellos para no ocultar
    # esas tareas al seleccionar el corte desde la interfaz.
    op.execute(sa.text(
        "INSERT INTO cortes "
        "(ficha_id, instructor_id, nombre, fecha_inicio, fecha_fin, compartido, creado_en) "
        "SELECT tareas.ficha_id, tareas.instructor_id, 'Corte inicial', "
        "COALESCE(MIN(tareas.creada_en), CURRENT_TIMESTAMP), NULL, TRUE, "
        "COALESCE(MIN(tareas.creada_en), CURRENT_TIMESTAMP) "
        "FROM tareas JOIN fichas ON fichas.id = tareas.ficha_id "
        "WHERE tareas.instructor_id <> fichas.instructor_id "
        "GROUP BY tareas.ficha_id, tareas.instructor_id"
    ))
    op.execute(sa.text(
        "UPDATE tareas SET corte_id = ("
        "SELECT cortes.id FROM cortes "
        "WHERE cortes.ficha_id = tareas.ficha_id "
        "AND cortes.instructor_id = tareas.instructor_id "
        "ORDER BY cortes.id LIMIT 1)"
    ))
    op.execute(sa.text(
        "UPDATE sesiones_asistencia SET corte_id = ("
        "SELECT cortes.id FROM cortes "
        "JOIN fichas ON fichas.id = sesiones_asistencia.ficha_id "
        "WHERE cortes.ficha_id = sesiones_asistencia.ficha_id "
        "AND cortes.instructor_id = fichas.instructor_id "
        "ORDER BY cortes.id LIMIT 1)"
    ))
    op.execute(sa.text(
        "UPDATE puntajes_historicos SET corte_id = ("
        "SELECT cortes.id FROM cortes JOIN fichas ON fichas.id = cortes.ficha_id "
        "WHERE cortes.ficha_id = puntajes_historicos.ficha_id "
        "AND cortes.instructor_id = fichas.instructor_id "
        "ORDER BY cortes.id LIMIT 1)"
    ))

    with op.batch_alter_table('sesiones_asistencia', schema=None) as batch_op:
        batch_op.drop_constraint('uq_sesion_ficha_fecha', type_='unique')
        batch_op.create_unique_constraint('uq_sesion_corte_fecha', ['corte_id', 'fecha'])


def downgrade():
    with op.batch_alter_table('sesiones_asistencia', schema=None) as batch_op:
        batch_op.drop_constraint('uq_sesion_corte_fecha', type_='unique')
        batch_op.create_unique_constraint('uq_sesion_ficha_fecha', ['ficha_id', 'fecha'])

    with op.batch_alter_table('puntajes_historicos', schema=None) as batch_op:
        batch_op.drop_index('ix_puntajes_historicos_corte_id')
        batch_op.drop_constraint('fk_puntajes_corte_id_cortes', type_='foreignkey')
        batch_op.drop_column('corte_id')

    with op.batch_alter_table('sesiones_asistencia', schema=None) as batch_op:
        batch_op.drop_index('ix_sesiones_asistencia_corte_id')
        batch_op.drop_constraint('fk_sesiones_corte_id_cortes', type_='foreignkey')
        batch_op.drop_column('corte_id')

    with op.batch_alter_table('tareas', schema=None) as batch_op:
        batch_op.drop_index('ix_tareas_corte_id')
        batch_op.drop_constraint('fk_tareas_corte_id_cortes', type_='foreignkey')
        batch_op.drop_column('corte_id')

    op.drop_index('ix_cortes_ficha_inicio', table_name='cortes')
    op.drop_index('ix_cortes_instructor_id', table_name='cortes')
    op.drop_index('ix_cortes_ficha_id', table_name='cortes')
    op.drop_table('cortes')
