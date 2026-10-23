"""Alta voluntaria y despacho de avisos Web Push para aprendices."""

import json
import base64
import binascii
import hashlib
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from flask import current_app

from app import db
from app.helpers import utc_now
from app.models.alertas import Notificacion, PushDispatch, PushSubscription


_DOMINIOS_PUSH = (
    'push.services.mozilla.com',
    'push.apple.com',
    'notify.windows.com',
    'fcm.googleapis.com',
)
_BASE64URL = re.compile(r'^[A-Za-z0-9_-]+$')
_TIPOS_EVALUACION = {'calificacion', 'juicio_evaluativo'}
_MAX_INTENTOS = 6


def validar_endpoint(endpoint):
    """Acepta solo endpoints HTTPS de proveedores conocidos de Web Push."""
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > 2048:
        return False
    try:
        partes = urlsplit(endpoint)
        dominio = (partes.hostname or '').lower().rstrip('.')
        puerto = partes.port
    except ValueError:
        return False
    if partes.scheme != 'https' or not dominio or partes.username or partes.password:
        return False
    if puerto not in (None, 443) or not partes.path.startswith('/'):
        return False
    return any(dominio == raiz or dominio.endswith('.' + raiz) for raiz in _DOMINIOS_PUSH)


def validar_datos_suscripcion(datos):
    """Valida el formato del navegador antes de guardar una suscripción."""
    if not isinstance(datos, dict) or not validar_endpoint(datos.get('endpoint')):
        raise ValueError('El navegador envió un endpoint Web Push no admitido.')
    claves = datos.get('keys')
    if not isinstance(claves, dict):
        raise ValueError('La suscripción no contiene sus claves de cifrado.')
    p256dh = claves.get('p256dh')
    auth = claves.get('auth')
    if (not isinstance(p256dh, str) or not 40 <= len(p256dh) <= 100
            or not _BASE64URL.fullmatch(p256dh)):
        raise ValueError('La clave pública de la suscripción no es válida.')
    if (not isinstance(auth, str) or not 16 <= len(auth) <= 100
            or not _BASE64URL.fullmatch(auth)):
        raise ValueError('La clave de autenticación de la suscripción no es válida.')
    try:
        clave_publica = base64.urlsafe_b64decode(p256dh + '=' * ((4 - len(p256dh) % 4) % 4))
        clave_autenticacion = base64.urlsafe_b64decode(auth + '=' * ((4 - len(auth) % 4) % 4))
    except (ValueError, binascii.Error) as error:
        raise ValueError('Las claves de la suscripción no están codificadas correctamente.') from error
    if len(clave_publica) != 65 or clave_publica[0] != 4 or len(clave_autenticacion) != 16:
        raise ValueError('Las claves de la suscripción no tienen el formato esperado.')
    return datos['endpoint'], p256dh, auth


def configuracion_push_disponible():
    """Indica si el envío fue activado y cuenta con las claves VAPID requeridas."""
    return bool(
        current_app.config.get('WEB_PUSH_ENABLED')
        and not current_app.config.get('SECRET_KEY_IS_EPHEMERAL', False)
        and current_app.config.get('VAPID_PUBLIC_KEY')
        and current_app.config.get('VAPID_PRIVATE_KEY')
        and current_app.config.get('VAPID_SUBJECT')
    )


def registrar_suscripcion(aprendiz, ficha_id, datos):
    """Vincula el endpoint validado con el aprendiz de la sesión actual."""
    if not configuracion_push_disponible():
        raise RuntimeError('Los avisos del navegador todavía no están habilitados.')
    endpoint, p256dh, auth = validar_datos_suscripcion(datos)
    huella_endpoint = hashlib.sha256(endpoint.encode('utf-8')).hexdigest()
    existente = PushSubscription.query.filter_by(endpoint_hash=huella_endpoint).first()
    if existente and (existente.aprendiz_id != aprendiz.id or existente.ficha_id != ficha_id):
        raise PermissionError('Esta suscripción ya está vinculada a otra sesión.')
    if existente:
        existente.p256dh = p256dh
        existente.auth = auth
        existente.actualizada_en = utc_now()
        suscripcion = existente
    else:
        suscripcion = PushSubscription(
            aprendiz_id=aprendiz.id, ficha_id=ficha_id,
            endpoint=endpoint, p256dh=p256dh, auth=auth,
        )
        db.session.add(suscripcion)
    db.session.commit()
    return suscripcion


def retirar_suscripcion(aprendiz, ficha_id, endpoint):
    """Retira únicamente el endpoint que pertenece a la sesión del aprendiz."""
    if not validar_endpoint(endpoint):
        return False
    suscripcion = PushSubscription.query.filter_by(
        endpoint_hash=hashlib.sha256(endpoint.encode('utf-8')).hexdigest(),
        aprendiz_id=aprendiz.id, ficha_id=ficha_id,
    ).first()
    if not suscripcion:
        return False
    db.session.delete(suscripcion)
    db.session.commit()
    return True


