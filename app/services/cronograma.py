"""Cálculo y alertas del avance temporal de una ficha SENA."""

from datetime import datetime

from app import db
from app.models.alertas import Alerta
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.ficha_instructor import FichaInstructor
from app.services.alertas import registrar_notificacion
from app.services.periodo_formacion import obtener_periodo_formacion as obtener_cronograma


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
    from app.tyt.avisos import actualizar_avisos
    actualizar_avisos(ficha, ahora=ahora)
    ahora = ahora or datetime.utcnow()
    hoy = ahora.date()
    cronograma = obtener_cronograma(ficha, hoy)
    if not cronograma['configurado']:
        return []
    alertas = []
    inicio_lectiva = cronograma['inicio_lectiva']
    inicio_productiva = cronograma['inicio_productiva']
    fin = cronograma['fin_productiva']

    dias_inicio = (inicio_lectiva - hoy).days
    dias_productiva = (inicio_productiva - hoy).days
    dias_fin = (fin - hoy).days

    # 1. Alerta por inicio de etapa lectiva
    if 0 <= dias_inicio <= 30:
        if dias_inicio == 0:
            tit_inicio = '¡Hoy inicia la etapa lectiva!'
            msg_inicio = f'¡Hoy {inicio_lectiva.strftime("%d/%m/%Y")} inicia la etapa lectiva de la ficha {ficha.codigo}! Alista la inducción y el recibimiento de aprendices.'
        elif dias_inicio <= 7:
            tit_inicio = 'Inicio inminente de la etapa lectiva'
            msg_inicio = f'Faltan solo {dias_inicio} día(s) para iniciar la etapa lectiva el {inicio_lectiva.strftime("%d/%m/%Y")}. Alista la planeación pedagógica y ambientes.'
        else:
            tit_inicio = 'Se acerca el inicio de la etapa lectiva'
            msg_inicio = f'Faltan {dias_inicio} días para iniciar la etapa lectiva el {inicio_lectiva.strftime("%d/%m/%Y")}.'
        alertas.append(_alerta_ficha(
            ficha, 'cronograma_inicio_lectiva', 'amarilla', tit_inicio, msg_inicio,
            {'inicio_lectiva': inicio_lectiva.isoformat(), 'dias_restantes': dias_inicio}, ahora,
        ))
    elif dias_inicio < 0:
        alerta_lectiva = Alerta.query.filter_by(
            ficha_id=ficha.id, aprendiz_id=None, tipo='cronograma_inicio_lectiva', estado='activa'
        ).first()
        if alerta_lectiva:
            alerta_lectiva.estado = 'resuelta'
            alerta_lectiva.fecha_resuelta = ahora

    # 2. Alerta por inicio de etapa productiva
    if 0 <= dias_productiva <= 30:
        alertas.append(_alerta_ficha(
            ficha, 'cronograma_productiva', 'amarilla',
            'Se acerca el inicio de la etapa productiva',
            f'La etapa lectiva termina el {cronograma["fin_lectiva"].strftime("%d/%m/%Y")}. '
            f'La etapa productiva inicia el {inicio_productiva.strftime("%d/%m/%Y")} y dura {cronograma["meses_productiva"]} meses.',
            {'inicio_productiva': inicio_productiva.isoformat()}, ahora,
        ))

    # 3. Alerta por cierre / finalización de ficha
    if dias_fin < 0:
        alertas.append(_alerta_ficha(
            ficha, 'cronograma_fin', 'amarilla', 'La ficha ya finalizó',
            f'La ficha terminó el {fin.strftime("%d/%m/%Y")}. Conserva el histórico para las consultas y cierres pendientes.',
            {'fecha_fin': fin.isoformat(), 'fase': 'finalizada'}, ahora,
        ))
    elif 0 <= dias_fin <= 30:
        if dias_fin == 0:
            tit_fin = '¡Hoy es el cierre de la ficha!'
            msg_fin = f'Hoy {fin.strftime("%d/%m/%Y")} finaliza la ficha {ficha.codigo}. Verifica los juicios evaluativos y el cierre de la etapa productiva.'
            nivel_fin = 'roja'
        elif dias_fin <= 15:
            tit_fin = 'Cierre inminente de la ficha'
            msg_fin = f'Faltan solo {dias_fin} día(s) para finalizar la ficha, el {fin.strftime("%d/%m/%Y")}. Revisa con urgencia las certificaciones y cierres pendientes.'
            nivel_fin = 'roja' if dias_fin <= 7 else 'amarilla'
        else:
            tit_fin = 'La ficha termina pronto'
            msg_fin = f'Faltan {dias_fin} día(s) para finalizar la ficha, el {fin.strftime("%d/%m/%Y")}. Revisa los cierres de la etapa productiva.'
            nivel_fin = 'amarilla'
        alertas.append(_alerta_ficha(
            ficha, 'cronograma_fin', nivel_fin, tit_fin, msg_fin,
            {'fecha_fin': fin.isoformat(), 'dias_restantes': dias_fin}, ahora,
        ))
    db.session.commit()
    return alertas
