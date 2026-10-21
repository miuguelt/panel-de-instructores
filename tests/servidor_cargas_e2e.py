"""Servidor hermético para comprobar cargas reales desde Chromium.

Solo este proceso de pruebas registra las rutas ``/__pruebas__/``. Sus casos
y archivos se prepararon para aprender y probar; no contienen registros reales.
"""

import hashlib
import os
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path
from threading import Thread

# Este módulo también se ejecuta fuera de pytest; no hereda su conftest.
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['REDIS_URL'] = ''
os.environ['SECRET_KEY'] = secrets.token_hex(64)
os.environ['IMPORTACIONES_ASINCRONAS'] = 'false'

from flask import abort, jsonify, redirect, render_template_string, request, send_file
from flask_login import current_user, login_user
from werkzeug.serving import make_server

from app import create_app, csrf, db
from app.models import ArchivoFichaVersion, Ficha, Instructor
from app.models.carga import CargaArchivo, EnvioCarga
from app.models.material import MaterialFicha
from app.services.cargas_trabajos import procesar_pendientes
from tests.apoyo_planeacion import crear_planeacion_xlsx


PAGINA = '''<!doctype html><html lang="es-CO"><meta charset="utf-8">
<meta name="csrf-token" content="{{ csrf_token() }}"><title>Prueba de carga real</title>
<p>Casos y archivos preparados para pruebas; no contienen registros reales.</p>
<form method="POST" action="{{ destino }}" enctype="multipart/form-data">
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
<label>Archivo <input name="{{ campo }}" type="file" accept="{{ formatos }}" required></label>
<input name="descripcion" value="Guía revisada del grupo">
<button type="submit">{{ boton }}</button></form>
<script>window.ADSO_MAX_UPLOAD_BYTES=50*1024*1024;window.ADSO_MAX_REQUEST_BYTES=51*1024*1024;
window.ADSO_RESUMABLE_UPLOAD={enabled:true,maxBytes:2147483648,chunkBytes:1024,url:'/cargas'};</script>
<script src="/static/js/uploads_reanudables.js"></script><script src="/static/js/uploads.js"></script>
</html>'''


def crear_servidor(carpeta):
    carpeta = Path(carpeta).resolve()
    carpeta.mkdir(parents=True, exist_ok=True)
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (carpeta / 'pruebas.sqlite').as_posix(),
        'SQLALCHEMY_ENGINE_OPTIONS': {},
        'SECRET_KEY': secrets.token_urlsafe(48),
        'UPLOAD_FOLDER': str(carpeta / 'uploads'),
        'WTF_CSRF_ENABLED': True,
        'RATELIMIT_ENABLED': False,
        'IMPORTACIONES_ASINCRONAS': False,
        'CARGAS_REANUDABLES_ENABLED': True,
        'CARGAS_BLOQUE_BYTES': 1024,
        'CARGAS_RESERVA_BYTES': 0,
        'CARGAS_RESERVA_PORCENTAJE': 0,
    })
    with app.app_context():
        db.create_all()
        instructor = Instructor(nombre='Instructor de pruebas', correo='prueba@example.com', rol='admin')
        instructor.set_password(secrets.token_urlsafe(48))
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(id=1, codigo='4000001', codigo_ficha='4000001', codigo_programa='228118',
                      nombre_programa='Tecnólogo en Analisis y Desarrollo de Software',
                      instructor_id=instructor.id, fecha_inicio=date.today() - timedelta(days=10),
                      fecha_fin=date.today() + timedelta(days=100))
        db.session.add(ficha)
        db.session.commit()
        instructor_id = instructor.id
    planeacion = crear_planeacion_xlsx(carpeta)
    servidor = make_server('127.0.0.1', 0, app, threaded=True)

    @app.get('/__pruebas__/ingresar')
    def ingresar():
        login_user(db.session.get(Instructor, instructor_id))
        formulario = 'planeacion' if request.args.get('formulario') == 'planeacion' else 'material'
        return redirect('/__pruebas__/form/' + formulario)

    @app.get('/__pruebas__/form/<formulario>')
    def formulario_carga(formulario):
        if not current_user.is_authenticated:
            abort(401)
        if formulario == 'planeacion':
            datos = dict(destino='/instructor/fichas/1/planeacion/cargar', campo='archivo_planeacion',
                         formatos='.xlsx', boton='Guardar planeación')
        else:
            datos = dict(destino='/instructor/fichas/1/materiales', campo='archivo',
                         formatos='.pdf', boton='Guardar material')
        return render_template_string(PAGINA, **datos)

    @app.get('/__pruebas__/estado')
    def estado():
        if not current_user.is_authenticated:
            abort(401)
        materiales = [dict(id=m.id, descripcion=m.descripcion,
                          descarga='/aprendiz/descargar/' + m.url_archivo)
                      for m in MaterialFicha.query.order_by(MaterialFicha.id)]
        versiones = []
        for version in ArchivoFichaVersion.query.order_by(ArchivoFichaVersion.id):
            ruta = Path(app.config['UPLOAD_FOLDER']) / version.ruta_archivo
            digest = hashlib.sha256()
            with ruta.open('rb') as archivo:
                for bloque in iter(lambda: archivo.read(1024 * 1024), b''):
                    digest.update(bloque)
            versiones.append(dict(id=version.id, estado=version.estado, sha256=digest.hexdigest()))
        return jsonify(materiales=materiales, versiones=versiones,
                       cargas=[dict(id=c.id, offset=c.offset, estado=c.estado) for c in CargaArchivo.query],
                       envios=[dict(id=e.id, estado=e.estado, resultado=e.resultado) for e in EnvioCarga.query])

    @app.post('/__pruebas__/procesar')
    def procesar():
        if not current_user.is_authenticated:
            abort(401)
        return jsonify(procesados=procesar_pendientes())

    @app.get('/__pruebas__/planeacion.xlsx')
    def archivo_planeacion():
        if not current_user.is_authenticated:
            abort(401)
        return send_file(planeacion)

    @app.post('/__pruebas__/detener')
    @csrf.exempt
    def detener():
        respuesta = jsonify(ok=True)
        respuesta.call_on_close(lambda: Thread(target=servidor.shutdown, daemon=True).start())
        return respuesta

    return servidor


if __name__ == '__main__':
    servidor = crear_servidor(sys.argv[1])
    print(f'URL=http://127.0.0.1:{servidor.server_port}', flush=True)
    try:
        servidor.serve_forever()
    finally:
        servidor.server_close()
        with servidor.app.app_context():
            db.session.remove()
            db.engine.dispose()
