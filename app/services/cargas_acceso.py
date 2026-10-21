"""Destinos explícitos y permisos vigentes para cada transferencia."""

from urllib.parse import urlsplit

from flask import current_app, session
from flask_login import current_user
from werkzeug.exceptions import HTTPException

from app import db
from app.models import Aprendiz, Ficha, Tarea, RegistroAsistencia, PlanMejoramiento
from app.services.cargas_errores import ErrorCarga
from app.services.permisos import puede_gestionar_ficha


DOCUMENTOS = {
    'planeacion.cargar_planeacion': {'archivo_planeacion': {'xlsx'}},
    'planeacion.cargar_programa': {'archivo_programa': {'pdf'}},
    'planeacion.cargar_todo': {'archivo_planeacion': {'xlsx'}, 'archivo_programa': {'pdf'},
                              'archivo_juicios': {'xls', 'xlsx'}, 'archivo_reporte': {'xls', 'xlsx'},
                              'archivo': {'xls', 'xlsx'}},
    'instructor.cargar_excel': {'archivo': {'xls', 'xlsx'}},
    'instructor.importar_reporte_ficha': {'archivo': {'xls', 'xlsx'}},
}
ADJUNTOS = {
    'instructor.materiales': {'archivo'}, 'instructor.tareas': {'material_apoyo'},
    'instructor.editar_tarea': {'material_apoyo'},
    'aprendiz.adjuntar_soporte_inasistencia': {'soporte'},
    'aprendiz.subir_evidencia': {'archivo_evidencia'},
    'aprendiz.subir_evidencia_plan': {'archivo_evidencia_plan'},
}


def resolver_destino(destino, campo):
    if not isinstance(destino, str) or len(destino) > 500:
        raise ErrorCarga('destino_invalido', 'El destino de la carga no es válido.')
    url = urlsplit(destino)
    if url.netloc or url.scheme or not url.path.startswith('/') or url.path.startswith('//'):
        raise ErrorCarga('destino_invalido', 'Seleccione un formulario del panel para cargar el archivo.')
    try:
        endpoint, argumentos = current_app.url_map.bind('localhost').match(url.path, method='POST')
    except HTTPException as exc:
        raise ErrorCarga('destino_invalido', 'El formulario de destino ya no está disponible.', 404) from exc
    campos = DOCUMENTOS.get(endpoint) or ADJUNTOS.get(endpoint, set())
    if campo not in campos:
        raise ErrorCarga('campo_invalido', 'Este formulario no admite el archivo seleccionado.')
    return url.path, endpoint, argumentos


def autorizar(destino, campo):
    ruta, endpoint, argumentos = resolver_destino(destino, campo)
    ficha_id = argumentos.get('ficha_id')
    ficha = db.session.get(Ficha, ficha_id) if ficha_id else None
    if endpoint.startswith(('instructor.', 'planeacion.')):
        if not current_user.is_authenticated:
            raise ErrorCarga('sesion_vencida', 'Su sesión terminó. Ingrese de nuevo para continuar la carga.', 401, 'iniciar_sesion')
        if ficha_id and not puede_gestionar_ficha(ficha):
            raise ErrorCarga('sin_permiso', 'No tiene permiso para cargar archivos en esta ficha.', 403)
        if endpoint == 'instructor.editar_tarea':
            from app.services.tareas import obtener_tarea_gestionable
            if not obtener_tarea_gestionable(ficha_id, argumentos['tarea_id'])[1]:
                raise ErrorCarga('sin_permiso', 'No tiene permiso para editar esta tarea.', 403)
        return f'instructor:{current_user.id}', ruta, endpoint, argumentos
    documento = session.get('aprendiz_documento')
    if not documento or session.get('aprendiz_ficha_id') != ficha_id:
        raise ErrorCarga('sesion_vencida', 'Tu sesión terminó. Ingresa de nuevo a tu ficha para continuar.', 401, 'iniciar_sesion')
    aprendiz = Aprendiz.query.filter_by(documento=documento, ficha_id=ficha_id).first()
    if not aprendiz or not aprendiz.activo:
        raise ErrorCarga('sin_permiso', 'Ya no tienes acceso a esta ficha.', 403)
    if endpoint == 'aprendiz.subir_evidencia':
        tarea = db.session.get(Tarea, argumentos['tarea_id'])
        if not tarea or tarea.ficha_id != ficha_id or tarea.es_actividad_clase:
            raise ErrorCarga('actividad_no_disponible', 'Esta actividad no recibe archivos.', 403)
        if tarea.es_grupal:
            grupos = {grupo.id for grupo in aprendiz.grupos_asignados if grupo.activo}
            if not any(grupo.id in grupos for grupo in tarea.grupos):
                raise ErrorCarga('sin_permiso', 'Esta actividad no está asignada a tu grupo.', 403)
    elif endpoint == 'aprendiz.subir_evidencia_plan':
        plan = db.session.get(PlanMejoramiento, argumentos['plan_id'])
        if not plan or plan.ficha_id != ficha_id or plan.aprendiz_id != aprendiz.id or plan.estado != 'pendiente':
            raise ErrorCarga('actividad_no_disponible', 'Este plan ya no recibe evidencias.', 403)
    else:
        registro = db.session.get(RegistroAsistencia, argumentos['registro_id'])
        if not registro or registro.aprendiz_id != aprendiz.id or registro.sesion.ficha_id != ficha_id:
            raise ErrorCarga('sin_permiso', 'No encontramos esa inasistencia para tu ficha.', 403)
    return f'aprendiz:{aprendiz.id}', ruta, endpoint, argumentos


def extensiones(endpoint, campo):
    if endpoint in DOCUMENTOS:
        return DOCUMENTOS[endpoint][campo]
    return current_app.config['ALLOWED_EXTENSIONS']
