"""Prioridad de las fichas en «Mis fichas».

El instructor abre el panel para saber dónde actuar. Estas funciones puras
ordenan las fichas por urgencia y resumen sus pendientes con los datos que la
ruta ya calculó; no consultan la base de datos.
"""

from app.services.visualizacion import hito_urgente

ORDEN_FASE = {'lectiva': 1, 'por_iniciar': 2, 'productiva': 3, 'sin_fechas': 5, 'finalizada': 6}
PESO_ALERTA = 3
PESO_VENCIDAS = 2
PESO_DESFASE = 2
TOPE_POR_CALIFICAR = 10
PESO_HITO = {'danger': 5, 'warning': 2}

# (clave en estadísticas, singular, plural, estado, endpoint)
PENDIENTES = (
    ('alertas_activas', 'alerta activa', 'alertas activas', 'danger', 'instructor.alertas'),
    ('por_calificar', 'entrega por calificar', 'entregas por calificar', 'warning', 'instructor.tareas'),
    ('pendientes', 'entrega vencida sin recibir', 'entregas vencidas sin recibir', 'warning', 'instructor.tareas'),
    ('planes_pendientes', 'plan de mejoramiento abierto', 'planes de mejoramiento abiertos', 'info',
     'seguimiento.gestionar_planes'),
)


def _n(datos, clave):
    return int((datos or {}).get(clave) or 0)


def puntaje_urgencia(cronograma, extra, fases_data):
    """Puntaje de urgencia: más alto significa que la ficha requiere acción antes."""
    puntaje = (
        PESO_ALERTA * _n(extra, 'alertas_activas')
        + min(_n(extra, 'por_calificar'), TOPE_POR_CALIFICAR)
        + PESO_VENCIDAS * _n(extra, 'pendientes')
        + _n(extra, 'planes_pendientes')
        + PESO_DESFASE * max(_n(fases_data, 'desfase_fases'), 0)
    )
    hito = hito_urgente(cronograma)
    if hito:
        puntaje += PESO_HITO.get(hito['estado'], 0)
    return puntaje


def _finalizada(cronograma):
    return (cronograma or {}).get('fase') == 'finalizada'


def ordenar_por_urgencia(fichas, cronogramas, estadisticas_extra, fases_fichas):
    """Fichas activas por urgencia; empates por fase y código; finalizadas al final."""
    fases_fichas = fases_fichas or {}

    def clave(ficha):
        crono = cronogramas.get(ficha.id, {})
        return (
            _finalizada(crono),
            -puntaje_urgencia(crono, estadisticas_extra.get(ficha.id), fases_fichas.get(ficha.id)),
            ORDEN_FASE.get(crono.get('fase'), 99),
            str(ficha.codigo),
        )

    return sorted(fichas, key=clave)


def pendientes_de_hoy(extra):
    """Pendientes con valor, en orden de prioridad, con texto listo para leer."""
    items = []
    for clave, singular, plural, estado, endpoint in PENDIENTES:
        valor = _n(extra, clave)
        if valor:
            items.append({
                'clave': clave, 'valor': valor, 'estado': estado, 'endpoint': endpoint,
                'texto': f'{valor} {singular if valor == 1 else plural}',
            })
    return items


def resumen_global(fichas, cronogramas, estadisticas_extra):
    """Totales de las fichas activas para la franja «Hoy en tus fichas»."""
    activas = [f for f in fichas if not _finalizada(cronogramas.get(f.id))]
    cierres = 0
    for f in activas:
        hito = hito_urgente(cronogramas.get(f.id))
        if hito and hito['tipo'] == 'cierre' and hito['estado'] in ('danger', 'warning'):
            cierres += 1
    return {
        'activas': len(activas),
        'por_calificar': sum(_n(estadisticas_extra.get(f.id), 'por_calificar') for f in activas),
        'alertas': sum(_n(estadisticas_extra.get(f.id), 'alertas_activas') for f in activas),
        'cierres_proximos': cierres,
        'con_pendientes': sum(1 for f in activas if pendientes_de_hoy(estadisticas_extra.get(f.id))),
    }


ORDEN_NIVEL = {'rojo': 0, 'amarillo': 1, 'verde': 2}


def ordenar_por_riesgo(datos):
    """Aprendices de mayor a menor riesgo: nivel, faltas, tareas y apellido."""
    return sorted(datos, key=lambda d: (
        ORDEN_NIVEL.get(d.get('nivel'), 3),
        -(d.get('no_justificadas') or 0),
        -(d.get('tareas_pendientes') or 0),
        d['aprendiz'].apellidos or '',
    ))
