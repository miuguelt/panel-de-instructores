"""auditoría SENA: descargos y anulación de llamados, fase del plan, acta de novedades

Revision ID: y49auditoriasena
Revises: x48novedadesproductiva
Create Date: 2026-11-09 18:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'y49auditoriasena'
down_revision = 'x48novedadesproductiva'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('llamados_atencion') as batch:
        batch.add_column(sa.Column('descargos', sa.Text(), nullable=True))
        batch.add_column(sa.Column('descargos_en', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('anulado_en', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('anulado_por', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('motivo_anulacion', sa.Text(), nullable=True))
        batch.create_foreign_key(
            'fk_llamados_anulado_por_instructor', 'instructores', ['anulado_por'], ['id'])
    with op.batch_alter_table('planes_mejoramiento') as batch:
        batch.add_column(sa.Column('fase', sa.String(length=30), nullable=True))
    with op.batch_alter_table('novedades_aprendiz') as batch:
        batch.add_column(sa.Column('acta_comite', sa.String(length=60), nullable=True))
        batch.add_column(sa.Column('estado_cambiado_en', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('estado_cambiado_por', sa.Integer(), nullable=True))
        batch.create_foreign_key(
            'fk_novedades_estado_cambiado_por', 'instructores', ['estado_cambiado_por'], ['id'])
    # El plazo de justificación no puede ser menor que los 5 días hábiles del Art. 28.
    op.execute(
        "UPDATE configuracion_alertas_comite SET dias_plazo_justificacion = 5 "
        "WHERE dias_plazo_justificacion < 5"
    )
    # Las notificaciones guardadas llevaban la cédula en la URL: se quita el parámetro.
    op.execute(
        "UPDATE notificaciones SET url = substr(url, 1, instr(url, '?documento=') - 1) "
        "WHERE url LIKE '%?documento=%'"
        if op.get_context().dialect.name == 'sqlite' else
        "UPDATE notificaciones SET url = split_part(url, '?documento=', 1) "
        "WHERE url LIKE '%?documento=%'"
    )


def downgrade():
    with op.batch_alter_table('novedades_aprendiz') as batch:
        batch.drop_constraint('fk_novedades_estado_cambiado_por', type_='foreignkey')
        batch.drop_column('estado_cambiado_por')
        batch.drop_column('estado_cambiado_en')
        batch.drop_column('acta_comite')
    with op.batch_alter_table('planes_mejoramiento') as batch:
        batch.drop_column('fase')
    with op.batch_alter_table('llamados_atencion') as batch:
        batch.drop_constraint('fk_llamados_anulado_por_instructor', type_='foreignkey')
        batch.drop_column('motivo_anulacion')
        batch.drop_column('anulado_por')
        batch.drop_column('anulado_en')
        batch.drop_column('descargos_en')
        batch.drop_column('descargos')
