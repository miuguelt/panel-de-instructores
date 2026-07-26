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

    debug = os.environ.get('FLASK_DEBUG', '1').lower() in ('1', 'true', 'yes')
    # Watchdog debe observar el código y las plantillas del proyecto, no el
    # entorno virtual ni sus caches del entorno. Esto evita reinicios por cambios internos
    # de site-packages durante instalaciones, pruebas o herramientas IA.
    reloader_excludes = (
        '*venv*',
        '*venv_win*',
        '*uploads*',
        '*logs*',
        '*__pycache__*',
    )
    app.run(
        # Listen on IPv6 so http://localhost:8009 does not wait for the
        # IPv6-to-IPv4 fallback before reaching the development server.
        host='::',
        port=8009,
        debug=debug,
        use_reloader=debug,
        reloader_type='watchdog',
        reloader_interval=1,
        exclude_patterns=reloader_excludes,
    )
