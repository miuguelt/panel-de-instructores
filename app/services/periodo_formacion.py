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
        'dias_para_iniciar_lectiva': None,
        'dias_para_cerrar_ficha': None,
        'dias_cierre_ficha': None,
        'etapa_lectiva_iniciada': False,
        'etapa_lectiva_inicia_hoy': False,
        'ficha_cerrada': False,
        'ficha_cierra_hoy': False,
        'alerta_inicio_lectiva': {'activa': False, 'tipo': 'sin_fechas', 'nivel': 'normal', 'dias': None, 'mensaje': 'Sin fechas configuradas'},
        'alerta_cierre_ficha': {'activa': False, 'tipo': 'sin_fechas', 'nivel': 'normal', 'dias': None, 'mensaje': 'Sin fechas configuradas'},
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

    dias_para_iniciar_lectiva = (inicio - hoy).days
    etapa_lectiva_iniciada = hoy > inicio
    etapa_lectiva_inicia_hoy = hoy == inicio

    dias_cierre_ficha = (fin - hoy).days
    dias_para_cerrar_ficha = dias_cierre_ficha
    ficha_cerrada = hoy > fin
    ficha_cierra_hoy = hoy == fin

    # Alertas estructuradas para inicio de etapa lectiva
    if etapa_lectiva_inicia_hoy:
        alerta_inicio_lectiva = {
            'activa': True,
            'tipo': 'hoy',
            'nivel': 'urgente',
            'dias': 0,
            'mensaje': f'¡Hoy {inicio.strftime("%d/%m/%Y")} inicia la etapa lectiva!',
        }
    elif 1 <= dias_para_iniciar_lectiva <= 7:
        alerta_inicio_lectiva = {
            'activa': True,
            'tipo': 'inminente',
            'nivel': 'urgente',
            'dias': dias_para_iniciar_lectiva,
            'mensaje': f'Inicio inminente de etapa lectiva: faltan {dias_para_iniciar_lectiva} día{"s" if dias_para_iniciar_lectiva > 1 else ""} ({inicio.strftime("%d/%m/%Y")}).',
        }
    elif 8 <= dias_para_iniciar_lectiva <= 30:
        alerta_inicio_lectiva = {
            'activa': True,
            'tipo': 'proxima',
            'nivel': 'aviso',
            'dias': dias_para_iniciar_lectiva,
            'mensaje': f'Próximo inicio de etapa lectiva: faltan {dias_para_iniciar_lectiva} días ({inicio.strftime("%d/%m/%Y")}).',
        }
    else:
        alerta_inicio_lectiva = {
            'activa': False,
            'tipo': 'normal',
            'nivel': 'normal',
            'dias': dias_para_iniciar_lectiva,
            'mensaje': (
                f'Faltan {dias_para_iniciar_lectiva} días para iniciar la etapa lectiva.'
                if dias_para_iniciar_lectiva > 0
                else f'Etapa lectiva en curso (inició el {inicio.strftime("%d/%m/%Y")}).'
            ),
        }

    # Alertas estructuradas para cierre de ficha
    if ficha_cierra_hoy:
        alerta_cierre_ficha = {
            'activa': True,
            'tipo': 'hoy',
            'nivel': 'critico',
            'dias': 0,
            'mensaje': f'¡Hoy {fin.strftime("%d/%m/%Y")} es el cierre definitivo de la ficha!',
        }
    elif ficha_cerrada:
        alerta_cierre_ficha = {
            'activa': False,
            'tipo': 'cerrada',
            'nivel': 'normal',
            'dias': dias_cierre_ficha,
            'mensaje': f'Ficha finalizada el {fin.strftime("%d/%m/%Y")}.',
        }
    elif 1 <= dias_cierre_ficha <= 15:
        alerta_cierre_ficha = {
            'activa': True,
            'tipo': 'inminente',
            'nivel': 'critico',
            'dias': dias_cierre_ficha,
            'mensaje': f'¡Cierre inminente! Faltan {dias_cierre_ficha} día{"s" if dias_cierre_ficha > 1 else ""} para cerrar la ficha ({fin.strftime("%d/%m/%Y")}).',
        }
    elif 16 <= dias_cierre_ficha <= 45:
        alerta_cierre_ficha = {
            'activa': True,
            'tipo': 'proxima',
            'nivel': 'aviso',
            'dias': dias_cierre_ficha,
            'mensaje': f'Próximo cierre de ficha: faltan {dias_cierre_ficha} días ({fin.strftime("%d/%m/%Y")}).',
        }
    else:
        alerta_cierre_ficha = {
            'activa': False,
            'tipo': 'normal',
            'nivel': 'normal',
            'dias': dias_cierre_ficha,
            'mensaje': f'Faltan {dias_cierre_ficha} días para el cierre de la ficha ({fin.strftime("%d/%m/%Y")}).',
        }

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
        'dias_para_iniciar_lectiva': dias_para_iniciar_lectiva,
        'dias_para_cerrar_ficha': dias_para_cerrar_ficha,
        'dias_cierre_ficha': dias_cierre_ficha,
        'etapa_lectiva_iniciada': etapa_lectiva_iniciada,
        'etapa_lectiva_inicia_hoy': etapa_lectiva_inicia_hoy,
        'ficha_cerrada': ficha_cerrada,
        'ficha_cierra_hoy': ficha_cierra_hoy,
        'alerta_inicio_lectiva': alerta_inicio_lectiva,
        'alerta_cierre_ficha': alerta_cierre_ficha,
        'mensaje': f'La etapa productiva dura {meses} meses y termina el {fin.strftime("%d/%m/%Y")}.',
    }
