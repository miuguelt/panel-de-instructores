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
from app.services.archivos import ArchivoDuplicado, ArchivoService, nombre_original_desde_ruta


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


def buscar_archivo_reporte_original(ficha):
    """Busca en el sistema de archivos un reporte original auténtico de SOFIA Plus para la ficha.

    Explora tanto las subcarpetas de almacenamiento (uploads/fichas, uploads/importaciones)
    como la raíz del proyecto para localizar archivos (.xls o .xlsx) cuyo código de ficha
    coincida con el de la ficha. Si existen varios, prioriza el más reciente según la fecha
    del reporte o la fecha de modificación del archivo.
    """
    import io
    from pathlib import Path
    from werkzeug.datastructures import FileStorage
    from app.services.importacion_ficha import leer_metadata_archivo

    codigo_objetivo = str(ficha.codigo or '').strip()
    if not codigo_objetivo:
        return None

    candidatos_rutas = []

    # 1. Dentro de UPLOAD_FOLDER (subcarpetas de fichas, importaciones, raíz de uploads)
    uploads_dir = Path(current_app.config.get('UPLOAD_FOLDER', 'uploads'))
    if uploads_dir.is_dir():
        for patron in ('*.xls', '*.xlsx'):
            for p in uploads_dir.rglob(patron):
                if p.is_file() and not p.name.endswith('.part'):
                    if f'Reporte_de_Juicios_Evaluativos_{codigo_objetivo}.xlsx' in p.name:
                        continue
                    candidatos_rutas.append(p)

    # 2. En la raíz del proyecto y directorio actual de ejecución
    raiz_proyecto = Path(current_app.root_path).parent
    for base in {Path.cwd(), raiz_proyecto}:
        if base.is_dir():
            for p in base.glob('Reporte*.xls*'):
                if p.is_file() and not p.name.endswith('.part'):
                    candidatos_rutas.append(p)

    candidatos_unicos = []
    vistos = set()
    for c in candidatos_rutas:
        try:
            c_res = c.resolve()
            if c_res not in vistos and c_res.is_file():
                vistos.add(c_res)
                candidatos_unicos.append(c_res)
        except OSError:
            continue

    coincidencias = []
    for cand in candidatos_unicos:
        try:
            with open(cand, 'rb') as fp:
                fs = FileStorage(stream=io.BytesIO(fp.read()), filename=cand.name)
                meta_cand = leer_metadata_archivo(fs)
                if meta_cand and meta_cand.get('codigo_ficha'):
                    if str(meta_cand['codigo_ficha']).strip() == codigo_objetivo:
                        coincidencias.append({
                            'path': cand,
                            'metadata': meta_cand,
                            'fecha_reporte': meta_cand.get('fecha_reporte'),
                            'mtime': cand.stat().st_mtime,
                        })
        except Exception:
            continue

    if not coincidencias:
        return None

    def _orden_clave(item):
        f = item['fecha_reporte']
        fecha_str = f.isoformat() if hasattr(f, 'isoformat') else (str(f) if f else '')
        return (fecha_str, item['mtime'])

    coincidencias.sort(key=_orden_clave, reverse=True)
    return coincidencias[0]


