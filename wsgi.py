import os
import click

from app import create_app, db

app = create_app()


@app.cli.command('alertas-auto-evaluar')
@click.option('--verbose', is_flag=True, help='Mostrar detalles de la evaluacion')
def alertas_auto_evaluar(verbose):
    """Evalua automaticamente todas las fichas activas segun Res. 009 de 2024.
    Ejecuta reglas de asistencia, tareas, % asistencia y auto-escala casos inactivos.
    Programar via cron o tarea programada de Windows para ejecucion diaria."""
    from app.services.alertas import ejecutar_revision_automatica, vencer_planes_pendientes
    evaluadas = ejecutar_revision_automatica()
    vencidos = vencer_planes_pendientes()
    mensaje = f'Revision automatica completada: {evaluadas} ficha(s) evaluadas, {vencidos} plan(es) vencidos.'
    if verbose:
        click.echo(mensaje)
    app.logger.info(mensaje)


HOSTS_LOOPBACK = ('127.0.0.1', '::1', 'localhost')

# The 'stat' reloader avoids watchdog reacting to reads inside site-packages
# (venv, venv_win, uv, pycache) on Windows, which caused endless reload loops.
RELOADER_EXCLUDES = (
    '*venv*',
    '*venv_win*',
    '*uploads*',
    '*logs*',
    '*__pycache__*',
)


def opciones_servidor(env):
    """Build app.run() options from an environment mapping.

    With debug on, the Werkzeug interactive debugger allows code execution, so
    a non-loopback HOST is replaced by 127.0.0.1. Binding '::' on Windows is
    IPv6-only, so it also broke http://127.0.0.1 (the advertised URL).
    """
    debug = (env.get('FLASK_DEBUG') or '1').strip().lower() in ('1', 'true', 'yes')

    puerto_texto = (env.get('PORT') or '').strip() or '8009'
    try:
        puerto = int(puerto_texto)
    except ValueError as exc:
        raise ValueError(f'PORT debe ser un número entero; se recibió {puerto_texto!r}.') from exc

    host = (env.get('HOST') or '').strip() or '127.0.0.1'
    if debug and host not in HOSTS_LOOPBACK:
        print(f'HOST={host} no es loopback y el modo debug está activo: se usa 127.0.0.1.')
        host = '127.0.0.1'

    return {
        'host': host,
        'port': puerto,
        'debug': debug,
        'use_reloader': debug,
        'reloader_type': 'stat',
        'reloader_interval': 1,
        'exclude_patterns': RELOADER_EXCLUDES,
    }


if __name__ == '__main__':
    with app.app_context():
        import time
        for intento in range(5):
            try:
                db.engine.connect()
                print("Conexion a base de datos exitosa.")
                break
            except Exception as e:
                print(f"Intento {intento + 1}/5 fallido: {e}")
                if intento < 4:
                    time.sleep(2)
        else:
            print("No se pudo conectar a la BD. La app inicia igual.")

    app.run(**opciones_servidor(os.environ))
