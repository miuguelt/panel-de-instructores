"""Permitir otorgar insignias a aprendices o grupos.

Revision ID: f016a2b9c421
Revises: e025798e7b92
Create Date: 2026-09-28 23:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'f016a2b9c421'
down_revision = 'e025798e7b92'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('insignias_otorgadas') as batch_op:
        batch_op.add_column(sa.Column('grupo_id', sa.Integer(), nullable=True))
        batch_op.alter_column(
            'aprendiz_id',
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.create_foreign_key(
            'fk_insignias_otorgadas_grupo_id_grupos', 'grupos', ['grupo_id'], ['id']
        )
        batch_op.create_index('ix_insignias_otorgadas_grupo_id', ['grupo_id'])
        batch_op.create_unique_constraint(
            'uq_grupo_insignia', ['grupo_id', 'insignia_id']
        )
        batch_op.create_check_constraint(
            'chk_insignia_owner',
            '(aprendiz_id IS NOT NULL AND grupo_id IS NULL) OR '
            '(aprendiz_id IS NULL AND grupo_id IS NOT NULL)',
        )


def downgrade():
    conexion = op.get_bind()
    otorgamientos_grupo = conexion.execute(
        sa.text(
            'SELECT COUNT(*) FROM insignias_otorgadas WHERE grupo_id IS NOT NULL'
        )
    ).scalar_one()
    if otorgamientos_grupo:
        raise RuntimeError(
            'No se puede revertir: existen otorgamientos a grupos que se perderían.'
        )

    with op.batch_alter_table('insignias_otorgadas') as batch_op:
        batch_op.drop_constraint('chk_insignia_owner', type_='check')
        batch_op.drop_constraint('uq_grupo_insignia', type_='unique')
        batch_op.drop_index('ix_insignias_otorgadas_grupo_id')
        batch_op.drop_constraint(
            'fk_insignias_otorgadas_grupo_id_grupos', type_='foreignkey'
        )
        batch_op.drop_column('grupo_id')
        batch_op.alter_column(
            'aprendiz_id',
            existing_type=sa.Integer(),
            nullable=False,
        )
