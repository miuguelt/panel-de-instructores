"""Servicio de recuperación y vinculación de planeaciones pedagógicas GFPI-F-134.

Localiza archivos de planeación originales en el almacenamiento local o reutiliza
la planeación oficial procesada de otra ficha con el mismo programa formativo.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, Optional

from flask import current_app
from werkzeug.datastructures import FileStorage

from app import db
from app.models.archivo_ficha import ArchivoFichaVersion, TIPO_PLANEACION
from app.models.ficha import Ficha
from app.services.planeacion import parsear_planeacion
from app.services.resultados_persistidos import guardar_contenido_documento
from app.services.archivos import resolver_archivo_subido
from app.services.versiones_archivos import (
    actualizar_estado,
    crear_version,
    ultima_version,
)


def buscar_archivo_planeacion_original(ficha: Ficha) -> Optional[Dict[str, Any]]:
    """Busca en el sistema de archivos un Excel de planeación GFPI-F-134 para la ficha."""
    codigo_prog = str(ficha.codigo_programa or '').strip()
    nombre_prog = str(ficha.nombre_programa or '').strip().lower()
    codigo_ficha = str(ficha.codigo or '').strip()

    candidatos_rutas = []
    uploads_dir = Path(current_app.config.get('UPLOAD_FOLDER', 'uploads'))
    if uploads_dir.is_dir():
        for patron in ('*GPFI*.xlsx', '*planeacion*.xlsx', '*Planeacion*.xlsx'):
            for p in uploads_dir.rglob(patron):
                if p.is_file() and not p.name.endswith('.part'):
                    partes = p.parts
                    if 'fichas' in partes:
                        idx = partes.index('fichas')
                        if idx + 1 < len(partes) and partes[idx + 1] != str(ficha.id):
                            continue
                    candidatos_rutas.append(p)

    if not current_app.config.get('TESTING'):
        raiz_proyecto = Path(current_app.root_path).parent
        for base in {Path.cwd(), raiz_proyecto}:
            if base.is_dir():
                for patron in ('*GPFI*.xlsx', '*planeacion*.xlsx', '*Planeacion*.xlsx'):
                    for p in base.glob(patron):
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
            contenido = parsear_planeacion(cand)
            meta = contenido.get('metadata', {})
            cand_cod_prog = str(meta.get('codigo_programa') or '').strip()
            cand_nom_prog = str(meta.get('nombre_programa') or '').strip().lower()
            cand_cod_ficha = str(meta.get('codigo_ficha') or '').strip()

            coincide = False
            if codigo_ficha and cand_cod_ficha == codigo_ficha:
                coincide = True
            elif codigo_prog and cand_cod_prog == codigo_prog:
                coincide = True
            elif nombre_prog and cand_nom_prog and (nombre_prog in cand_nom_prog or cand_nom_prog in nombre_prog):
                coincide = True

            if coincide:
                coincidencias.append({
                    'path': cand,
                    'contenido': contenido,
                    'metadata': meta,
                    'mtime': cand.stat().st_mtime,
                })
        except Exception:
            continue

    if not coincidencias:
        return None

    coincidencias.sort(key=lambda x: x['mtime'], reverse=True)
    return coincidencias[0]


def asegurar_version_planeacion(
    ficha_o_id: Any, instructor_id: Optional[int] = None,
) -> Optional[ArchivoFichaVersion]:
    """Garantiza que la ficha cuente con su planeación pedagógica procesada.

    Si no tiene versión propia, localiza el archivo en disco o la importa de una
    ficha del mismo programa formativo.
    """
    if isinstance(ficha_o_id, int):
        ficha = db.session.get(Ficha, ficha_o_id)
    else:
        ficha = ficha_o_id

    if not ficha:
        return None

    existente = ultima_version(ficha.id, TIPO_PLANEACION, solo_procesadas=True)
    if existente:
        return existente

    inst_id = instructor_id or ficha.instructor_id or 1

    # 1. Buscar archivo original en almacenamiento o raíz
    match_orig = buscar_archivo_planeacion_original(ficha)
    if match_orig:
        cand_path = match_orig['path']
        contenido = match_orig['contenido']
        try:
            with open(cand_path, 'rb') as fp:
                storage = FileStorage(stream=io.BytesIO(fp.read()), filename=cand_path.name)
                version = crear_version(storage, ficha.id, inst_id, TIPO_PLANEACION, permitir_existente=True)
                guardar_contenido_documento(version, contenido, 'planeacion-v1')
                actualizar_estado(
                    version,
                    'procesado',
                    detalle=f'Planeación pedagógica original recuperada automáticamente: {cand_path.name}',
                    metadata=contenido.get('metadata'),
                )
                db.session.commit()
                return version
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Fallo al crear versión recuperada de planeación para ficha %s', ficha.id)

    # 2. Reutilizar planeación procesada de otra ficha hermana con el mismo programa
    if ficha.codigo_programa:
        hermana = (
            ArchivoFichaVersion.query.join(Ficha, ArchivoFichaVersion.ficha_id == Ficha.id)
            .filter(
                Ficha.codigo_programa == ficha.codigo_programa,
                Ficha.id != ficha.id,
                ArchivoFichaVersion.tipo == TIPO_PLANEACION,
                ArchivoFichaVersion.estado == 'procesado',
            )
            .order_by(ArchivoFichaVersion.version.desc())
            .first()
        )
        if hermana:
            try:
                raiz, relativa, _ = resolver_archivo_subido(hermana.ruta_archivo)
                ruta_fisica = raiz / relativa
                if ruta_fisica.is_file():
                    with open(ruta_fisica, 'rb') as fp:
                        storage = FileStorage(stream=io.BytesIO(fp.read()), filename=hermana.nombre_archivo)
                        version = crear_version(storage, ficha.id, inst_id, TIPO_PLANEACION, permitir_existente=True)
                        contenido = parsear_planeacion(ruta_fisica)
                        guardar_contenido_documento(version, contenido, 'planeacion-v1')
                        actualizar_estado(
                            version,
                            'procesado',
                            detalle=f'Planeación pedagógica vinculada automáticamente desde la ficha hermana {hermana.ficha.codigo} ({ficha.codigo_programa})',
                            metadata=contenido.get('metadata'),
                        )
                        db.session.commit()
                        return version
            except Exception:
                db.session.rollback()
                current_app.logger.exception('Fallo al vincular planeación hermana para ficha %s', ficha.id)

    return None