def asegurar_version_reporte(ficha_o_id, instructor_id=None):
    """Garantiza que una ficha con juicios evaluativos tenga su versión registrada.

    Si la ficha ya tiene una versión de reporte de juicios procesada y apunta a un
    archivo original existente, la retorna. Si la versión existente es una
    reconstrucción sintética o su archivo no está en disco y se encuentra el archivo
    original auténtico de SOFIA Plus, actualiza la versión con el archivo original.
    Si no tiene versión pero ya tiene juicios evaluativos en base de datos, localiza
    el archivo original auténtico o reconstruye la versión 1 y la retorna.
    """
    import io
    import shutil
    import openpyxl
    from werkzeug.datastructures import FileStorage
    from app.models.ficha import Ficha
    from app.models.juicio import JuicioEvaluativo
    from app.models.aprendiz import Aprendiz

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

    es_sintetico = False
    archivo_falta = False
    if existente:
        carpeta_uploads = Path(current_app.config['UPLOAD_FOLDER'])
        ruta_fisica = carpeta_uploads / existente.ruta_archivo
        archivo_falta = not ruta_fisica.is_file()
        es_sintetico = (
            existente.nombre_archivo == f'Reporte_de_Juicios_Evaluativos_{ficha.codigo}.xlsx'
            or (existente.nombre_archivo.startswith(f'Reporte_de_Juicios_Evaluativos_{ficha.codigo}') and existente.nombre_archivo.endswith('.xlsx'))
        )
        if not es_sintetico and not archivo_falta:
            return existente

    juicios = JuicioEvaluativo.query.filter_by(ficha_id=ficha.id).all()
    if not juicios and not existente:
        return None

    carpeta_relativa = f'fichas/{ficha.id}/{TIPO_REPORTE_JUICIOS}'
    directorio_destino = Path(current_app.config['UPLOAD_FOLDER']) / carpeta_relativa
    directorio_destino.mkdir(parents=True, exist_ok=True)

    match_original = buscar_archivo_reporte_original(ficha)

    if match_original:
        archivo_origen = match_original['path']
        meta = match_original['metadata']
        nombre_original = nombre_original_desde_ruta(archivo_origen.name)
        if not nombre_original or nombre_original == archivo_origen.name:
            nombre_original = secure_filename(archivo_origen.name)
        else:
            nombre_original = secure_filename(nombre_original)

        if archivo_origen.parent.resolve() == directorio_destino.resolve():
            nombre_disco = archivo_origen.name
            ruta_absoluta = archivo_origen
        else:
            num_ver = existente.version if existente else 1
            nombre_disco = f'v{num_ver}_{uuid4().hex}_{nombre_original}'
            ruta_absoluta = directorio_destino / nombre_disco
            shutil.copy2(archivo_origen, ruta_absoluta)

        with open(ruta_absoluta, 'rb') as fp:
            digest = hashlib.sha256(fp.read()).hexdigest()
        tamano = ruta_absoluta.stat().st_size
    elif existente and not archivo_falta:
        return existente
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

    aprendices_count = Aprendiz.query.filter_by(ficha_id=ficha.id).count() if juicios else 0
    detalle = f'{aprendices_count} aprendices, {len(juicios)} juicios sincronizados'

    if existente:
        existente.nombre_archivo = nombre_original
        existente.ruta_archivo = f'{carpeta_relativa}/{nombre_disco}'
        existente.tamano_bytes = tamano
        existente.hash_sha256 = digest
        existente.detalle = detalle
        existente.metadata_json = json.dumps(meta, ensure_ascii=False, default=str)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return existente

    inst_id = instructor_id or ficha.instructor_id
    if not inst_id and ficha.instructores:
        inst_id = ficha.instructores[0].id
    if not inst_id:
        from app.models.instructor import Instructor
        primer_inst = Instructor.query.first()
        inst_id = primer_inst.id if primer_inst else 1

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
        asegurar_version_reporte(ficha_id)
    consulta = ArchivoFichaVersion.query.filter_by(ficha_id=ficha_id)
    if tipo:
        consulta = consulta.filter_by(tipo=tipo)
    return consulta.order_by(
        ArchivoFichaVersion.tipo,
        ArchivoFichaVersion.version.desc(),
    ).all()


def ultima_version(ficha_id, tipo, solo_procesadas=False):
    if tipo == TIPO_REPORTE_JUICIOS:
        asegurar_version_reporte(ficha_id)
    consulta = ArchivoFichaVersion.query.filter_by(ficha_id=ficha_id, tipo=tipo)
    if solo_procesadas:
        consulta = consulta.filter(ArchivoFichaVersion.estado == 'procesado')
    return consulta.order_by(ArchivoFichaVersion.version.desc()).first()


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
