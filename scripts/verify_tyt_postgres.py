"""Verify TyT persistence in a temporary PostgreSQL schema, fully rolled back.

Run with the project's Python environment and its configured local database.
No real academic rows are read or changed; credentials never enter the output.
"""

from pathlib import Path
import secrets
import sys
import tempfile
from datetime import date, datetime
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app import create_app, db
from app.models import Aprendiz, Ficha, FichaInstructor, Instructor, Notificacion
from app.models.juicio import JuicioEvaluativo
from app.tyt.avisos import _guardar, actualizar_avisos
from app.tyt.consulta import obtener_seguimiento


def _seed():
    instructores = [Instructor(nombre=n, correo=f'{n}@example.com')
                   for n in ('responsable', 'vinculado')]
    for instructor in instructores:
        instructor.set_password(secrets.token_urlsafe(24))
    db.session.add_all(instructores)
    db.session.flush()
    ficha = Ficha(codigo='VERIFICACION_TYT', nombre_programa='Verificación',
                  instructor_id=instructores[0].id,
                  fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 10, 11))
    db.session.add(ficha)
    db.session.flush()
    db.session.add(FichaInstructor(ficha_id=ficha.id, instructor_id=instructores[1].id))
    aprendices = [Aprendiz(documento=str(i), nombre=f'Aprendiz {i}', apellidos='Verificación',
                           ficha_id=ficha.id, estado=estado)
                  for i, estado in enumerate(('EN_FORMACION', 'CONDICIONADO', 'RETIRADO'))]
    db.session.add_all(aprendices)
    db.session.flush()
    for n in range(10):
        db.session.add(JuicioEvaluativo(
            ficha_id=ficha.id, aprendiz_id=aprendices[0].id, competencia='C',
            resultado_aprendizaje=f'R{n}', juicio='APROBADO' if n < 6 else 'POR EVALUAR',
            huella=secrets.token_hex(32),
        ))
    db.session.commit()
    return ficha


def _verify(ficha):
    seguimiento = obtener_seguimiento(ficha)
    assert seguimiento['total_aprendices'] == 2
    assert seguimiento['promedio_aprobados'] == 30
    assert seguimiento['faltan_evaluar'] == 8
    actualizar_avisos(ficha, ahora=datetime(2026, 3, 10, 12))
    assert Notificacion.query.count() == 0
    for _ in range(2):
        actualizar_avisos(ficha, ahora=datetime(2026, 3, 11, 12))
        db.session.commit()
    assert Notificacion.query.count() == 4
    assert Notificacion.query.filter_by(destinatario_tipo='instructor').count() == 2
    assert Notificacion.query.filter_by(destinatario_tipo='aprendiz').count() == 2
    existente = Notificacion.query.first()
    # Force a unique-key collision, as with a stale concurrent recipient snapshot.
    _guardar(existente.destinatario_tipo, existente.destinatario_id, ficha.id,
             existente.clave, existente.mensaje, existente.url, set())
    db.session.commit()
    assert Notificacion.query.count() == 4
    JuicioEvaluativo.query.update({'juicio': 'APROBADO'})
    db.session.commit()
    assert obtener_seguimiento(ficha)['promedio_aprobados'] == 50


def main():
    with tempfile.TemporaryDirectory() as uploads:
        app = create_app({'TESTING': True, 'UPLOAD_FOLDER': uploads, 'RATELIMIT_ENABLED': False})
        with app.app_context():
            engine = db.engine
            if engine.dialect.name != 'postgresql':
                raise RuntimeError('Esta verificación requiere PostgreSQL.')
            schema = 'tyt_verification_' + uuid4().hex
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                    connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                    db.session.remove()
                    db.engines[None] = connection
                    db.session.configure(join_transaction_mode='create_savepoint')
                    db.create_all()
                    _verify(_seed())
                finally:
                    db.session.remove()
                    db.engines[None] = engine
                    transaction.rollback()
            with engine.connect() as connection:
                assert connection.execute(text(
                    'SELECT count(*) FROM pg_namespace WHERE nspname = :schema'
                ), {'schema': schema}).scalar_one() == 0
            print('PASS: PostgreSQL, cálculo, destinatarios, idempotencia, actualización y rollback.')


if __name__ == '__main__':
    main()
