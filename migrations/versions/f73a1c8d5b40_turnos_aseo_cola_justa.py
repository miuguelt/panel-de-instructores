"""turnos de aseo con cola justa e intercambios

Revision ID: f73a1c8d5b40
Revises: e42f7b1c9d20
Create Date: 2026-07-23 23:30:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'f73a1c8d5b40'
down_revision = 'e42f7b1c9d20'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'configuracion_aseo',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column(
            'excluir_ausentes',
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            'aviso_horas',
            sa.Integer(),
            server_default='24',
            nullable=False,
        ),
        sa.Column('actualizada_en', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ficha_id'),
    )
    op.create_table(
        'contador_aseo',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('aprendiz_id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column(
            'veces_aseo',
            sa.Integer(),
            server_default='0',
            nullable=False,
        ),
        sa.Column('ultima_vez_aseo', sa.Date(), nullable=True),
        sa.Column('excluido_hasta', sa.Date(), nullable=True),
        sa.Column('motivo_exclusion', sa.String(length=250), nullable=True),
        sa.ForeignKeyConstraint(['aprendiz_id'], ['aprendices.id']),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'aprendiz_id',
            'ficha_id',
            name='uq_contador_aseo_aprendiz_ficha',
        ),
    )
    with op.batch_alter_table('contador_aseo', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_contador_aseo_aprendiz_id'),
            ['aprendiz_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_contador_aseo_ficha_id'),
            ['ficha_id'],
            unique=False,
        )

    op.create_table(
        'turnos_aseo',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ficha_id', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('aprendiz_1_id', sa.Integer(), nullable=False),
        sa.Column('aprendiz_2_id', sa.Integer(), nullable=False),
        sa.Column(
            'estado',
            sa.String(length=20),
            server_default='programado',
            nullable=False,
        ),
        sa.Column(
            'generado_por',
            sa.String(length=20),
            server_default='sistema',
            nullable=False,
        ),
        sa.Column('auditoria_1', sa.Text(), nullable=True),
        sa.Column('auditoria_2', sa.Text(), nullable=True),
        sa.Column('observacion', sa.Text(), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('actualizado_en', sa.DateTime(), nullable=False),
        sa.Column('completado_en', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            'aprendiz_1_id <> aprendiz_2_id',
            name='ck_turno_aseo_aprendices_distintos',
        ),
        sa.ForeignKeyConstraint(['aprendiz_1_id'], ['aprendices.id']),
        sa.ForeignKeyConstraint(['aprendiz_2_id'], ['aprendices.id']),
        sa.ForeignKeyConstraint(['ficha_id'], ['fichas.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'ficha_id', 'fecha', name='uq_turno_aseo_ficha_fecha'
        ),
    )
    with op.batch_alter_table('turnos_aseo', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_turnos_aseo_fecha'), ['fecha'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_turnos_aseo_ficha_id'), ['ficha_id'], unique=False
        )

    op.create_table(
        'intercambios_aseo',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('turno_id', sa.Integer(), nullable=False),
        sa.Column('turno_reciproco_id', sa.Integer(), nullable=True),
        sa.Column('aprendiz_solicita_id', sa.Integer(), nullable=False),
        sa.Column('aprendiz_recibe_id', sa.Integer(), nullable=False),
        sa.Column(
            'estado',
            sa.String(length=20),
            server_default='pendiente',
            nullable=False,
        ),
        sa.Column(
            'confirma_solicita',
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            'confirma_recibe',
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('respondido_en', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['aprendiz_recibe_id'], ['aprendices.id']),
        sa.ForeignKeyConstraint(['aprendiz_solicita_id'], ['aprendices.id']),
        sa.ForeignKeyConstraint(['turno_id'], ['turnos_aseo.id']),
        sa.ForeignKeyConstraint(['turno_reciproco_id'], ['turnos_aseo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('intercambios_aseo', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_intercambios_aseo_turno_id'),
            ['turno_id'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('intercambios_aseo', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_intercambios_aseo_turno_id'))
    op.drop_table('intercambios_aseo')

    with op.batch_alter_table('turnos_aseo', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_turnos_aseo_ficha_id'))
        batch_op.drop_index(batch_op.f('ix_turnos_aseo_fecha'))
    op.drop_table('turnos_aseo')

    with op.batch_alter_table('contador_aseo', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contador_aseo_ficha_id'))
        batch_op.drop_index(batch_op.f('ix_contador_aseo_aprendiz_id'))
    op.drop_table('contador_aseo')
    op.drop_table('configuracion_aseo')