def encolar_push(notificacion):
    """Añade un despacho al buzón solo cuando existe una suscripción activa."""
    if (notificacion.tipo not in _TIPOS_EVALUACION
            or not configuracion_push_disponible()):
        return None
    suscripciones = PushSubscription.query.filter_by(
        aprendiz_id=notificacion.destinatario_id,
        ficha_id=notificacion.ficha_id,
    ).all()
    despachos = []
    for suscripcion in suscripciones:
        despacho = PushDispatch(
            notificacion_id=notificacion.id,
            aprendiz_id=notificacion.destinatario_id,
            ficha_id=notificacion.ficha_id,
            suscripcion_id=suscripcion.id,
            estado='pendiente',
            disponible_en=utc_now(),
        )
        db.session.add(despacho)
        despachos.append(despacho)
    return despachos


def _mensaje_push(notificacion, ficha_id, silenciosa):
    """Construye contenido general que no contiene notas ni documentos."""
    if notificacion.tipo == 'juicio_evaluativo':
        cuerpo = 'Tu reporte de resultados fue actualizado. Entra al panel para consultar la información.'
    else:
        cuerpo = 'Tu instructor publicó una calificación. Entra al panel para consultar el resultado.'
    return {
        'title': 'Tienes una nueva actualización',
        'body': cuerpo,
        'url': f'/aprendiz/{ficha_id}/notificaciones',
        'silent': bool(silenciosa),
    }


def _enviar_suscripcion(suscripcion, payload, private_key, subject):
    """Envía un mensaje cifrado con VAPID y un tiempo máximo de ocho segundos."""
    from pywebpush import webpush

    return webpush(
        subscription_info={
            'endpoint': suscripcion.endpoint,
            'keys': {'p256dh': suscripcion.p256dh, 'auth': suscripcion.auth},
        },
        data=json.dumps(payload, ensure_ascii=False),
        vapid_private_key=private_key,
        vapid_claims={'sub': subject},
        ttl=86400,
        timeout=8,
    )


def _estado_error_push(error):
    """Clasifica errores temporales, vencidos y permanentes sin guardar datos externos."""
    respuesta = getattr(error, 'response', None)
    status = getattr(error, 'status_code', None) or getattr(respuesta, 'status_code', None)
    if status in (404, 410):
        return 'vencida'
    if status is None or status in (408, 425, 429) or status >= 500:
        return 'temporal'
    return 'permanente'


def procesar_push_pendientes(limit=20, sender=None, ahora=None):
    """Envía lotes del buzón; los fallos de red nunca revierten la calificación."""
    resumen = {'enviados': 0, 'reintentados': 0, 'retirados': 0, 'fallidos': 0}
    if not configuracion_push_disponible():
        return resumen
    ahora = ahora or utc_now()
    enviar = sender or _enviar_suscripcion
    pendientes = PushDispatch.query.filter_by(estado='pendiente').filter(
        PushDispatch.disponible_en <= ahora,
    ).order_by(PushDispatch.id).limit(max(1, min(int(limit), 100))).all()
    for despacho in pendientes:
        notificacion = db.session.get(Notificacion, despacho.notificacion_id)
        suscripcion = db.session.get(PushSubscription, despacho.suscripcion_id)
        if notificacion is None or not suscripcion:
            despacho.estado = 'enviado'
            despacho.enviado_en = ahora
            continue
        from app.features.experiencia_aprendiz.service import leer_experiencia

        preferencias = leer_experiencia(despacho.aprendiz_id)['preferences']
        payload = _mensaje_push(
            notificacion, despacho.ficha_id,
            preferencias.get('notificationMode') == 'quiet',
        )
        despacho.intentos += 1
        despacho.ultimo_error = None
        try:
            enviar(
                suscripcion, payload,
                current_app.config['VAPID_PRIVATE_KEY'],
                current_app.config['VAPID_SUBJECT'],
            )
            despacho.estado = 'enviado'
            despacho.enviado_en = ahora
            resumen['enviados'] += 1
        except Exception as error:
            clase = _estado_error_push(error)
            if clase == 'vencida':
                despacho.suscripcion_id = None
                despacho.estado = 'enviado'
                despacho.enviado_en = ahora
                db.session.delete(suscripcion)
                resumen['retirados'] += 1
            elif clase == 'temporal' and despacho.intentos < _MAX_INTENTOS:
                demora = min(30 * (2 ** (despacho.intentos - 1)), 3600)
                despacho.disponible_en = ahora + timedelta(seconds=demora)
                despacho.ultimo_error = 'fallo_temporal'
                resumen['reintentados'] += 1
            else:
                despacho.estado = 'fallido'
                despacho.ultimo_error = 'fallo_permanente' if clase == 'permanente' else 'reintentos_agotados'
                resumen['fallidos'] += 1
    db.session.commit()
    return resumen
