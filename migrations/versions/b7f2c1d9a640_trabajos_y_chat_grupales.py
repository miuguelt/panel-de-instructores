"""Agrega trabajos grupales y mensajes persistentes para cada grupo.

Revision ID: b7f2c1d9a640
Revises: f016a2b9c421
"""

from alembic import op
import sqlalchemy as sa


revision = 'b7f2c1d9a640'
down_revision = 'f016a2b9c421'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'tareas',
        sa.Column(
            'es_grupal',
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )

    op.create_table(
        'tarea_grupo',
        sa.Column('tarea_id', sa.Integer(), nullable=False),
        sa.Column('grupo_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['tarea_id'], ['tareas.id'],
            name='fk_tarea_grupo_tarea_id_tareas',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['grupo_id'], ['grupos.id'],
            name='fk_tarea_grupo_grupo_id_grupos',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('tarea_id', 'grupo_id'),
    )
    op.create_index('ix_tarea_grupo_grupo_id', 'tarea_grupo', ['grupo_id'])

    with op.batch_alter_table('entregas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('grupo_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_entregas_grupo_id_grupos', 'grupos', ['grupo_id'], ['id']
        )
        batch_op.create_index('ix_entregas_grupo_id', ['grupo_id'], unique=False)
        batch_op.create_unique_constraint(
            'uq_entrega_tarea_grupo', ['tarea_id', 'grupo_id']
        )

    op.create_table(
        'grupo_mensajes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('grupo_id', sa.Integer(), nullable=False),
        sa.Column('aprendiz_id', sa.Integer(), nullable=False),
        sa.Column('contenido', sa.Text(), nullable=False),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['grupo_id'], ['grupos.id'],
            name='fk_grupo_mensajes_grupo_id_grupos',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['aprendiz_id'], ['aprendices.id'],
            name='fk_grupo_mensajes_aprendiz_id_aprendices',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_grupo_mensajes_grupo_id', 'grupo_mensajes', ['grupo_id'])
    op.create_index(
        'ix_grupo_mensajes_aprendiz_id', 'grupo_mensajes', ['aprendiz_id']
    )
    op.create_index(
        'ix_grupo_mensajes_grupo_fecha',
        'grupo_mensajes',
        ['grupo_id', 'creado_en', 'id'],
    )


def downgrade():
    conexion = op.get_bind()
    hay_datos_grupales = any((
        conexion.execute(sa.text(
            'SELECT COUNT(*) FROM tareas WHERE es_grupal = TRUE'
        )).scalar_one(),
        conexion.execute(sa.text(
            'SELECT COUNT(*) FROM tarea_grupo'
        )).scalar_one(),
        conexion.execute(sa.text(
            'SELECT COUNT(*) FROM entregas WHERE grupo_id IS NOT NULL'
        )).scalar_one(),
        conexion.execute(sa.text(
            'SELECT COUNT(*) FROM grupo_mensajes'
        )).scalar_one(),
    ))
    if hay_datos_grupales:
        raise RuntimeError(
            'No se puede revertir: existen trabajos o mensajes grupales que se perderían.'
        )

    op.drop_index('ix_grupo_mensajes_grupo_fecha', table_name='grupo_mensajes')
    op.drop_index('ix_grupo_mensajes_aprendiz_id', table_name='grupo_mensajes')
    op.drop_index('ix_grupo_mensajes_grupo_id', table_name='grupo_mensajes')
    op.drop_table('grupo_mensajes')

    op.drop_index('ix_tarea_grupo_grupo_id', table_name='tarea_grupo')
    op.drop_table('tarea_grupo')

    with op.batch_alter_table('entregas', schema=None) as batch_op:
        batch_op.drop_constraint('uq_entrega_tarea_grupo', type_='unique')
        batch_op.drop_index('ix_entregas_grupo_id')
        batch_op.drop_constraint('fk_entregas_grupo_id_grupos', type_='foreignkey')
        batch_op.drop_column('grupo_id')

    with op.batch_alter_table('tareas', schema=None) as batch_op:
        batch_op.drop_column('es_grupal')
