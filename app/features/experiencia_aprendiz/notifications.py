"""Agrupación de avisos sin borrar registros ni silenciar información de atención."""

from app.features.experiencia_aprendiz.context import fecha_colombiana


CATEGORIAS = {
    'alerta': ('Seguimiento', 'convivencia'),
    'advertencia': ('Seguimiento', 'convivencia'),
    'critica': ('Seguimiento', 'convivencia'),
    'tarea': ('Evidencias', 'evidencias'),
    'calificacion': ('Retroalimentación', 'evidencias'),
    'feedback': ('Retroalimentación', 'evidencias'),
    'justificacion': ('Asistencia', 'resumen'),
    'observador': ('Convivencia', 'convivencia'),
    'cronograma': ('Calendario', 'resumen'),
    'grupo': ('Tu grupo', 'grupo'),
    'logro': ('Reconocimientos', 'rendimiento'),
}
OPCIONALES = {'general', 'grupo', 'logro', 'resumen'}


def clasificar_notificacion(notificacion, ficha_id):
    """Usa tipos persistidos y un destino de sesión, sin copiar URLs con documentos."""
    categoria, seccion = CATEGORIAS.get(notificacion.tipo, ('Otros avisos', 'resumen'))
    return {
        'notificacion': notificacion,
        'fecha_local': fecha_colombiana(notificacion.fecha_creada),
        'categoria': categoria,
        'seccion': seccion,
        'importante': notificacion.tipo not in OPCIONALES,
        'destino': f'/aprendiz/{ficha_id}/panel#tab-{seccion}',
    }


def _agrupar(avisos):
    """Conserva el orden de recencia y reúne cada día y categoría sin duplicar avisos."""
    grupos = {}
    for aviso in avisos:
        fecha = aviso['fecha_local'].strftime('%d/%m/%Y')
        clave = (fecha, aviso['categoria'])
        if clave not in grupos:
            grupos[clave] = {'fecha': fecha, 'categoria': aviso['categoria'], 'avisos': []}
        grupos[clave]['avisos'].append(aviso)
    return list(grupos.values())


def organizar_notificaciones(notificaciones, modo, ficha_id):
    """Todos los avisos siguen consultables; los modos solo cambian la presentación."""
    modo = modo if modo in ('all', 'important', 'quiet') else 'all'
    avisos = sorted(
        [clasificar_notificacion(item, ficha_id) for item in notificaciones],
        key=lambda aviso: (aviso['fecha_local'].timestamp(), aviso['notificacion'].id),
        reverse=True,
    )
    importantes = [aviso for aviso in avisos if aviso['importante']]
    opcionales = [aviso for aviso in avisos if not aviso['importante']]
    return {
        'modo': modo,
        'total': len(avisos),
        'sin_leer': sum(not aviso['notificacion'].leida for aviso in avisos),
        'importantes': len(importantes),
        'opcionales': len(opcionales),
        'principales': _agrupar(avisos if modo == 'all' else importantes),
        'secundarios': _agrupar([] if modo == 'all' else opcionales),
    }
