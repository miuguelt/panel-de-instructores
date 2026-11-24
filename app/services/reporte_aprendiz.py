"""Resúmenes del reporte integral del aprendiz que consulta el instructor.

Funciones puras sobre registros ya cargados: asistencia detallada por mes,
estado de las evidencias, seguimiento (alertas y planes) y última actividad.
"""

from collections import defaultdict
from datetime import datetime

ESTADOS_ASISTENCIA = (
    ('ASISTE', 'Asistió', 'success'),
    ('TARDANZA', 'Tardanza', 'warning'),
    ('FALTA', 'Falta injustificada', 'danger'),
    ('FALTA_JUSTIFICADA', 'Falta justificada', 'info'),
    ('EXCUSA_MEDICA', 'Excusa médica', 'info'),
    ('SIN_REGISTRO', 'Sin registro', 'secondary'),
)
CAMPO_MENSUAL = {'ASISTE': 'asistio', 'TARDANZA': 'tardanzas', 'FALTA': 'faltas',
                 'FALTA_JUSTIFICADA': 'justificadas', 'EXCUSA_MEDICA': 'justificadas'}


def detalle_asistencia(registros):
    """Conteo por estado, resumen mensual (del más reciente al más antiguo) y detalle de cada registro."""
    estados = {clave: {'label': etiqueta, 'count': 0, 'tone': tono} for clave, etiqueta, tono in ESTADOS_ASISTENCIA}
    mensual = defaultdict(lambda: {'total': 0, 'asistio': 0, 'tardanzas': 0, 'faltas': 0, 'justificadas': 0})
    for registro in registros:
        # Un estado desconocido no se presume falta injustificada.
        estado = registro.estado if registro.estado in estados else 'SIN_REGISTRO'
        estados[estado]['count'] += 1
        if registro.sesion and registro.sesion.fecha:
            mes = mensual[registro.sesion.fecha.strftime('%Y-%m')]
            mes['total'] += 1
            if estado in CAMPO_MENSUAL:
                mes[CAMPO_MENSUAL[estado]] += 1
    # Mismo criterio que el resto de la app: solo la falta sin justificar resta.
    for mes in mensual.values():
        mes['pct'] = round((mes['total'] - mes['faltas']) / mes['total'] * 100)
    return {
        'estados': estados,
        'mensual': sorted(mensual.items(), reverse=True),
        'registros': [{
            'fecha': r.sesion.fecha if r.sesion else None,
            'estado': r.estado,
            'causal': r.causal_justificacion,
            'nota': r.nota,
            'soporte': bool(r.soporte_url),
            'observaciones_sesion': r.sesion.observaciones if r.sesion else None,
        } for r in registros],
        'faltas_injustificadas': estados['FALTA']['count'],
        'faltas_justificadas': estados['FALTA_JUSTIFICADA']['count'] + estados['EXCUSA_MEDICA']['count'],
    }


def _numero(valor):
    try:
        return float(str(valor).replace(',', '.'))
    except (TypeError, ValueError):
        return None


def resumir_evidencias(items):
    """Totales por estado, promedio de calificaciones numéricas y porcentajes de entrega."""
    total = len(items)
    cuenta = lambda estado: sum(1 for item in items if item['estado'] == estado)  # noqa: E731
    calificaciones = [n for n in (_numero(i['entrega'].calificacion) for i in items
                                  if i['entrega'] and i['entrega'].calificacion) if n is not None]
    entregas = sum(1 for item in items if item['entrega'])
    a_tiempo = cuenta('entregada')
    return {
        'total': total, 'entregas': entregas, 'a_tiempo': a_tiempo, 'retrasos': cuenta('retraso'),
        'pendientes': cuenta('pendiente'), 'vencidas': cuenta('vencida'), 'correcciones': cuenta('correccion'),
        'calificadas': sum(1 for item in items if item['entrega'] and item['entrega'].calificada),
        'promedio': round(sum(calificaciones) / len(calificaciones), 2) if calificaciones else None,
        'pct_entrega': round(entregas / total * 100) if total else 0,
        'pct_a_tiempo': round(a_tiempo / total * 100) if total else 0,
    }


def resumir_seguimiento(alertas, planes):
    """Alertas y planes de mejoramiento por estado."""
    return {
        'alertas_total': len(alertas),
        'alertas_activas': sum(a.estado == 'activa' for a in alertas),
        'alertas_rojas': sum(a.nivel == 'roja' and a.estado in ('activa', 'escalada_comite') for a in alertas),
        'alertas_resueltas': sum(a.estado == 'resuelta' for a in alertas),
        'planes_total': len(planes),
        'planes_pendientes': sum(p.estado == 'pendiente' for p in planes),
        'planes_cumplidos': sum(p.estado == 'cumplido' for p in planes),
        'planes_vencidos': sum(p.estado == 'vencido' for p in planes),
    }


def ultima_actividad(*fechas):
    """La fecha más reciente entre evaluaciones, asistencia y entregas (fechas o fechas con hora)."""
    normalizadas = [f if isinstance(f, datetime) else datetime.combine(f, datetime.min.time()) for f in fechas if f]
    return max(normalizadas, default=None)
