"""Exporta la vista de gestión de grupos con datos sintéticos para pruebas en Chromium."""

import sys
from pathlib import Path

raiz = Path(__file__).resolve().parents[1]
if str(raiz) not in sys.path:
    sys.path.insert(0, str(raiz))

from app import create_app, db
from app.models.instructor import Instructor
from app.models.ficha import Ficha
from app.models.grupo import Grupo, GrupoAprendiz
from app.models.aprendiz import Aprendiz


def exportar(destino):
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
    })
    with app.app_context():
        db.create_all()
        inst = Instructor(id=1, nombre="Instructor Pruebas", correo="inst@sena.edu.co", password_hash="hash")
        db.session.add(inst)
        ficha = Ficha(id=2, codigo="2900000", nombre_programa="ADSO", instructor_id=inst.id)
        db.session.add(ficha)

        a1 = Aprendiz(id=1, ficha_id=ficha.id, documento="1001", nombre="Carlos", apellidos="Pérez", estado="EN_FORMACION", activo=True)
        a2 = Aprendiz(id=2, ficha_id=ficha.id, documento="1002", nombre="Ana", apellidos="Gómez", estado="EN_FORMACION", activo=True)
        a3 = Aprendiz(id=3, ficha_id=ficha.id, documento="1003", nombre="Beatriz", apellidos="Ruiz", estado="EN_FORMACION", activo=True)
        db.session.add_all([a1, a2, a3])

        g1 = Grupo(id=10, ficha_id=ficha.id, nombre="Equipo Alfa", activo=True)
        db.session.add(g1)
        db.session.flush()
        db.session.add(GrupoAprendiz(grupo_id=g1.id, aprendiz_id=a1.id))
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["_user_id"] = str(inst.id)
                sess["_fresh"] = True
            resp = client.get(f"/instructor/fichas/{ficha.id}/grupos")
            assert resp.status_code == 200
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(resp.get_data(as_text=True), encoding="utf-8")


if __name__ == '__main__':
    exportar(Path(__file__).resolve().parents[1] / 'test-results' / 'grupos-navegador.html')
