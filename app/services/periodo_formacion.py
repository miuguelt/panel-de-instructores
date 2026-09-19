"""Shared training dates: induction and teaching reach 100%; practice is separate."""

import calendar
from datetime import date, datetime, timedelta, timezone


def _restar_meses(fecha, meses):
    total = fecha.year * 12 + fecha.month - 1 - meses
    anio, mes0 = divmod(total, 12)
    mes = mes0 + 1
    return date(anio, mes, min(fecha.day, calendar.monthrange(anio, mes)[1]))


def _sin_fechas(inicio, fin):
    return {
        'configurado': False, 'porcentaje': 0, 'fase': 'sin_fechas',
        'fase_label': 'Fechas pendientes', 'inicio_lectiva': inicio,
        'fin_lectiva': None, 'inicio_productiva': None, 'fin_productiva': fin,
        'dias_transcurridos': 0, 'dias_totales': 0, 'dias_restantes': None,
        'dias_restantes_lectiva': None, 'meses_restantes_lectiva': None,
        'meses_restantes_total': None, 'porcentaje_lectiva': 0,
        'porcentaje_restante': 0.0,
        'mensaje': 'Configura fechas válidas que incluyan la etapa lectiva antes de la productiva.',
    }


def obtener_periodo_formacion(ficha, hoy=None):
    """Return one calendar for all time indicators and TyT milestone calculations."""
    hoy = hoy or datetime.now(timezone.utc)
    if isinstance(hoy, datetime):
        hoy = hoy.replace(tzinfo=hoy.tzinfo or timezone.utc)
        hoy = hoy.astimezone(timezone(timedelta(hours=-5))).date()
    inicio, fin = ficha.fecha_inicio, ficha.fecha_fin
    if not inicio or not fin or fin < inicio:
        return _sin_fechas(inicio, fin)
    meses = max(int(ficha.duracion_productiva_meses or 6), 1)
    productiva = _restar_meses(fin, meses)
    fin_lectiva = productiva - timedelta(days=1)
    if fin_lectiva < inicio:
        return _sin_fechas(inicio, fin)
    total = (fin_lectiva - inicio).days + 1
    transcurridos = max(0, min((hoy - inicio).days + 1, total))
    porcentaje = round(transcurridos / total * 100, 1)
    fase = ('por_iniciar' if hoy < inicio else 'lectiva' if hoy < productiva
            else 'productiva' if hoy <= fin else 'finalizada')
    nombres = {'por_iniciar': 'Por iniciar', 'lectiva': 'Etapa lectiva',
               'productiva': 'Etapa productiva', 'finalizada': 'Ficha finalizada'}
    dias_restantes = max(0, (fin - hoy).days)
    dias_restantes_lectiva = max(0, (fin_lectiva - hoy).days)
    meses_restantes_lectiva = round(dias_restantes_lectiva / 30.44, 1) if dias_restantes_lectiva else 0.0
    meses_restantes_total = round(dias_restantes / 30.44, 1) if dias_restantes else 0.0
    porcentaje_restante = max(0.0, round(100.0 - porcentaje, 1))

    return {
        'configurado': True, 'porcentaje': porcentaje, 'porcentaje_lectiva': porcentaje,
        'porcentaje_restante': porcentaje_restante,
        'fase': fase, 'fase_label': nombres[fase], 'inicio_lectiva': inicio,
        'fin_lectiva': fin_lectiva, 'inicio_productiva': productiva, 'fin_productiva': fin,
        'dias_transcurridos': transcurridos, 'dias_totales': total,
        'dias_restantes': dias_restantes,
        'dias_restantes_lectiva': dias_restantes_lectiva,
        'meses_restantes_lectiva': meses_restantes_lectiva,
        'meses_restantes_total': meses_restantes_total,
        'meses_productiva': meses,
        'mensaje': f'La etapa productiva dura {meses} meses y termina el {fin.strftime("%d/%m/%Y")}.',
    }
