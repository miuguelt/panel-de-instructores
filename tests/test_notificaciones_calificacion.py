import unittest
import base64
import hashlib
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import create_app, db
from app.models import Aprendiz, Entrega, Ficha, Grupo, GrupoAprendiz, Instructor, Notificacion, Tarea
from app.models.alertas import PushDispatch, PushSubscription
from app.services.alertas import notificar_calificacion
from app.services.notificaciones_push import (
    _enviar_suscripcion,
    configuracion_push_disponible,
    procesar_push_pendientes,
    validar_datos_suscripcion,
)


class NotificacionesCalificacionTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'WEB_PUSH_ENABLED': True,
            'VAPID_PUBLIC_KEY': 'publica',
            'VAPID_PRIVATE_KEY': 'privada',
            'VAPID_SUBJECT': 'mailto:soporte@example.org',
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        self.instructor = Instructor(nombre='Instructor', correo='i@example.org', rol='admin')
        self.instructor.set_password('clave')
        db.session.add(self.instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='F1', nombre_programa='ADSO', instructor_id=self.instructor.id)
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendices = [
            Aprendiz(documento=f'DOC-{i}001', nombre=f'Aprendiz {i}', apellidos='Prueba', ficha_id=self.ficha.id)
            for i in (1, 2)
        ]
        db.session.add_all(self.aprendices)
        db.session.flush()
        self.tarea = Tarea(
            ficha_id=self.ficha.id, instructor_id=self.instructor.id,
            titulo='Actividad grupal', es_grupal=True,
        )
        db.session.add(self.tarea)
        db.session.flush()
        self.grupo = Grupo(ficha_id=self.ficha.id, nombre='Equipo')
        db.session.add(self.grupo)
        db.session.flush()
        self.tarea.grupos.append(self.grupo)
        db.session.add_all([
            GrupoAprendiz(grupo_id=self.grupo.id, aprendiz_id=aprendiz.id)
            for aprendiz in self.aprendices
        ])
        self.entrega = Entrega(
            tarea_id=self.tarea.id, aprendiz_id=self.aprendices[0].id,
            grupo_id=self.grupo.id, calificada=True, calificacion='4.5',
            revisada_en=datetime.utcnow(),
        )
        db.session.add(self.entrega)
        db.session.flush()
        db.session.add(PushSubscription(
            aprendiz_id=self.aprendices[0].id, ficha_id=self.ficha.id,
            endpoint='https://updates.push.services.mozilla.com/push/v1/subscription/1',
            p256dh='A' * 87, auth='B' * 22,
        ))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def test_calificacion_grupal_crea_aviso_para_cada_integrante_y_un_envio(self):
        db.session.add(PushSubscription(
            aprendiz_id=self.aprendices[1].id, ficha_id=self.ficha.id,
            endpoint='https://updates.push.services.mozilla.com/push/v1/subscription/2',
            p256dh='C' * 87, auth='D' * 22,
        ))
        db.session.commit()
        notificar_calificacion(self.entrega, self.ficha.id)

        avisos = Notificacion.query.filter_by(tipo='calificacion').order_by(
            Notificacion.destinatario_id
        ).all()
        self.assertEqual([aviso.destinatario_id for aviso in avisos], [
            self.aprendices[0].id, self.aprendices[1].id,
        ])
        self.assertTrue(all('documento=' not in (aviso.url or '') for aviso in avisos))
        self.assertTrue(all('4.5' not in aviso.mensaje for aviso in avisos))
        self.assertEqual(
            [despacho.aprendiz_id for despacho in PushDispatch.query.order_by(PushDispatch.aprendiz_id)],
            [aprendiz.id for aprendiz in self.aprendices],
        )

    def test_credenciales_push_quedan_cifradas_en_la_base_de_datos(self):
        suscripcion = PushSubscription.query.one()

        self.assertNotIn(suscripcion.endpoint, suscripcion.endpoint_cifrado)
        self.assertNotIn(suscripcion.p256dh, suscripcion.p256dh_cifrado)
        self.assertNotIn(suscripcion.auth, suscripcion.auth_cifrado)
        self.assertEqual(
            suscripcion.endpoint_hash,
            hashlib.sha256(suscripcion.endpoint.encode('utf-8')).hexdigest(),
        )

    def test_endpoint_de_sondeo_aisla_aprendiz_con_la_sesion(self):
        notificar_calificacion(self.entrega, self.ficha.id)
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = self.aprendices[0].documento
            sesion['aprendiz_ficha_id'] = self.ficha.id

        respuesta = cliente.get(f'/aprendiz/{self.ficha.id}/notificaciones/nuevas?desde_id=0')

        self.assertEqual(respuesta.status_code, 200)
        payload = respuesta.get_json()
        self.assertEqual(len(payload['notificaciones']), 1)
        self.assertEqual(payload['notificaciones'][0]['tipo'], 'calificacion')
        self.assertNotIn(self.aprendices[0].documento, respuesta.get_data(as_text=True))

    def test_suscripcion_se_vincula_y_solo_su_aprendiz_puede_retirarla(self):
        payload = {
            'endpoint': 'https://updates.push.services.mozilla.com/push/v1/subscription/1',
            'keys': {
                'p256dh': base64.urlsafe_b64encode(bytes([4]) + bytes([1]) * 64).decode().rstrip('='),
                'auth': base64.urlsafe_b64encode(bytes([2]) * 16).decode().rstrip('='),
            },
        }
        propietario = self.app.test_client()
        with propietario.session_transaction() as sesion:
            sesion['aprendiz_documento'] = self.aprendices[0].documento
            sesion['aprendiz_ficha_id'] = self.ficha.id
        creada = propietario.post(
            f'/aprendiz/{self.ficha.id}/notificaciones/suscripcion', json=payload,
        )
        self.assertEqual(creada.status_code, 200)
        self.assertEqual(PushSubscription.query.count(), 1)
        self.assertEqual(PushSubscription.query.one().p256dh, payload['keys']['p256dh'])

        otro_aprendiz = self.app.test_client()
        with otro_aprendiz.session_transaction() as sesion:
            sesion['aprendiz_documento'] = self.aprendices[1].documento
            sesion['aprendiz_ficha_id'] = self.ficha.id
        conflicto = otro_aprendiz.post(
            f'/aprendiz/{self.ficha.id}/notificaciones/suscripcion', json=payload,
        )
        self.assertEqual(conflicto.status_code, 409)
        solicitud_malformada = propietario.delete(
            f'/aprendiz/{self.ficha.id}/notificaciones/suscripcion',
            json=['este cuerpo no es un objeto'],
        )
        self.assertEqual(solicitud_malformada.status_code, 404)
        retiro_ajeno = otro_aprendiz.delete(
            f'/aprendiz/{self.ficha.id}/notificaciones/suscripcion',
            json={'endpoint': payload['endpoint']},
        )
        self.assertEqual(retiro_ajeno.status_code, 404)

        retiro = propietario.delete(
            f'/aprendiz/{self.ficha.id}/notificaciones/suscripcion',
            json={'endpoint': payload['endpoint']},
        )
        self.assertEqual(retiro.status_code, 200)
        self.assertEqual(PushSubscription.query.count(), 0)

    def test_sondeo_requiere_sesion_y_suscripcion_rechaza_endpoint_no_seguro(self):
        cliente = self.app.test_client()
        self.assertEqual(
            cliente.get(f'/aprendiz/{self.ficha.id}/notificaciones/nuevas').status_code,
            401,
        )
        with cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = self.aprendices[0].documento
            sesion['aprendiz_ficha_id'] = self.ficha.id
        respuesta = cliente.post(
            f'/aprendiz/{self.ficha.id}/notificaciones/suscripcion',
            json={'endpoint': 'http://127.0.0.1/interno', 'keys': {}},
        )
        self.assertEqual(respuesta.status_code, 400)

        with cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = self.aprendices[0].documento
            sesion['aprendiz_ficha_id'] = self.ficha.id
        self.app.config['WEB_PUSH_ENABLED'] = False
        deshabilitada = cliente.post(
            f'/aprendiz/{self.ficha.id}/notificaciones/suscripcion', json={},
        )
        self.assertEqual(deshabilitada.status_code, 503)

    def test_service_worker_se_sirve_con_alcance_del_panel(self):
        respuesta = self.app.test_client().get('/aprendiz/service-worker.js')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.headers['Service-Worker-Allowed'], '/aprendiz/')
        self.assertIn(b'notificationclick', respuesta.data)

    def test_validacion_rechaza_claves_malformadas_y_sender_usa_vapid_cifrado(self):
        with self.assertRaises(ValueError):
            validar_datos_suscripcion({
                'endpoint': 'https://updates.push.services.mozilla.com/push/v1/prueba',
                'keys': {'p256dh': 'A' * 87, 'auth': 'B' * 22},
            })
        sender = Mock(return_value='enviado')
        suscripcion = PushSubscription.query.one()
        with patch.dict('sys.modules', {'pywebpush': SimpleNamespace(webpush=sender)}):
            resultado = _enviar_suscripcion(
                suscripcion, {'body': 'Aviso general'}, 'clave-privada',
                'mailto:soporte@example.org',
            )
        self.assertEqual(resultado, 'enviado')
        argumento = sender.call_args.kwargs
        self.assertEqual(argumento['subscription_info']['endpoint'], suscripcion.endpoint)
        self.assertEqual(argumento['vapid_private_key'], 'clave-privada')
        self.assertEqual(argumento['timeout'], 8)

    def test_push_exitoso_envia_contenido_general_y_cierra_el_despacho(self):
        notificar_calificacion(self.entrega, self.ficha.id)
        enviado = []
        resultado = procesar_push_pendientes(
            sender=lambda suscripcion, payload, *_args: enviado.append(payload),
            ahora=datetime.utcnow(),
        )
        despacho = PushDispatch.query.one()
        self.assertEqual(resultado['enviados'], 1)
        self.assertEqual(despacho.estado, 'enviado')
        self.assertNotIn('4.5', str(enviado[0]))
        self.assertNotIn('DOC-', str(enviado[0]))
        self.assertEqual(enviado[0]['url'], f'/aprendiz/{self.ficha.id}/notificaciones')

    def test_push_de_juicio_y_fallo_permanente_quedan_registrados(self):
        notificacion = Notificacion(
            destinatario_tipo='aprendiz', destinatario_id=self.aprendices[0].id,
            ficha_id=self.ficha.id, mensaje='Reporte actualizado.', tipo='juicio_evaluativo',
            clave='juicio-prueba', url=f'/aprendiz/{self.ficha.id}/notificaciones',
        )
        db.session.add(notificacion)
        db.session.flush()
        from app.services.notificaciones_push import encolar_push

        encolar_push(notificacion)
        db.session.commit()
        resultado = procesar_push_pendientes(
            sender=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                type('ErrorPush', (Exception,), {'status_code': 400})()
            ),
            ahora=datetime.utcnow(),
        )
        self.assertEqual(resultado['fallidos'], 1)
        self.assertEqual(PushDispatch.query.one().estado, 'fallido')

    def test_worker_no_envia_si_web_push_esta_apagado(self):
        self.app.config['WEB_PUSH_ENABLED'] = False
        notificar_calificacion(self.entrega, self.ficha.id)
        resultado = procesar_push_pendientes(sender=Mock())
        self.assertEqual(resultado, {'enviados': 0, 'reintentados': 0, 'retirados': 0, 'fallidos': 0})
        self.assertEqual(PushDispatch.query.count(), 0)

    def test_push_no_se_habilita_con_una_clave_de_sesion_efimera(self):
        self.app.config['SECRET_KEY_IS_EPHEMERAL'] = True

        self.assertFalse(configuracion_push_disponible())
        notificar_calificacion(self.entrega, self.ficha.id)
        self.assertEqual(PushDispatch.query.count(), 0)

    def test_push_vencido_retira_suscripcion_y_marca_el_envio_cerrado(self):
        notificar_calificacion(self.entrega, self.ficha.id)
        resultado = procesar_push_pendientes(
            sender=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                type('ErrorPush', (Exception,), {'status_code': 410})()
            ),
            ahora=datetime.utcnow(),
        )
        despacho = PushDispatch.query.one()
        self.assertEqual(resultado['retirados'], 1)
        self.assertEqual(despacho.estado, 'enviado')
        self.assertEqual(PushSubscription.query.count(), 0)

    def test_error_temporal_de_push_se_reintenta_sin_afectar_aviso(self):
        notificar_calificacion(self.entrega, self.ficha.id)
        dispatch = PushDispatch.query.one()

        resultado = procesar_push_pendientes(
            sender=lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError('sin servicio')),
            ahora=datetime.utcnow(),
        )

        db.session.refresh(dispatch)
        self.assertEqual(resultado['reintentados'], 1)
        self.assertEqual(dispatch.estado, 'pendiente')
        self.assertEqual(dispatch.intentos, 1)
        self.assertEqual(Notificacion.query.filter_by(tipo='calificacion').count(), 2)


if __name__ == '__main__':
    unittest.main()
