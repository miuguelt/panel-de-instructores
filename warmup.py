"""Script de precalentamiento para invocar durante el arranque del contenedor."""

from app import create_app
from app.services.warmup import precargar_todas_las_fichas

if __name__ == '__main__':
    app = create_app()
    print('Iniciando precalentamiento de snapshots...')
    resumen = precargar_todas_las_fichas(app)
    print(
        f"Precalentamiento finalizado: {resumen['exitosas']}/{resumen['total']} fichas listas "
        f"(fallidas: {resumen['fallidas']})."
    )
