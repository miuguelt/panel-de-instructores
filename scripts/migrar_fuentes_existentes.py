"""Integra reportes, planeaciones y programas de fichas existentes."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from sqlalchemy import func
from werkzeug.datastructures import FileStorage

from app import db
from app.models import (
    ArchivoFichaVersion,
    Ficha,
    TIPO_PLANEACION,
    TIPO_PROGRAMA,
    TIPO_REPORTE_JUICIOS,
)
from app.services.alertas import actualizar_alertas_ficha
from app.services.archivos import nombre_original_desde_ruta
from app.services.importacion_ficha import (
    importar_archivo,
    leer_metadata_archivo,
    validar_reporte_ficha,
)
from app.services.planeacion import comparar_fuentes, parsear_planeacion
from app.services.programa_formacion import parsear_programa
from app.services.ranking import actualizar_participacion_ficha
from app.services.resultados_persistidos import (
    guardar_contenido_documento,
    precargar_resultados_ficha,
)
from app.services.versiones_archivos import actualizar_estado


EXTENSIONES_POR_TIPO = {
    TIPO_REPORTE_JUICIOS: {'.xls', '.xlsx'},
    TIPO_PLANEACION: {'.xlsx'},
    TIPO_PROGRAMA: {'.pdf'},
}
VERSION_PARSER = {
    TIPO_PLANEACION: 'planeacion-v1',
    TIPO_PROGRAMA: 'programa-v1',
}


def _detectar_fuentes(raiz):
    """Lista solo los tres tipos de fuente admitidos en las carpetas de fichas."""
    raiz = Path(raiz).resolve()
    carpeta_fichas = raiz / 'fichas'
    if not carpeta_fichas.is_dir():
        return []

    fuentes = []
    for ruta in sorted(carpeta_fichas.rglob('*')):
        if not ruta.is_file() or ruta.is_symlink():
            continue
        relativa = ruta.relative_to(raiz)
        if len(relativa.parts) < 3:
            continue
        tipo = relativa.parts[2]
        if tipo in EXTENSIONES_POR_TIPO and ruta.suffix.lower() in EXTENSIONES_POR_TIPO[tipo]:
            fuentes.append((ruta, tipo, relativa.parts[1]))
    return fuentes


def _huella_archivo(ruta):
    """Calcula SHA-256 por bloques para no cargar el original completo en memoria."""
    digest = hashlib.sha256()
    with Path(ruta).open('rb') as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b''):
            digest.update(bloque)
    return digest.hexdigest()


def _leer_fuente(ruta, tipo):
    """Extrae metadatos o contenido usando el lector propio de cada formato."""
    if tipo == TIPO_REPORTE_JUICIOS:
        with Path(ruta).open('rb') as stream:
            metadata = leer_metadata_archivo(FileStorage(stream=stream, filename=Path(ruta).name))
        return metadata, None
    if tipo == TIPO_PLANEACION:
        contenido = parsear_planeacion(ruta)
        return contenido['metadata'], contenido
    if tipo == TIPO_PROGRAMA:
        contenido = parsear_programa(ruta)
        return contenido['metadata'], contenido
    raise ValueError(f'Tipo de fuente no permitido: {tipo}.')


def _validar_con_ficha(tipo, ficha, metadata):
    """Valida que el documento pertenezca al programa y ficha existentes."""
    if tipo == TIPO_REPORTE_JUICIOS:
        validar_reporte_ficha(ficha, metadata)
        return True
    alineacion = comparar_fuentes(metadata, {
        'codigo_programa': ficha.codigo_programa,
        'nombre_programa': ficha.nombre_programa,
    })
    if tipo == TIPO_PLANEACION:
        return bool(
            alineacion['alineado']
            and alineacion.get('codigo_planeacion')
            and alineacion.get('codigo_ficha')
        )
    return bool(alineacion['alineado'])


def _resolver_ficha(tipo, id_carpeta, metadata, fichas):
    """Prefiere el ID guardado en la ruta y exige una coincidencia única alternativa."""
    try:
        id_carpeta = int(id_carpeta)
    except (TypeError, ValueError):
        id_carpeta = None

    por_id = next((ficha for ficha in fichas if ficha.id == id_carpeta), None)
    if por_id:
        try:
            if _validar_con_ficha(tipo, por_id, metadata):
                return por_id, 'coincide'
        except ValueError:
            pass

    coincidencias = []
    for ficha in fichas:
        if ficha is por_id:
            continue
        try:
            if _validar_con_ficha(tipo, ficha, metadata):
                coincidencias.append(ficha)
        except ValueError:
            continue
    if len(coincidencias) == 1:
        return coincidencias[0], 'coincide'
    if coincidencias:
        return None, 'ambigua'
    return None, 'sin_ficha'


def _crear_version_desde_original(raiz, ruta, tipo, ficha, digest, metadata):
    """Registra el archivo existente sin copiarlo ni cambiar el volumen."""
    numero = db.session.query(func.max(ArchivoFichaVersion.version)).filter_by(
        ficha_id=ficha.id, tipo=tipo,
    ).scalar() or 0
    relativa = Path(ruta).resolve().relative_to(Path(raiz).resolve()).as_posix()
    nombre = nombre_original_desde_ruta(Path(ruta).name)
    version = ArchivoFichaVersion(
        ficha_id=ficha.id,
        instructor_id=ficha.instructor_id,
        tipo=tipo,
        version=int(numero) + 1,
        nombre_archivo=nombre,
        ruta_archivo=relativa,
        hash_sha256=digest,
        tamano_bytes=Path(ruta).stat().st_size,
        estado='pendiente',
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False, default=str),
    )
    db.session.add(version)
    db.session.flush()
    return version


def _actualizar_extraccion_existente(version, ruta, tipo, metadata, contenido):
    """Completa una extracción JSONB faltante o de una versión de parser anterior."""
    parser_version = VERSION_PARSER[tipo]
    if version.contenido_extraido_json and version.contenido_extraido_version == parser_version:
        return False
    if contenido is None:
        _, contenido = _leer_fuente(ruta, tipo)
    guardar_contenido_documento(version, contenido, parser_version)
    actualizar_estado(version, 'procesado', detalle=version.detalle, metadata=metadata)
    return True


def _importar_fuente(raiz, ruta, tipo, ficha, digest, metadata, contenido):
    """Guarda el registro y su resultado en la misma transacción por archivo."""
    version = _crear_version_desde_original(raiz, ruta, tipo, ficha, digest, metadata)
    resultado = None
    if tipo == TIPO_REPORTE_JUICIOS:
        with Path(ruta).open('rb') as stream:
            archivo = FileStorage(stream=stream, filename=Path(ruta).name)
            resultado = importar_archivo(archivo, ficha, ficha.instructor_id)
        detalle = (
            f"{resultado.get('nuevos', 0)} aprendices, "
            f"{resultado.get('juicios_nuevos', 0)} juicios"
        )
        actualizar_estado(version, 'procesado', detalle=detalle, metadata=metadata)
    else:
        guardar_contenido_documento(version, contenido, VERSION_PARSER[tipo])
        actualizar_estado(version, 'procesado', metadata=metadata)
    db.session.commit()
    return version, resultado


def _metadata_version(version):
    """Devuelve metadatos de una versión sin depender del tipo JSON del motor."""
    if isinstance(version.metadata_json, dict):
        return dict(version.metadata_json)
    try:
        return json.loads(version.metadata_json or '{}')
    except (TypeError, ValueError):
        return {}


def _fecha_version_reporte(version):
    """Obtiene la fecha de negocio de un reporte y ordena al final por versión."""
    valor = _metadata_version(version).get('fecha_reporte')
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return date.min


def _reaplicar_reporte_mas_reciente(raiz, ficha_id):
    """Restaura el reporte actual después de importar reportes históricos."""
    versiones = ArchivoFichaVersion.query.filter_by(
        ficha_id=ficha_id, tipo=TIPO_REPORTE_JUICIOS,
    ).all()
    if not versiones:
        return None
    mas_reciente = max(
        versiones,
        key=lambda version: (_fecha_version_reporte(version), version.version),
    )
    max_version = max(version.version for version in versiones)
    metadata = _metadata_version(mas_reciente)
    if metadata.get('_conciliado_hasta_version') == max_version:
        return None

    ruta = Path(raiz) / mas_reciente.ruta_archivo
    if not ruta.is_file():
        raise FileNotFoundError(f'No se encuentra el reporte más reciente: {ruta.name}.')
    with ruta.open('rb') as stream:
        archivo = FileStorage(stream=stream, filename=Path(ruta).name)
        resultado = importar_archivo(
            archivo, mas_reciente.ficha, mas_reciente.instructor_id,
        )
    metadata['_conciliado_hasta_version'] = max_version
    mas_reciente.metadata_json = json.dumps(metadata, ensure_ascii=False, default=str)
    actualizar_estado(mas_reciente, 'procesado', detalle=mas_reciente.detalle, metadata=metadata)
    db.session.commit()
    return resultado


def migrar_fuentes_existentes(app, raiz, aplicar=False):
    """Reconcilia archivos con fichas vigentes; no crea fichas nuevas."""
    raiz = Path(raiz).resolve()
    resultado = {
        'encontrados': 0,
        'elegibles': 0,
        'registrados': 0,
        'ya_existian': 0,
        'duplicados': 0,
        'sin_ficha': 0,
        'ambiguas': 0,
        'rechazados': 0,
        'errores': 0,
        'extracciones_actualizadas': 0,
        'filas_con_error': 0,
        'reportes_reaplicados': 0,
    }
    fichas_cambiadas = defaultdict(set)
    hashes_en_esta_ejecucion = set()

    with app.app_context():
        fuentes = _detectar_fuentes(raiz)
        resultado['encontrados'] = len(fuentes)
        fichas = Ficha.query.order_by(Ficha.id).all()
        existentes = {
            (version.tipo, version.hash_sha256): version
            for version in ArchivoFichaVersion.query.filter(
                ArchivoFichaVersion.tipo.in_(tuple(EXTENSIONES_POR_TIPO)),
                ArchivoFichaVersion.hash_sha256.isnot(None),
            ).all()
        }
        pendientes = []

        for ruta, tipo, id_carpeta in fuentes:
            try:
                digest = _huella_archivo(ruta)
            except OSError:
                resultado['errores'] += 1
                continue

            clave_hash = (tipo, digest)
            version_existente = existentes.get(clave_hash)
            if version_existente:
                if tipo == TIPO_REPORTE_JUICIOS:
                    resultado['ya_existian'] += 1
                    continue
                parser_version = VERSION_PARSER[tipo]
                if (
                    version_existente.contenido_extraido_json
                    and version_existente.contenido_extraido_version == parser_version
                ):
                    resultado['ya_existian'] += 1
                    continue
                try:
                    metadata, contenido = _leer_fuente(ruta, tipo)
                    if _actualizar_extraccion_existente(
                        version_existente, ruta, tipo, metadata, contenido
                    ):
                        resultado['extracciones_actualizadas'] += 1
                        if aplicar:
                            db.session.commit()
                        else:
                            db.session.rollback()
                    else:
                        resultado['ya_existian'] += 1
                except Exception:
                    db.session.rollback()
                    resultado['errores'] += 1
                continue
            if clave_hash in hashes_en_esta_ejecucion:
                resultado['duplicados'] += 1
                continue
            hashes_en_esta_ejecucion.add(clave_hash)

            try:
                metadata, contenido = _leer_fuente(ruta, tipo)
            except Exception:
                resultado['rechazados'] += 1
                continue
            ficha, estado_match = _resolver_ficha(tipo, id_carpeta, metadata, fichas)
            if not ficha:
                clave_estado = 'ambiguas' if estado_match == 'ambigua' else estado_match
                resultado[clave_estado] += 1
                continue
            fecha_reporte = metadata.get('fecha_reporte')
            if not isinstance(fecha_reporte, date):
                fecha_reporte = date.min
            pendientes.append((
                ficha.id, tipo, fecha_reporte, ruta.stat().st_mtime_ns,
                digest, ruta, ficha, metadata, contenido,
            ))

        pendientes.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4]))
        resultado['elegibles'] = len(pendientes)
        if aplicar:
            for (_ficha_id, tipo, _fecha, _mtime, digest, ruta, ficha, metadata, contenido) in pendientes:
                try:
                    version, importacion = _importar_fuente(
                        raiz, ruta, tipo, ficha, digest, metadata, contenido,
                    )
                    existentes[(tipo, digest)] = version
                    resultado['registrados'] += 1
                    fichas_cambiadas[ficha.id].add(tipo)
                    if importacion:
                        resultado['filas_con_error'] += len(importacion.get('errores') or [])
                except Exception:
                    db.session.rollback()
                    resultado['errores'] += 1

            fichas_con_reportes = {
                ficha_id for (ficha_id,) in db.session.query(
                    ArchivoFichaVersion.ficha_id.distinct(),
                ).filter_by(tipo=TIPO_REPORTE_JUICIOS).all()
            }
            fichas_para_recalcular = set(fichas_cambiadas)
            for ficha_id in fichas_con_reportes | {
                ficha_id for ficha_id, tipos in fichas_cambiadas.items()
                if TIPO_REPORTE_JUICIOS in tipos
            }:
                try:
                    importacion = _reaplicar_reporte_mas_reciente(raiz, ficha_id)
                    if importacion is not None:
                        resultado['reportes_reaplicados'] += 1
                        resultado['filas_con_error'] += len(importacion.get('errores') or [])
                        fichas_para_recalcular.add(ficha_id)
                    if ficha_id in fichas_para_recalcular:
                        actualizar_alertas_ficha(ficha_id)
                        actualizar_participacion_ficha(ficha_id)
                        precargar_resultados_ficha(ficha_id)
                        db.session.commit()
                except Exception:
                    db.session.rollback()
                    resultado['errores'] += 1
        db.session.remove()

    return resultado


def main(argumentos=None):
    """Ejecuta revisión por defecto; --apply confirma la integración en PostgreSQL."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Guarda las fuentes en la base de datos.')
    args = parser.parse_args(argumentos)
    from wsgi import app

    resultado = migrar_fuentes_existentes(
        app, app.config['UPLOAD_FOLDER'], aplicar=args.apply,
    )
    print(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
    return 1 if resultado['errores'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
