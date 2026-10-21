"""Las cargas conservan archivos confirmados y revierten fallas de persistencia."""

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.datastructures import FileStorage, MultiDict

from app import db
from app.models import ArchivoFichaVersion, ImportacionJob, Tarea
from app.models.material import MaterialFicha
from app.models.archivo_ficha import TIPO_PLANEACION
from app.services.carga_documentos import procesar_carga_unificada
from app.services.importacion_jobs import ColaImportacionesNoDisponible
from app.services.versiones_archivos import crear_version
from tests import test_archivos as soporte
from tests import test_importacion_ficha as reportes
from tests.apoyo_planeacion import crear_planeacion_xlsx
from tests.apoyo_programa import crear_programa_pdf


@pytest.fixture
def contexto():
    caso = soporte.ArchivosTestCase()
    caso.setUp()
    try:
        yield caso
    finally:
        caso.tearDown()


def archivos(contexto):
    return sorted(p for p in Path(contexto.uploads.name).rglob('*') if p.is_file())


def test_material_fallido_revierte_registro_y_archivo(contexto):
    with patch('app.routes.instructor.db.session.commit', side_effect=SQLAlchemyError('sin conexión')):
        respuesta = contexto.cliente.post(
            f'/instructor/fichas/{contexto.ficha.id}/materiales',
            data={'archivo': (BytesIO(soporte.PDF), 'guia.pdf')},
        )
    assert respuesta.status_code == 302
    assert MaterialFicha.query.count() == 0
    assert archivos(contexto) == []
    with contexto.cliente.session_transaction() as sesion:
        assert any('No fue posible registrar el material' in m for _, m in sesion['_flashes'])


def test_tarea_fallida_limpia_material_nuevo(contexto):
    with patch('app.routes.instructor.db.session.commit', side_effect=SQLAlchemyError('sin conexión')):
        respuesta = contexto.cliente.post(
            f'/instructor/fichas/{contexto.ficha.id}/tareas',
            data={'titulo': 'Tarea con material', 'material_apoyo': (BytesIO(soporte.PDF), 'guia.pdf')},
        )
    assert respuesta.status_code == 302
    assert Tarea.query.count() == 0
    assert archivos(contexto) == []


def test_edicion_fallida_conserva_material_anterior(contexto):
    respuesta = contexto.cliente.post(
        f'/instructor/fichas/{contexto.ficha.id}/tareas',
        data={'titulo': 'Tarea original', 'material_apoyo': (BytesIO(soporte.PDF), 'anterior.pdf')},
    )
    assert respuesta.status_code == 302
    tarea = Tarea.query.one()
    anterior = tarea.material_apoyo_url
    archivos_antes = archivos(contexto)
    with patch('app.routes.instructor.db.session.commit', side_effect=SQLAlchemyError('sin conexión')):
        respuesta = contexto.cliente.post(
            f'/instructor/fichas/{contexto.ficha.id}/tareas/{tarea.id}/editar',
            data={'titulo': 'Nuevo título', 'material_apoyo': (BytesIO(soporte.PDF), 'nuevo.pdf')},
        )
    assert respuesta.status_code == 302
    db.session.refresh(tarea)
    assert tarea.titulo == 'Tarea original'
    assert tarea.material_apoyo_url == anterior
    assert archivos(contexto) == archivos_antes


def test_carga_unificada_no_borra_una_version_reutilizada(contexto):
    contexto.ficha.codigo_programa = '228118'
    contexto.ficha.nombre_programa = 'Tecnólogo en Analisis y Desarrollo de Software'
    db.session.commit()
    contenido = crear_planeacion_xlsx(contexto.uploads.name).read_bytes()
    original = crear_version(FileStorage(BytesIO(contenido), filename='plan.xlsx'), contexto.ficha.id,
                             contexto.instructor.id, TIPO_PLANEACION)
    db.session.commit()
    ruta = Path(contexto.uploads.name) / original.ruta_archivo
    ok, mensaje, estado = procesar_carga_unificada(contexto.ficha, contexto.instructor.id, MultiDict({
        'archivo_planeacion': FileStorage(BytesIO(contenido), filename='plan.xlsx'),
        'archivo_programa': FileStorage(BytesIO(b'no corresponde'), filename='programa.txt'),
    }))
    assert ok is False and estado == 422
    assert 'formato .pdf' in mensaje
    assert ArchivoFichaVersion.query.count() == 1
    assert ruta.read_bytes() == contenido


