"""Servidor aislado para las pruebas de navegador del calendario de programación.

Los equipos, instructores y fichas son datos de práctica; no corresponden a registros reales.
"""

import sys
from datetime import date, timedelta

from flask import redirect
from flask_login import login_user

from app import csrf, db
from app.models import EquipoEjecutor, Ficha, Instructor
from app.services.programacion_instructores import guardar_asignacion, lunes_de
from tests.servidor_personalizacion import crear_servidor


def servidor_programacion(ruta):
    servidor = crear_servidor(ruta)
    app = servidor.app
    with app.app_context():
        if not EquipoEjecutor.query.first():
            sistemas = EquipoEjecutor(nombre='Sistemas')
            agricola = EquipoEjecutor(nombre='Agrícola')
            db.session.add_all([sistemas, agricola])
            db.session.flush()
            coord = Instructor(nombre='Carla Coordinación', correo='coord@example.com', rol='coordinacion')
            ana = Instructor(nombre='Ana María Rodríguez Castañeda', correo='ana@example.com', equipo_id=sistemas.id)
            beto = Instructor(nombre='Beto Agrícola', correo='beto@example.com', equipo_id=agricola.id)
            for inst in (coord, ana, beto):
                inst.set_password('no-se-usa-en-pruebas')
            db.session.add_all([coord, ana, beto])
            db.session.flush()
            sistemas.lider_id = ana.id
            db.session.add(Ficha(id=2, codigo='2900002', nombre_programa='Producción agropecuaria', instructor_id=beto.id))
            db.session.commit()
            lunes = lunes_de(date.today())
            guardar_asignacion({
                'instructor_id': ana.id, 'ficha_id': 1, 'modo': 'semanas',
                'competencia': 'Desarrollar la solución de software de acuerdo con el diseño y metodologías de desarrollo',
                'fecha_inicio': lunes.isoformat(), 'fecha_fin': (lunes + timedelta(days=5)).isoformat(),
                'dias_semana': ['0', '1', '2'], 'jornada': 'manana',
            }, None)

    @app.get('/__pruebas__/entrar/<int:instructor_id>')
    @csrf.exempt
    def entrar(instructor_id):
        login_user(db.session.get(Instructor, instructor_id))
        return redirect('/programacion/')

    return servidor


if __name__ == '__main__':
    servidor = servidor_programacion(sys.argv[1])
    print(f'URL=http://127.0.0.1:{servidor.server_port}', flush=True)
    servidor.serve_forever()
    servidor.server_close()
    with servidor.app.app_context():
        db.session.remove()
        db.engine.dispose()
