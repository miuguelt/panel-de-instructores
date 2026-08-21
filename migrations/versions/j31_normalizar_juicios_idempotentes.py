"""Consolidate duplicate learning outcomes created by mutable fingerprints.

Revision ID: j31juicios
Revises: i30ciclo
"""

from __future__ import annotations

import hashlib
import re

from alembic import op
import sqlalchemy as sa


revision = 'j31juicios'
down_revision = 'i30ciclo'
branch_labels = None
depends_on = None


def _texto(valor):
    if valor is None:
        return ''
    return re.sub(r'\s+', ' ', str(valor).strip())


def _clave(row):
    return (
        row['ficha_id'],
        row['aprendiz_id'],
        _texto(row['competencia']),
        _texto(row['resultado_aprendizaje']),
    )


def _huella(clave):
    return hashlib.sha256(
        '|'.join(_texto(parte) for parte in clave).encode('utf-8')
    ).hexdigest()


def _es_aprobado(juicio):
    estado = _texto(juicio).upper()
    return (
        'APROBADO' in estado
        and 'AUN NO' not in estado
        and 'POR EVALUAR' not in estado
    )


def _fila_preferida(anterior, actual):
    """Conserva aprobados al consolidar estados históricos contradictorios."""
    if _es_aprobado(actual['juicio']) != _es_aprobado(anterior['juicio']):
        return actual if _es_aprobado(actual['juicio']) else anterior
    return actual


def _consolidar_vinculos(conn, origen_id, destino_id):
    vinculos = conn.execute(sa.text(
        """
        SELECT instructor_id, fecha_importacion
        FROM juicios_evaluativos_instructores
        WHERE juicio_id = :juicio_id
        """
    ), {'juicio_id': origen_id}).mappings().all()

    for vinculo in vinculos:
        existe = conn.execute(sa.text(
            """
            SELECT 1
            FROM juicios_evaluativos_instructores
            WHERE juicio_id = :juicio_id AND instructor_id = :instructor_id
            """
        ), {
            'juicio_id': destino_id,
            'instructor_id': vinculo['instructor_id'],
        }).first()
        if not existe:
            conn.execute(sa.text(
                """
                INSERT INTO juicios_evaluativos_instructores
                    (juicio_id, instructor_id, fecha_importacion)
                VALUES (:juicio_id, :instructor_id, :fecha_importacion)
                """
            ), {
                'juicio_id': destino_id,
                'instructor_id': vinculo['instructor_id'],
                'fecha_importacion': vinculo['fecha_importacion'],
            })

    conn.execute(sa.text(
        """
        DELETE FROM juicios_evaluativos_instructores
        WHERE juicio_id = :juicio_id
        """
    ), {'juicio_id': origen_id})


def upgrade():
    conn = op.get_bind()
    filas = conn.execute(sa.text(
        """
        SELECT id, ficha_id, aprendiz_id, competencia,
               resultado_aprendizaje, juicio
        FROM juicios_evaluativos
        ORDER BY id
        """
    )).mappings().all()

    canonicos = {}
    for fila in filas:
        clave = _clave(fila)
        anterior = canonicos.get(clave)
        if anterior is not None:
            preferida = _fila_preferida(anterior, fila)
            origen = fila if preferida['id'] == anterior['id'] else anterior
            destino = preferida
            _consolidar_vinculos(conn, origen['id'], destino['id'])
            conn.execute(sa.text(
                "DELETE FROM juicios_evaluativos WHERE id = :juicio_id"
            ), {'juicio_id': origen['id']})
            canonicos[clave] = destino
        else:
            canonicos[clave] = fila

    for clave, fila in canonicos.items():
        conn.execute(sa.text(
            """
            UPDATE juicios_evaluativos
            SET huella = :huella
            WHERE id = :juicio_id
            """
        ), {'huella': _huella(clave), 'juicio_id': fila['id']})


def downgrade():
    # La consolidación elimina estados duplicados y no se puede revertir sin
    # una copia de seguridad de la base de datos.
    pass