def test_flush_de_version_fallido_no_deja_archivo_huerfano(contexto):
    with patch('app.services.versiones_archivos.db.session.flush', side_effect=SQLAlchemyError('fallo')):
        with pytest.raises(SQLAlchemyError):
            crear_version(FileStorage(BytesIO(b'contenido'), filename='plan.xlsx'), contexto.ficha.id,
                          contexto.instructor.id, TIPO_PLANEACION)
    db.session.rollback()
    assert archivos(contexto) == []


def test_recalculo_fallido_conserva_planeacion_confirmada(contexto):
    contexto.ficha.codigo_programa = '228118'
    contexto.ficha.nombre_programa = 'Tecnólogo en Analisis y Desarrollo de Software'
    db.session.commit()
    contenido = crear_planeacion_xlsx(contexto.uploads.name).read_bytes()
    with patch('app.routes.planeacion.encolar_recalculo_resumen', side_effect=RuntimeError('sin cola')):
        respuesta = contexto.cliente.post(
            f'/instructor/fichas/{contexto.ficha.id}/planeacion/cargar',
            data={'archivo_planeacion': (BytesIO(contenido), 'plan.xlsx')},
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
    assert respuesta.status_code == 200
    assert respuesta.json['ok'] is True
    version = ArchivoFichaVersion.query.one()
    assert (Path(contexto.uploads.name) / version.ruta_archivo).read_bytes() == contenido
    assert 'guardada' in respuesta.json['message']


def test_cola_caida_informa_error_y_preserva_reporte(contexto):
    contexto.ficha.codigo = '2672089'
    contexto.ficha.codigo_ficha = '2672089'
    contexto.ficha.codigo_programa = '228117'
    contexto.ficha.nombre_programa = 'Programa'
    contexto.app.config['IMPORTACIONES_ASINCRONAS'] = True
    db.session.commit()
    archivo = reportes.ImportacionFichaTestCase()._archivo()
    with patch('app.services.carga_documentos.encolar_importacion', side_effect=ColaImportacionesNoDisponible('sin cola')):
        ok, mensaje, estado = procesar_carga_unificada(contexto.ficha, contexto.instructor.id,
                                                      MultiDict({'archivo_juicios': archivo}))
    assert ok is False and estado == 503
    assert 'no pudo iniciarse' in mensaje
    version = ArchivoFichaVersion.query.one()
    assert (Path(contexto.uploads.name) / version.ruta_archivo).is_file()
    assert ImportacionJob.query.one().estado == 'error'
    assert list((Path(contexto.uploads.name) / 'importaciones').glob('*')) == []


def test_planeacion_delega_un_solo_envio_al_control_comun():
    contenido = Path('app/templates/instructor/planeacion.html').read_text(encoding='utf-8')
    assert 'xhr.send(formData)' not in contenido


def test_tarea_confirmada_informa_falla_de_indicadores(contexto):
    with patch('app.routes.instructor.actualizar_alertas_ficha', side_effect=RuntimeError('sin alertas')):
        respuesta = contexto.cliente.post(
            f'/instructor/fichas/{contexto.ficha.id}/tareas',
            data={'titulo': 'Tarea durable', 'material_apoyo': (BytesIO(soporte.PDF), 'guia.pdf')},
        )
    assert respuesta.status_code == 302
    tarea = Tarea.query.one()
    assert (Path(contexto.uploads.name) / tarea.material_apoyo_url).read_bytes() == soporte.PDF
    with contexto.cliente.session_transaction() as sesion:
        assert any('indicadores' in m and c == 'warning' for c, m in sesion['_flashes'])


def test_importacion_advierte_si_falla_el_respaldo_original(contexto):
    archivo = reportes.ImportacionFichaTestCase()._archivo()
    with patch('app.routes.instructor.crear_version', side_effect=SQLAlchemyError('sin respaldo')):
        respuesta = contexto.cliente.post(
            '/instructor/fichas/importar-reporte',
            data={'archivo': (archivo.stream, archivo.filename)},
        )
    assert respuesta.status_code == 302
    with contexto.cliente.session_transaction() as sesion:
        assert any('reporte original' in m and c == 'warning' for c, m in sesion['_flashes'])


def test_commit_asincrono_fallido_limpia_copia_y_version(contexto):
    contexto.ficha.codigo = '2672089'
    contexto.ficha.codigo_ficha = '2672089'
    contexto.ficha.codigo_programa = '228117'
    contexto.ficha.nombre_programa = 'Programa'
    contexto.app.config['IMPORTACIONES_ASINCRONAS'] = True
    db.session.commit()
    archivo = reportes.ImportacionFichaTestCase()._archivo()
    with patch('app.services.carga_documentos.db.session.commit', side_effect=SQLAlchemyError('sin conexión')):
        ok, mensaje, estado = procesar_carga_unificada(contexto.ficha, contexto.instructor.id,
                                                      MultiDict({'archivo_juicios': archivo}))
    assert ok is False and estado == 500
    assert ArchivoFichaVersion.query.count() == ImportacionJob.query.count() == 0
    assert archivos(contexto) == []


def test_reporte_confirmado_se_conserva_si_falla_el_ranking(contexto):
    contexto.ficha.codigo = '2672089'
    contexto.ficha.codigo_ficha = '2672089'
    contexto.ficha.codigo_programa = '228117'
    contexto.ficha.nombre_programa = 'Programa'
    db.session.commit()
    archivo = reportes.ImportacionFichaTestCase()._archivo()
    with patch('app.services.carga_documentos.actualizar_participacion_ficha', side_effect=RuntimeError('sin ranking')):
        ok, mensaje, estado = procesar_carga_unificada(contexto.ficha, contexto.instructor.id,
                                                      MultiDict({'archivo_juicios': archivo}))
    assert ok is True and estado == 200
    assert 'indicadores' in mensaje
    version = ArchivoFichaVersion.query.one()
    assert (Path(contexto.uploads.name) / version.ruta_archivo).is_file()


def test_importacion_reutilizada_no_borra_el_original_ante_error(contexto):
    contexto.ficha.codigo = '2672089'
    contexto.ficha.codigo_ficha = '2672089'
    contexto.ficha.codigo_programa = '228117'
    contexto.ficha.nombre_programa = 'Programa'
    db.session.commit()
    contenido = reportes.ImportacionFichaTestCase()._archivo().read()
    respuesta = contexto.cliente.post(
        f'/instructor/fichas/{contexto.ficha.id}/cargar-excel',
        data={'archivo': (BytesIO(contenido), 'reporte.xlsx')},
    )
    assert respuesta.status_code == 302
    version = ArchivoFichaVersion.query.one()
    ruta_original = Path(contexto.uploads.name) / version.ruta_archivo
    with patch('app.routes.instructor.importar_archivo', side_effect=RuntimeError('fallo de procesamiento')):
        respuesta = contexto.cliente.post(
            f'/instructor/fichas/{contexto.ficha.id}/cargar-excel',
            data={'archivo': (BytesIO(contenido), 'reporte.xlsx')},
        )
    assert respuesta.status_code == 302
    assert ArchivoFichaVersion.query.count() == 1
    assert ruta_original.read_bytes() == contenido


def test_indicadores_fallidos_no_invalidan_edicion_confirmada(contexto):
    respuesta = contexto.cliente.post(
        f'/instructor/fichas/{contexto.ficha.id}/tareas',
        data={'titulo': 'Tarea inicial', 'material_apoyo': (BytesIO(soporte.PDF), 'anterior.pdf')},
    )
    assert respuesta.status_code == 302
    tarea = Tarea.query.one()
    with patch('app.routes.instructor.actualizar_participacion_ficha', side_effect=RuntimeError('sin ranking')):
        respuesta = contexto.cliente.post(
            f'/instructor/fichas/{contexto.ficha.id}/tareas/{tarea.id}/editar',
            data={'titulo': 'Tarea final', 'material_apoyo': (BytesIO(soporte.PDF), 'nuevo.pdf')},
        )
    assert respuesta.status_code == 302
    db.session.refresh(tarea)
    assert tarea.titulo == 'Tarea final'
    assert (Path(contexto.uploads.name) / tarea.material_apoyo_url).is_file()
    assert len(archivos(contexto)) == 1


@pytest.mark.parametrize('tipo', ['planeacion', 'programa'])
def test_resumen_en_error_se_informa_sin_perder_documento(contexto, tipo):
    contexto.ficha.codigo_programa = '228118'
    contexto.ficha.nombre_programa = 'Tecnólogo en Analisis y Desarrollo de Software'
    db.session.commit()
    if tipo == 'planeacion':
        ruta = crear_planeacion_xlsx(contexto.uploads.name)
        campo, destino = 'archivo_planeacion', 'cargar'
    else:
        ruta = crear_programa_pdf(contexto.uploads.name)
        campo, destino = 'archivo_programa', 'programa'
    contenido = ruta.read_bytes()
    with patch('app.services.importacion_jobs.encolar_importacion', side_effect=ColaImportacionesNoDisponible('cola no disponible')):
        respuesta = contexto.cliente.post(
            f'/instructor/fichas/{contexto.ficha.id}/planeacion/{destino}',
            data={campo: (BytesIO(contenido), ruta.name)},
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
    assert respuesta.status_code == 200 and respuesta.json['ok'] is True
    assert 'indicadores' in respuesta.json['message']
    trabajo = ImportacionJob.query.filter_by(tipo_trabajo='resumen_ficha').one()
    assert trabajo.estado == 'error'
    assert trabajo.error == 'cola no disponible'
    version = ArchivoFichaVersion.query.one()
    assert version.estado == 'procesado'
    assert (Path(contexto.uploads.name) / version.ruta_archivo).read_bytes() == contenido


def test_carga_unificada_informa_resumen_en_error_con_documento_conservado(contexto):
    contexto.ficha.codigo_programa = '228118'
    contexto.ficha.nombre_programa = 'Tecnólogo en Analisis y Desarrollo de Software'
    db.session.commit()
    contenido = crear_planeacion_xlsx(contexto.uploads.name).read_bytes()
    with patch('app.services.importacion_jobs.encolar_importacion', side_effect=ColaImportacionesNoDisponible('cola no disponible')):
        ok, mensaje, estado = procesar_carga_unificada(contexto.ficha, contexto.instructor.id,
            MultiDict({'archivo_planeacion': FileStorage(BytesIO(contenido), filename='plan.xlsx')}))
    assert ok is True and estado == 200
    assert 'indicadores' in mensaje
    trabajo = ImportacionJob.query.filter_by(tipo_trabajo='resumen_ficha').one()
    assert trabajo.estado == 'error'
    assert trabajo.error == 'cola no disponible'
    version = ArchivoFichaVersion.query.one()
    assert (Path(contexto.uploads.name) / version.ruta_archivo).read_bytes() == contenido


def test_resumen_sin_trabajo_nuevo_no_se_reporta_como_falla(contexto):
    contexto.ficha.codigo_programa = '228118'
    contexto.ficha.nombre_programa = 'Tecnólogo en Analisis y Desarrollo de Software'
    db.session.commit()
    contenido = crear_planeacion_xlsx(contexto.uploads.name).read_bytes()
    with patch('app.routes.planeacion.encolar_recalculo_resumen', return_value=None):
        respuesta = contexto.cliente.post(
            f'/instructor/fichas/{contexto.ficha.id}/planeacion/cargar',
            data={'archivo_planeacion': (BytesIO(contenido), 'plan.xlsx')},
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
    assert respuesta.status_code == 200 and respuesta.json['ok'] is True
    assert 'indicadores' not in respuesta.json['message']
    assert ArchivoFichaVersion.query.one().estado == 'procesado'
