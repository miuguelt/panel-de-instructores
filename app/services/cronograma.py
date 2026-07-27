"""Cálculo y alertas del avance temporal de una ficha SENA."""

import calendar
from datetime import date, datetime, timedelta

from app import db
from app.models.alertas import Alerta, Notificacion
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.ficha_instructor import FichaInstructor
from app.services.alertas import registrar_notificacion


def _restar_meses(fecha, meses):
    total = fecha.year * 12 + fecha.month - 1 - meses
    año, mes0 = divmod(total, 12)
    mes = mes0 + 1
    return date(año, mes, min(fecha.day, calendar.monthrange(año, mes)[1]))


def obtener_cronograma(ficha, hoy=None):
    """Devuelve fechas y porcentaje sin inventar avance cuando faltan fechas."""
    hoy = hoy or date.today()
    inicio = ficha.fecha_inicio
    fin = ficha.fecha_fin
    if not inicio or not fin or fin < inicio:
        return {
            'configurado': False, 'porcentaje': 0, 'fase': 'sin_fechas',
            'inicio_lectiva': inicio, 'fin_lectiva': None,
            'inicio_productiva': None, 'fin_productiva': fin,
            'dias_transcurridos': 0, 'dias_totales': 0, 'dias_restantes': None,
            'porcentaje_lectiva': 0,
            'mensaje': 'Configura las fechas de inicio y finalización para ver el avance temporal.',
        }

    meses_productiva = max(int(ficha.duracion_productiva_meses or 6), 1)
    inicio_productiva = _restar_meses(fin, meses_productiva)
    fin_lectiva = inicio_productiva - timedelta(days=1)
    dias_totales = (fin - inicio).days + 1
    dias_transcurridos = max(0, min((hoy - inicio).days + 1, dias_totales))
    porcentaje = round(dias_transcurridos / dias_totales * 100, 1)
    dias_lectiva = max((fin_lectiva - inicio).days + 1, 0)
    if hoy < inicio:
        fase = 'por_iniciar'
    elif hoy < inicio_productiva:
        fase = 'lectiva'
    elif hoy <= fin:
        fase = 'productiva'
    else:
        fase = 'finalizada'
    dias_restantes = (fin - hoy).days if hoy <= fin else 0
    nombres = {
        'por_iniciar': 'Por iniciar', 'lectiva': 'Etapa lectiva',
        'productiva': 'Etapa productiva', 'finalizada': 'Ficha finalizada',
    }
    return {
        'configurado': True, 'porcentaje': porcentaje, 'fase': fase,
        'fase_label': nombres[fase], 'inicio_lectiva': inicio,
        'fin_lectiva': fin_lectiva, 'inicio_productiva': inicio_productiva,
        'fin_productiva': fin, 'dias_transcurridos': dias_transcurridos,
        'dias_totales': dias_totales, 'dias_restantes': dias_restantes,
        'porcentaje_lectiva': round(dias_lectiva / dias_totales * 100, 1),
        'meses_productiva': meses_productiva,
        'mensaje': f'La etapa productiva dura {meses_productiva} meses y termina el {fin.strftime("%d/%m/%Y")}.',
    }


def _instructores_ficha(ficha):
    ids = {ficha.instructor_id}
    ids.update(v.instructor_id for v in FichaInstructor.query.filter_by(ficha_id=ficha.id).all())
    return ids


def _alerta_ficha(ficha, tipo, nivel, titulo, mensaje, detalle, ahora):
    alerta = Alerta.query.filter_by(
        ficha_id=ficha.id, aprendiz_id=None, tipo=tipo, estado='activa'
    ).order_by(Alerta.fecha_generada.desc()).first()
    cambio = False
    if alerta:
        cambio = alerta.titulo != titulo or alerta.nivel != nivel
        alerta.titulo, alerta.mensaje, alerta.nivel, alerta.detalle_json = titulo, mensaje, nivel, detalle
    else:
        alerta = Alerta(ficha_id=ficha.id, aprendiz_id=None, tipo=tipo, nivel=nivel,
                        titulo=titulo, mensaje=mensaje, detalle_json=detalle, fecha_generada=ahora)
        db.session.add(alerta)
        db.session.flush()
        cambio = True
    if cambio:
        clave = f'cronograma:{ficha.id}:{tipo}:{nivel}'
        for instructor_id in _instructores_ficha(ficha):
            registrar_notificacion('instructor', instructor_id, mensaje, 'cronograma', clave,
                                   ficha.id, f'/instructor/fichas/{ficha.id}/alertas')
        for aprendiz in Aprendiz.query_en_formacion(ficha.id).all():
            registrar_notificacion('aprendiz', aprendiz.id, mensaje, 'cronograma', clave,
                                   ficha.id, f'/aprendiz/{ficha.id}/panel?documento={aprendiz.documento}')
    return alerta


def actualizar_alertas_cronograma(ficha_id, ahora=None):
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        return []
    ahora = ahora or datetime.utcnow()
    hoy = ahora.date()
    cronograma = obtener_cronograma(ficha, hoy)
    if not cronograma['configurado']:
        return []
    alertas = []
    inicio_productiva = cronograma['inicio_productiva']
    fin = cronograma['fin_productiva']
    dias_productiva = (inicio_productiva - hoy).days
    dias_fin = (fin - hoy).days
    if 0 <= dias_productiva <= 30:
        alertas.append(_alerta_ficha(
            ficha, 'cronograma_productiva', 'amarilla',
            'Se acerca el inicio de la etapa productiva',
            f'La etapa lectiva termina el {cronograma["fin_lectiva"].strftime("%d/%m/%Y")}. '
            f'La etapa productiva inicia el {inicio_productiva.strftime("%d/%m/%Y")} y dura {cronograma["meses_productiva"]} meses.',
            {'inicio_productiva': inicio_productiva.isoformat()}, ahora,
        ))
    if dias_fin < 0:
        alertas.append(_alerta_ficha(
            ficha, 'cronograma_fin', 'amarilla', 'La ficha ya finalizó',
            f'La ficha terminó el {fin.strftime("%d/%m/%Y")}. Conserva el histórico para las consultas y cierres pendientes.',
            {'fecha_fin': fin.isoformat(), 'fase': 'finalizada'}, ahora,
        ))
    elif 0 <= dias_fin <= 30:
        alertas.append(_alerta_ficha(
            ficha, 'cronograma_fin', 'amarilla', 'La ficha termina pronto',
            f'Faltan {dias_fin} día(s) para finalizar la ficha, el {fin.strftime("%d/%m/%Y")}. Revisa los cierres de la etapa productiva.',
            {'fecha_fin': fin.isoformat(), 'dias_restantes': dias_fin}, ahora,
        ))
    db.session.commit()
    return alertas
