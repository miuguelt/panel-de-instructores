"""Servidor exclusivo de las pruebas de navegador, con datos preparados y BD aislada."""

import secrets
import sys
from threading import Thread
from pathlib import Path

from werkzeug.serving import make_server

from app import create_app, csrf, db
from app.models import Aprendiz, Ficha, Instructor


def crear_servidor(ruta_base):
    ruta_base = Path(ruta_base).resolve()
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + ruta_base.as_posix(),
        'SQLALCHEMY_ENGINE_OPTIONS': {},
        'SECRET_KEY': secrets.token_urlsafe(32),
        'WTF_CSRF_ENABLED': True,
        'RATELIMIT_ENABLED': False,
    })
    with app.app_context():
        db.create_all()
        if not db.session.get(Ficha, 1):
            instructor = Instructor(nombre='Instructor de pruebas', correo='instructor@example.com')
            instructor.set_password(secrets.token_urlsafe(32))
            db.session.add(instructor)
            db.session.flush()
            ficha = Ficha(id=1, codigo='PRUEBAS', nombre_programa='Análisis y Desarrollo de Software',
                          instructor_id=instructor.id)
            db.session.add(ficha)
            db.session.add_all([
                Aprendiz(documento='1001', nombre='Ana', apellidos='Pruebas', ficha_id=1),
                Aprendiz(documento='1002', nombre='Luis', apellidos='Pruebas', ficha_id=1),
            ])
            db.session.commit()
    servidor = make_server('127.0.0.1', 0, app, threaded=True)

    @app.post('/__pruebas__/detener')
    @csrf.exempt
    def detener_servidor():
        Thread(target=servidor.shutdown, daemon=True).start()
        return {'ok': True}

    return servidor


if __name__ == '__main__':
    servidor = crear_servidor(sys.argv[1])
    print(f'URL=http://127.0.0.1:{servidor.server_port}', flush=True)
    servidor.serve_forever()
    servidor.server_close()
    with servidor.app.app_context():
        db.session.remove()
        db.engine.dispose()
