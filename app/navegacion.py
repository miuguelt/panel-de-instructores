"""Menú de módulos de la ficha definido como datos.

`modulos_ficha` devuelve los módulos principales (siempre visibles), los grupos
secundarios (panel «Más módulos») y el acceso a Alertas, que se muestra como un
distintivo con contador junto a «Visión general». La función se expone a las
plantillas mediante un ``context_processor`` para que la lógica viva en Python y
pueda probarse con pytest.
"""

import logging

from flask import url_for

log = logging.getLogger(__name__)

# Blueprints en los que se muestra la barra de la ficha.
BLUEPRINTS_CON_MENU = ('instructor', 'ranking', 'aseo', 'seguimiento', 'planeacion',
                       'grupos', 'atencion', 'tyt', 'comite')


def _modulo(label, icon, title, url, activo):
    return {'label': label, 'icon': icon, 'title': title, 'url': url, 'activo': bool(activo)}


def contar_alertas_activas(ficha_id):
    """Cantidad de alertas activas de la ficha; 0 si no se puede consultar."""
    try:
        from app.models.alertas import Alerta
        return Alerta.query.filter_by(ficha_id=ficha_id, estado='activa').count()
    except Exception:  # El menú nunca debe romper la página.
        log.warning('No se pudo contar alertas de la ficha %s.', ficha_id, exc_info=True)
        try:
            from app import db
            db.session.rollback()
        except Exception:
            pass
        return None


def modulos_ficha(ficha, endpoint, blueprint, corte_id=None, alertas=None):
    """Calcula el menú de la ficha.

    Devuelve un diccionario con:
    - ``principales``: módulos siempre visibles.
    - ``grupos``: grupos con título y módulos para «Más módulos».
    - ``activo_secundario``: módulo activo dentro de «Más módulos» (o None).
    - ``alertas``: acceso a Alertas con ``count`` (int o None).
    """
    ep = endpoint or ''
    fid = ficha.id
    principales = [
        _modulo('Visión general', 'layout-dashboard', 'Centro de mando de la ficha',
                url_for('instructor.vision_general', ficha_id=fid, corte_id=corte_id),
                ep == 'instructor.vision_general'),
        _modulo('Asistencia', 'clipboard-check', 'Llamado a lista y asistencia',
                url_for('instructor.asistencia', ficha_id=fid, corte_id=corte_id),
                ep == 'instructor.asistencia'),
        _modulo('Tareas', 'file-check', 'Tareas y evidencias',
                url_for('instructor.tareas', ficha_id=fid, corte_id=corte_id),
                ep in ('instructor.tareas', 'instructor.ver_entregas', 'instructor.evidencias_faltantes')),
        _modulo('Aprendices', 'users', 'Directorio de aprendices',
                url_for('instructor.aprendices', ficha_id=fid),
                ep in ('instructor.aprendices', 'instructor.historial_aprendiz',
                       'instructor.configuracion_aprendices')),
        _modulo('Juicios', 'graduation-cap', 'Juicios evaluativos y RAPs',
                url_for('instructor.juicios', ficha_id=fid), ep == 'instructor.juicios'),
        _modulo('Planeación', 'compass', 'Planeación pedagógica y línea de tiempo',
                url_for('planeacion.analisis', ficha_id=fid), blueprint == 'planeacion'),
        _modulo('Aseo', 'sparkles', 'Turnos de aseo del ambiente',
                url_for('aseo.turnos', ficha_id=fid), blueprint == 'aseo'),
    ]
    grupos = [
        {'titulo': 'Seguimiento y convivencia', 'modulos': [
            _modulo('Observador', 'book-open', 'Observador del aprendiz',
                    url_for('instructor.observador', ficha_id=fid), ep == 'instructor.observador'),
            _modulo('Casos de seguimiento', 'search-check', 'Casos y planes de mejoramiento',
                    url_for('seguimiento.casos_seguimiento', ficha_id=fid),
                    ep in ('seguimiento.casos_seguimiento', 'seguimiento.gestionar_planes')),
            _modulo('Novedades', 'briefcase', 'Novedades y etapa productiva',
                    url_for('comite.novedades_productiva', ficha_id=fid), ep == 'comite.novedades_productiva'),
            _modulo('Fila de atención', 'hand', 'Turnos de atención a aprendices',
                    url_for('atencion.fila_atencion', ficha_id=fid), blueprint == 'atencion'),
            _modulo('Seguimiento TyT', 'target', 'Preparación para las pruebas Saber TyT',
                    url_for('tyt.detalle', ficha_id=fid), blueprint == 'tyt'),
        ]},
        {'titulo': 'Recursos y participación', 'modulos': [
            _modulo('Estadísticas', 'bar-chart-3', 'Estadísticas y reportes',
                    url_for('instructor.estadisticas', ficha_id=fid), ep == 'instructor.estadisticas'),
            _modulo('Materiales', 'folder', 'Materiales de apoyo',
                    url_for('instructor.materiales', ficha_id=fid), ep == 'instructor.materiales'),
            _modulo('Ranking', 'trophy', 'Ranking de participación e insignias',
                    url_for('ranking.ranking', ficha_id=fid, corte_id=corte_id), blueprint == 'ranking'),
            _modulo('Grupos', 'users-2', 'Gestión de grupos y equipos',
                    url_for('grupos.listar_grupos', ficha_id=fid), blueprint == 'grupos'),
        ]},
    ]
    activo_secundario = next((m for g in grupos for m in g['modulos'] if m['activo']), None)
    alerta = _modulo('Alertas', 'alert-triangle', 'Alertas tempranas de riesgo',
                     url_for('instructor.alertas', ficha_id=fid),
                     ep in ('instructor.alertas', 'instructor.guardar_config_alertas'))
    alerta['count'] = alertas
    return {'principales': principales, 'grupos': grupos,
            'activo_secundario': activo_secundario, 'alertas': alerta}


def registrar(app):
    """Expone `modulos_ficha` a las plantillas."""

    @app.context_processor
    def inyectar_navegacion():
        from flask import request

        def nav_ficha(ficha, corte=None):
            if not ficha or request.blueprint not in BLUEPRINTS_CON_MENU:
                return None
            corte_id = getattr(corte, 'id', None) if corte else None
            return modulos_ficha(ficha, request.endpoint, request.blueprint, corte_id,
                                 alertas=contar_alertas_activas(ficha.id))

        return {'nav_ficha': nav_ficha, 'modulos_ficha': modulos_ficha}
