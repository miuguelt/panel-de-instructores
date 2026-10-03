"""Persistencia reutilizable de documentos extraídos y vistas calculadas."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import text, update

from app import db
from app.models import (
    ArchivoFichaVersion,
    Ficha,
    ResultadoCalculadoFicha,
    TIPO_PLANEACION,
    TIPO_PROGRAMA,
    TIPO_REPORTE_JUICIOS,
)


ALGORITMO_RESULTADOS = 'resultados-v2'


def fecha_corte_bogota():
    """Retorna el día local de Colombia para snapshots que dependen del calendario."""
    return datetime.now(ZoneInfo('America/Bogota')).date()


def _json_default(valor):
    """Codifica fechas y referencias ORM sin convertirlas en texto ambiguo."""
    if isinstance(valor, datetime):
        return {'__tipo__': 'datetime', 'valor': valor.isoformat()}
    if isinstance(valor, date):
        return {'__tipo__': 'date', 'valor': valor.isoformat()}
    if isinstance(valor, ArchivoFichaVersion):
        return {'__tipo__': 'archivo_ficha_version', 'id': valor.id}
    raise TypeError(f'No se puede persistir un valor de tipo {type(valor).__name__}.')


def _json_object_hook(valor):
    """Restaura tipos usados por las plantillas al leer snapshots."""
    tipo = valor.get('__tipo__')
    if tipo == 'date':
        return date.fromisoformat(valor['valor'])
    if tipo == 'datetime':
        return datetime.fromisoformat(valor['valor'])
    if tipo == 'archivo_ficha_version':
        return db.session.get(ArchivoFichaVersion, valor['id'])
    return valor


def guardar_contenido_documento(version, contenido, parser_version):
    """Guarda la salida estructurada del parser asociada a su archivo fuente."""
    version.contenido_extraido_json = json.loads(json.dumps(
        contenido, ensure_ascii=False, default=_json_default, separators=(',', ':'),
    ))
    version.contenido_extraido_version = parser_version


def obtener_contenido_documento(version, parser, parser_version):
    """Lee extracción persistida o parsea una versión heredada una sola vez."""
    if not version:
        return None
    if (
        getattr(version, 'contenido_extraido_json', None)
        and getattr(version, 'contenido_extraido_version', None) == parser_version
    ):
        return json.loads(
            json.dumps(version.contenido_extraido_json), object_hook=_json_object_hook,
        )

    ruta = Path(current_app.config['UPLOAD_FOLDER']) / getattr(version, 'ruta_archivo', '')
    if not ruta.is_file():
        raise FileNotFoundError(f'No se encontró el archivo fuente {getattr(version, "nombre_archivo", "desconocido")}.')
    contenido = parser(ruta)
    guardar_contenido_documento(version, contenido, parser_version)
    # Este camino migra de forma transparente una versión anterior que aún no
    # tenía extracción guardada; se persiste sin esperar a otra subida.
    db.session.commit()
    return contenido


def huella_resultado(ficha, tipo, fecha_corte, versiones):
    """Construye la clave de validez con calendario, revisión y versiones fuente."""
    fuentes = [
        {
            'id': getattr(version, 'id', None),
            'tipo': getattr(version, 'tipo', 'desconocido'),
            'hash': getattr(version, 'hash_sha256', None),
            'estado': getattr(version, 'estado', 'procesado'),
        }
        for version in sorted(
            (item for item in (versiones or []) if item),
            key=lambda item: (getattr(item, 'tipo', ''), getattr(item, 'id', 0) or 0),
        )
    ]
    entrada = {
        'tipo': tipo,
        'fecha_corte': fecha_corte.isoformat(),
        'revision': ficha.revision_calculos or 1,
        'fecha_inicio': ficha.fecha_inicio.isoformat() if ficha.fecha_inicio else None,
        'fecha_fin': ficha.fecha_fin.isoformat() if ficha.fecha_fin else None,
        'duracion_productiva_meses': ficha.duracion_productiva_meses,
        'codigo_programa': ficha.codigo_programa,
        'nombre_programa': ficha.nombre_programa,
        'fuentes': fuentes,
    }
    serializado = json.dumps(entrada, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serializado.encode('utf-8')).hexdigest()


def _adquirir_bloqueo(ficha_id):
    """Serializa los cálculos concurrentes de una ficha en PostgreSQL."""
    if db.session.get_bind().dialect.name == 'postgresql':
        db.session.execute(
            text('SELECT pg_advisory_xact_lock(:namespace, :ficha_id)'),
            {'namespace': 183741, 'ficha_id': int(ficha_id)},
        )


def invalidar_resultados_ficha(ficha_id):
    """Incrementa atómicamente la revisión cuando una carga masiva cambia datos."""
    if not ficha_id:
        return
    db.session.execute(
        update(Ficha)
        .where(Ficha.id == ficha_id)
        .values(revision_calculos=Ficha.revision_calculos + 1)
    )
    for ficha in db.session.identity_map.values():
        if isinstance(ficha, Ficha) and ficha.id == ficha_id:
            db.session.expire(ficha, ['revision_calculos'])


def obtener_resultado_persistido(ficha, tipo, fecha_corte, versiones, construir):
    """Retorna el snapshot vigente o lo calcula y persiste una sola vez."""
    huella = huella_resultado(ficha, tipo, fecha_corte, versiones)
    _adquirir_bloqueo(ficha.id)
    fila = ResultadoCalculadoFicha.query.filter_by(
        ficha_id=ficha.id,
        tipo=tipo,
        fecha_corte=fecha_corte,
        revision_calculo=ficha.revision_calculos or 1,
        version_algoritmo=ALGORITMO_RESULTADOS,
        huella_fuentes=huella,
    ).first()
    if fila:
        return json.loads(json.dumps(fila.payload_json), object_hook=_json_object_hook)

    resultado = construir()
    db.session.add(ResultadoCalculadoFicha(
        ficha_id=ficha.id,
        tipo=tipo,
        fecha_corte=fecha_corte,
        revision_calculo=ficha.revision_calculos or 1,
        version_algoritmo=ALGORITMO_RESULTADOS,
        huella_fuentes=huella,
        payload_json=json.loads(json.dumps(
            resultado, ensure_ascii=False, default=_json_default, separators=(',', ':'),
        )),
    ))
    limite_fecha = fecha_corte - timedelta(days=35)
    ResultadoCalculadoFicha.query.filter(
        ResultadoCalculadoFicha.ficha_id == ficha.id,
        ResultadoCalculadoFicha.fecha_corte < limite_fecha,
    ).delete(synchronize_session=False)
    # Guardar y liberar el bloqueo hace que las siguientes peticiones, incluso
    # desde otro proceso Gunicorn, lean el mismo snapshot de PostgreSQL.
    db.session.commit()
    return resultado


def precargar_resultados_ficha(ficha_id, hoy=None):
    """Construye los snapshots diarios después de cargar o importar fuentes."""
    from app.services.fases_dashboard import obtener_seguimiento_fases_dashboard
    from app.services.panorama_planeacion import construir_panorama
    from app.services.planeacion import parsear_planeacion
    from app.services.programa_formacion import parsear_programa
    from app.services.versiones_archivos import ultima_version

    fecha_corte = hoy or fecha_corte_bogota()
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        raise LookupError(f'No existe la ficha {ficha_id}.')

    version_plan = ultima_version(ficha.id, TIPO_PLANEACION, solo_procesadas=True)
    version_reporte = ultima_version(ficha.id, TIPO_REPORTE_JUICIOS, solo_procesadas=True)
    version_programa = ultima_version(ficha.id, TIPO_PROGRAMA, solo_procesadas=True)
    if version_plan:
        contenido = obtener_contenido_documento(
            version_plan, parsear_planeacion, parser_version='planeacion-v1',
        )
        programa = (
            obtener_contenido_documento(
                version_programa, parsear_programa, parser_version='programa-v1',
            )
            if version_programa else None
        )
        obtener_resultado_persistido(
            ficha,
            'panorama',
            fecha_corte,
            [version_plan, version_reporte, version_programa],
            lambda: construir_panorama(
                ficha,
                contenido,
                version_planeacion=version_plan,
                version_reporte=version_reporte,
                programa=programa,
                hoy=fecha_corte,
            ),
        )
    fases = obtener_seguimiento_fases_dashboard(ficha, hoy=fecha_corte)
    return {'ficha_id': ficha.id, 'panorama': bool(version_plan), 'fases': fases['disponible']}
