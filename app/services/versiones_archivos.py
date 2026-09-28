"""Persistencia y consulta de versiones de archivos de una ficha."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from flask import current_app
from sqlalchemy import func
from werkzeug.utils import secure_filename

from app import db
from app.models.archivo_ficha import (
    ArchivoFichaVersion,
    TIPO_PLANEACION,
    TIPO_PROGRAMA,
    TIPO_REPORTE_JUICIOS,
)
from app.services.archivos import ArchivoDuplicado, ArchivoService


TIPOS_VERSIONADOS = {TIPO_PLANEACION, TIPO_REPORTE_JUICIOS, TIPO_PROGRAMA}
EXTENSION_POR_TIPO = {TIPO_PROGRAMA: '.pdf'}


def _hash_stream(stream):
    stream.seek(0)
    digest = hashlib.sha256()
    while True:
        bloque = stream.read(1024 * 1024)
        if not bloque:
            break
        digest.update(bloque)
    stream.seek(0)
    return digest.hexdigest()


def crear_version(archivo, ficha_id, instructor_id, tipo, metadata=None, permitir_existente=False):
    """Guarda un archivo en la ruta persistente y crea su registro de versión."""
    if tipo not in TIPOS_VERSIONADOS:
        raise ValueError(f'Tipo de archivo no soportado: {tipo}.')
    predeterminada = EXTENSION_POR_TIPO.get(tipo, '.xlsx')
    nombre_original = secure_filename(archivo.filename or '') or f'{tipo}{predeterminada}'
    extension = Path(nombre_original).suffix.lower() or predeterminada
    ultimo = db.session.query(func.max(ArchivoFichaVersion.version)).filter_by(
        ficha_id=ficha_id, tipo=tipo
    ).scalar() or 0
    numero_version = int(ultimo) + 1
    nombre_disco = f'v{numero_version}_{uuid4().hex}_{nombre_original}'
    carpeta = f'fichas/{ficha_id}/{tipo}'
    hash_sha256 = _hash_stream(archivo.stream)
    existente = ArchivoFichaVersion.query.filter_by(
        ficha_id=ficha_id,
        tipo=tipo,
        hash_sha256=hash_sha256,
    ).order_by(ArchivoFichaVersion.version.desc()).first()
    if existente:
        if permitir_existente:
            archivo.stream.seek(0)
            return existente
        raise ArchivoDuplicado(
            f'Este archivo ya fue cargado como versión {existente.version}; '
            'no se creó una versión duplicada.'
        )
    ruta = ArchivoService.guardar_crudo(
        archivo,
        carpeta=carpeta,
        nombre_archivo=nombre_disco,
    )
    tamano = Path(ruta).stat().st_size
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, default=str)
    version = ArchivoFichaVersion(
        ficha_id=ficha_id,
        instructor_id=instructor_id,
        tipo=tipo,
        version=numero_version,
        nombre_archivo=nombre_original,
        ruta_archivo=f'{carpeta}/{nombre_disco}',
        hash_sha256=hash_sha256,
        tamano_bytes=tamano,
        estado='pendiente',
        metadata_json=metadata_json,
    )
    db.session.add(version)
    db.session.flush()
    archivo.stream.seek(0)
    return version


def actualizar_estado(version, estado, detalle=None, metadata=None):
    version.estado = estado
    version.detalle = detalle
    if metadata is not None:
        version.metadata_json = json.dumps(metadata, ensure_ascii=False, default=str)


def asegurar_version_reporte(ficha_o_id, instructor_id=None):
    """Garantiza que una ficha con juicios evaluativos tenga su versión registrada.

    Si la ficha ya tiene una versión de reporte de juicios procesada, la retorna.
    Si no tiene versión pero ya tiene juicios evaluativos en base de datos
    (por ejemplo creada desde el reporte antes de la tabla versionada o sincronizada),
    genera/reconstruye el archivo Excel persistente, crea la versión 1 y la retorna.
    """
    import io
    import shutil
    import openpyxl
    from werkzeug.datastructures import FileStorage
    from app.models.ficha import Ficha
    from app.models.juicio import JuicioEvaluativo
    from app.models.aprendiz import Aprendiz
    from app.services.importacion_ficha import leer_metadata_archivo

    if isinstance(ficha_o_id, int):
        ficha = db.session.get(Ficha, ficha_o_id)
    else:
        ficha = ficha_o_id

    if not ficha:
        return None

    existente = ArchivoFichaVersion.query.filter_by(
        ficha_id=ficha.id,
        tipo=TIPO_REPORTE_JUICIOS,
        estado='procesado',
    ).order_by(ArchivoFichaVersion.version.desc()).first()

    if existente:
        return existente

    juicios = JuicioEvaluativo.query.filter_by(ficha_id=ficha.id).all()
    if not juicios:
        return None

    carpeta_relativa = f'fichas/{ficha.id}/{TIPO_REPORTE_JUICIOS}'
    directorio_destino = Path(current_app.config['UPLOAD_FOLDER']) / carpeta_relativa
    directorio_destino.mkdir(parents=True, exist_ok=True)

    archivo_origen = None
    candidatos = [
        Path('Reporte de Juicios Evaluativos.xls'),
        Path('Reporte de Juicios Evaluativos (28).xls'),
        Path('Reporte de Juicios Evaluativos.xlsx'),
    ]
    for cand in candidatos:
        if cand.is_file():
            try:
                with open(cand, 'rb') as fp:
                    fs = FileStorage(stream=io.BytesIO(fp.read()), filename=cand.name)
                    meta_cand = leer_metadata_archivo(fs)
                    if meta_cand.get('codigo_ficha') and str(meta_cand['codigo_ficha']).strip() == str(ficha.codigo).strip():
                        archivo_origen = cand
                        break
            except Exception:
                pass

    if archivo_origen:
        nombre_original = secure_filename(archivo_origen.name)
        nombre_disco = f'v1_{uuid4().hex}_{nombre_original}'
        ruta_absoluta = directorio_destino / nombre_disco
        shutil.copy2(archivo_origen, ruta_absoluta)
        with open(ruta_absoluta, 'rb') as fp:
            digest = hashlib.sha256(fp.read()).hexdigest()
        tamano = ruta_absoluta.stat().st_size
        with open(ruta_absoluta, 'rb') as fp:
            fs = FileStorage(stream=io.BytesIO(fp.read()), filename=nombre_original)
            meta = leer_metadata_archivo(fs)
    else:
        nombre_original = f'Reporte_de_Juicios_Evaluativos_{ficha.codigo}.xlsx'
        nombre_disco = f'v1_{uuid4().hex}_{nombre_original}'
        ruta_absoluta = directorio_destino / nombre_disco

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Juicios Evaluativos'
        ws.append(['Ficha de Caracterizacion:', ficha.codigo or ''])
        ws.append(['Codigo Programa:', ficha.codigo_programa or ''])
        ws.append(['Denominacion:', ficha.nombre_programa or ''])

        max_fecha = max((j.fecha_juicio for j in juicios if j.fecha_juicio), default=None)
        fecha_reporte_str = max_fecha.strftime('%Y-%m-%d') if max_fecha else (ficha.creado_en.strftime('%Y-%m-%d') if hasattr(ficha, 'creado_en') and ficha.creado_en else '')
        ws.append(['Fecha del Reporte:', fecha_reporte_str])
        ws.append(['Fecha Inicio:', ficha.fecha_inicio.strftime('%Y-%m-%d') if ficha.fecha_inicio else ''])
        ws.append(['Fecha Fin:', ficha.fecha_fin.strftime('%Y-%m-%d') if ficha.fecha_fin else ''])
        ws.append([])
        ws.append([
            'Tipo de Documento', 'Numero de Documento', 'Nombre', 'Apellidos',
            'Estado', 'Competencia', 'Resultado de Aprendizaje',
            'Juicio de Evaluacion', 'Fecha y Hora del Juicio Evaluativo',
            'Funcionario que Registro el Juicio Evaluativo'
        ])

        aprendices_map = {a.id: a for a in Aprendiz.query.filter_by(ficha_id=ficha.id).all()}
        for j in juicios:
            ap = aprendices_map.get(j.aprendiz_id)
            ws.append([
                getattr(ap, 'tipo_documento', 'CC') or 'CC',
                getattr(ap, 'documento', '') or '',
                getattr(ap, 'nombre', '') or '',
                getattr(ap, 'apellidos', '') or '',
                getattr(ap, 'estado', 'EN_FORMACION') or 'EN_FORMACION',
                j.competencia or '',
                j.resultado_aprendizaje or '',
                j.juicio or '',
                j.fecha_fuente_texto or (j.fecha_juicio.strftime('%d/%m/%Y %H:%M:%S') if j.fecha_juicio else ''),
                j.funcionario_registro or '',
            ])

        wb.save(ruta_absoluta)
        with open(ruta_absoluta, 'rb') as fp:
            digest = hashlib.sha256(fp.read()).hexdigest()
        tamano = ruta_absoluta.stat().st_size
        meta = {
            'codigo_ficha': ficha.codigo,
            'codigo_programa': ficha.codigo_programa,
            'nombre_programa': ficha.nombre_programa,
            'fecha_reporte': fecha_reporte_str,
            'fecha_inicio': ficha.fecha_inicio.strftime('%Y-%m-%d') if ficha.fecha_inicio else None,
            'fecha_fin': ficha.fecha_fin.strftime('%Y-%m-%d') if ficha.fecha_fin else None,
        }

    inst_id = instructor_id or ficha.instructor_id
    if not inst_id and ficha.instructores:
        inst_id = ficha.instructores[0].id
    if not inst_id:
        from app.models.instructor import Instructor
        primer_inst = Instructor.query.first()
        inst_id = primer_inst.id if primer_inst else 1

    aprendices_count = Aprendiz.query.filter_by(ficha_id=ficha.id).count()
    detalle = f'{aprendices_count} aprendices, {len(juicios)} juicios sincronizados'

    version = ArchivoFichaVersion(
        ficha_id=ficha.id,
        instructor_id=inst_id,
        tipo=TIPO_REPORTE_JUICIOS,
        version=1,
        nombre_archivo=nombre_original,
        ruta_archivo=f'{carpeta_relativa}/{nombre_disco}',
        hash_sha256=digest,
        tamano_bytes=tamano,
        estado='procesado',
        detalle=detalle,
        metadata_json=json.dumps(meta, ensure_ascii=False, default=str),
    )
    db.session.add(version)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        existente = ArchivoFichaVersion.query.filter_by(
            ficha_id=ficha.id,
            tipo=TIPO_REPORTE_JUICIOS,
            estado='procesado',
        ).order_by(ArchivoFichaVersion.version.desc()).first()
        if existente:
            return existente
        raise
    return version


def versiones_ficha(ficha_id, tipo=None):
    if tipo is None or tipo == TIPO_REPORTE_JUICIOS:
        if not ArchivoFichaVersion.query.filter_by(ficha_id=ficha_id, tipo=TIPO_REPORTE_JUICIOS).first():
            asegurar_version_reporte(ficha_id)
    consulta = ArchivoFichaVersion.query.filter_by(ficha_id=ficha_id)
    if tipo:
        consulta = consulta.filter_by(tipo=tipo)
    return consulta.order_by(
        ArchivoFichaVersion.tipo,
        ArchivoFichaVersion.version.desc(),
    ).all()


def ultima_version(ficha_id, tipo, solo_procesadas=False):
    consulta = ArchivoFichaVersion.query.filter_by(ficha_id=ficha_id, tipo=tipo)
    if solo_procesadas:
        consulta = consulta.filter(ArchivoFichaVersion.estado == 'procesado')
    res = consulta.order_by(ArchivoFichaVersion.version.desc()).first()
    if res is None and tipo == TIPO_REPORTE_JUICIOS:
        res = asegurar_version_reporte(ficha_id)
    return res


def ruta_version(version):
    raiz = Path(current_app.config['UPLOAD_FOLDER']).resolve()
    ruta = (raiz / version.ruta_archivo).resolve()
    try:
        ruta.relative_to(raiz)
    except ValueError as exc:
        raise FileNotFoundError(version.ruta_archivo) from exc
    if not ruta.is_file():
        raise FileNotFoundError(version.ruta_archivo)
    return raiz, ruta.relative_to(raiz)
