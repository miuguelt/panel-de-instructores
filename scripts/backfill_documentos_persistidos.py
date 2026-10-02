"""Migra extracciones de planeaciones y programas PDF ya cargados."""

from pathlib import Path

from app import db
from app.models import ArchivoFichaVersion, TIPO_PLANEACION, TIPO_PROGRAMA
from app.services.planeacion import parsear_planeacion
from app.services.programa_formacion import parsear_programa
from app.services.resultados_persistidos import (
    guardar_contenido_documento,
    precargar_resultados_ficha,
)
from wsgi import app


PARSER_POR_TIPO = {
    TIPO_PLANEACION: ('planeacion-v1', parsear_planeacion),
    TIPO_PROGRAMA: ('programa-v1', parsear_programa),
}


def ejecutar_backfill():
    """Extrae archivos heredados una vez y calienta sus snapshots diarios."""
    migrados = 0
    errores = []
    fichas = set()
    with app.app_context():
        versiones = ArchivoFichaVersion.query.filter(
            ArchivoFichaVersion.tipo.in_(PARSER_POR_TIPO),
            ArchivoFichaVersion.estado == 'procesado',
            ArchivoFichaVersion.contenido_extraido_json.is_(None),
        ).order_by(ArchivoFichaVersion.id).all()
        for version in versiones:
            parser_version, parser = PARSER_POR_TIPO[version.tipo]
            ruta = Path(app.config['UPLOAD_FOLDER']) / version.ruta_archivo
            try:
                if not ruta.is_file():
                    raise FileNotFoundError(f'No existe {version.ruta_archivo}.')
                contenido = parser(ruta)
                guardar_contenido_documento(version, contenido, parser_version)
                db.session.commit()
                migrados += 1
                fichas.add(version.ficha_id)
            except Exception as exc:
                db.session.rollback()
                errores.append(f'versión {version.id}: {type(exc).__name__}: {exc}')
        for ficha_id in fichas:
            try:
                precargar_resultados_ficha(ficha_id)
            except Exception as exc:
                db.session.rollback()
                errores.append(f'ficha {ficha_id}: {type(exc).__name__}: {exc}')
        db.session.remove()
    return {'documentos_migrados': migrados, 'errores': errores}


if __name__ == '__main__':
    resultado = ejecutar_backfill()
    print(f"Documentos migrados: {resultado['documentos_migrados']}")
    for error in resultado['errores']:
        print(error)
    raise SystemExit(1 if resultado['errores'] else 0)
