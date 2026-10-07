"""Servidor aislado para comprobar el recorrido completo con entregas preparadas."""

import sys
from datetime import datetime, timedelta

from app import db
from app.models import Entrega, Notificacion, Tarea
from tests.servidor_personalizacion import crear_servidor


def servidor_experiencia(ruta):
    servidor = crear_servidor(ruta)
    with servidor.app.app_context():
        if not db.session.get(Tarea, 1):
            ahora = datetime.utcnow()
            db.session.add_all([
                Tarea(id=1, ficha_id=1, instructor_id=1, titulo='Explicar la solución',
                      requiere_archivo=False, fecha_limite=ahora + timedelta(days=2)),
                Tarea(id=2, ficha_id=1, instructor_id=1, titulo='Probar la solución',
                      requiere_archivo=False, fecha_limite=ahora + timedelta(days=3)),
                Tarea(id=3, ficha_id=1, instructor_id=1, titulo='Documentar decisiones',
                      requiere_archivo=False, fecha_limite=ahora + timedelta(days=4)),
            ])
            db.session.flush()
            db.session.add_all([
                Entrega(tarea_id=1, aprendiz_id=1, estado_revision='rechazada', calificada=True,
                        feedback='Explica la decisión y aplica los ajustes.',
                        enlace_repositorio='https://example.com/evidencia'),
                Entrega(tarea_id=2, aprendiz_id=1, estado_revision='aprobada', calificada=True,
                        feedback='La solución supera las comprobaciones.'),
                Notificacion(destinatario_tipo='aprendiz', destinatario_id=1, ficha_id=1,
                             mensaje='Revisa los ajustes de tu evidencia.', tipo='calificacion', clave='prueba-revision'),
                Notificacion(destinatario_tipo='aprendiz', destinatario_id=1, ficha_id=1,
                             mensaje='Ya registraste tu primer avance.', tipo='logro', clave='prueba-logro'),
            ])
            db.session.commit()
    return servidor


if __name__ == '__main__':
    servidor = servidor_experiencia(sys.argv[1])
    print(f'URL=http://127.0.0.1:{servidor.server_port}', flush=True)
    servidor.serve_forever()
    servidor.server_close()
    with servidor.app.app_context():
        db.session.remove()
        db.engine.dispose()
