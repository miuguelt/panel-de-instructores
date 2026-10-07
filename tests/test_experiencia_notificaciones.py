"""Avisos del aprendiz: prioridad, lectura persistida y aislamiento por sesión."""

from datetime import datetime, timedelta, timezone
import re
import secrets
import unittest
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor, Notificacion


class ExperienciaNotificacionesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False, 'SECRET_KEY': secrets.token_hex(32),
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        instructor = Instructor(nombre='Instructor', correo='avisos@example.com')
        instructor.set_password(secrets.token_urlsafe(24))
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='300001', nombre_programa='ADSO', instructor_id=instructor.id)
        otra_ficha = Ficha(codigo='300002', nombre_programa='ADSO', instructor_id=instructor.id)
        db.session.add_all([ficha, otra_ficha])
        db.session.flush()
        ana = Aprendiz(documento='30001', nombre='Ana', apellidos='Pérez', ficha_id=ficha.id)
        luis = Aprendiz(documento='30002', nombre='Luis', apellidos='Rojas', ficha_id=ficha.id)
        db.session.add_all([ana, luis])
        db.session.flush()
        ahora = datetime(2026, 10, 7, 12, 0)
        notificaciones = []
        for indice, (tipo, texto) in enumerate((
            ('alerta', 'Revisa tu plan.'), ('calificacion', 'Lee la retroalimentación.'),
            ('tarea', 'Entrega tu evidencia.'), ('general', 'Mensaje general.'),
            ('logro', 'Un nuevo reconocimiento.'), ('general', 'Aviso del día anterior.'),
        )):
            notificaciones.append(Notificacion(
                destinatario_tipo='aprendiz', destinatario_id=ana.id, ficha_id=ficha.id,
                mensaje=texto, tipo=tipo, clave=f'avisoprueba:{indice}',
                url=f'/aprendiz/{ficha.id}/panel?documento={ana.documento}',
                fecha_creada=ahora - timedelta(days=1 if indice == 5 else 0, minutes=indice),
            ))
        ajenas = [
            Notificacion(destinatario_tipo='aprendiz', destinatario_id=luis.id,
                         ficha_id=ficha.id, mensaje='Solo Luis.', tipo='alerta', clave='otro'),
            Notificacion(destinatario_tipo='aprendiz', destinatario_id=ana.id,
                         ficha_id=otra_ficha.id, mensaje='Otra ficha.', tipo='alerta', clave='otra'),
            Notificacion(destinatario_tipo='instructor', destinatario_id=instructor.id,
                         ficha_id=ficha.id, mensaje='Solo instructor.', tipo='alerta', clave='instructor'),
        ]
        db.session.add_all(notificaciones + ajenas)
        db.session.commit()
        self.ficha_id, self.otra_ficha_id = ficha.id, otra_ficha.id
        self.ana_id, self.luis_id, self.instructor_id = ana.id, luis.id, instructor.id
        self.ids = [item.id for item in notificaciones]
        self.ajenos = [item.id for item in ajenas]
        self.client = self.app.test_client()
        self.autenticar()
        self.url = f'/aprendiz/{self.ficha_id}/notificaciones'

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.contexto.pop()

    def autenticar(self, cliente=None, documento='30001', ficha_id=None):
        with (cliente or self.client).session_transaction() as sesion:
            sesion['aprendiz_documento'] = documento
            sesion['aprendiz_ficha_id'] = ficha_id or self.ficha_id

    def modo(self, modo):
        from app.features.experiencia_aprendiz.service import DEFAULTS, guardar_experiencia
        preferencias = dict(DEFAULTS, notificationMode=modo)
        guardar_experiencia(self.ana_id, preferencias, 0, self.ficha_id)

    def test_clasificacion_conservadora_y_destinos_sin_identidad(self):
        from app.features.experiencia_aprendiz.notifications import clasificar_notificacion
        casos = {
            'alerta': ('Seguimiento', True, 'convivencia'),
            'tarea': ('Evidencias', True, 'evidencias'),
            'calificacion': ('Retroalimentación', True, 'evidencias'),
            'feedback': ('Retroalimentación', True, 'evidencias'),
            'justificacion': ('Asistencia', True, 'resumen'),
            'observador': ('Convivencia', True, 'convivencia'),
            'cronograma': ('Calendario', True, 'resumen'),
            'advertencia': ('Seguimiento', True, 'convivencia'),
            'critica': ('Seguimiento', True, 'convivencia'),
            'general': ('Otros avisos', False, 'resumen'),
            'grupo': ('Tu grupo', False, 'grupo'),
            'logro': ('Reconocimientos', False, 'rendimiento'),
            'resumen': ('Otros avisos', False, 'resumen'),
            'tipo_nuevo': ('Otros avisos', True, 'resumen'),
        }
        for tipo, esperado in casos.items():
            with self.subTest(tipo=tipo):
                notificacion = Notificacion(tipo=tipo, url='https://example.com/?documento=30001',
                                            fecha_creada=datetime(2026, 10, 7, 12))
                clasificacion = clasificar_notificacion(notificacion, self.ficha_id)
                self.assertEqual((clasificacion['categoria'], clasificacion['importante'],
                                  clasificacion['seccion']), esperado)
                self.assertEqual(clasificacion['destino'],
                                 f'/aprendiz/{self.ficha_id}/panel#tab-{esperado[2]}')
                self.assertIs(clasificacion['notificacion'], notificacion)

    def test_agrupa_dias_categorias_y_modos_sin_mutar_registros(self):
        from app.features.experiencia_aprendiz.notifications import organizar_notificaciones
        registros = [db.session.get(Notificacion, item_id) for item_id in reversed(self.ids)]
        for modo in ('all', 'important', 'quiet', 'desconocido'):
            with self.subTest(modo=modo):
                centro = organizar_notificaciones(registros, modo, self.ficha_id)
                self.assertEqual(centro['modo'], 'all' if modo == 'desconocido' else modo)
                self.assertEqual(centro['total'], 6)
                self.assertEqual(centro['sin_leer'], 6)
                self.assertEqual(centro['importantes'], 3)
                self.assertEqual(centro['opcionales'], 3)
                principales = [item['notificacion'].id for grupo in centro['principales']
                               for item in grupo['avisos']]
                secundarios = [item['notificacion'].id for grupo in centro['secundarios']
                               for item in grupo['avisos']]
                self.assertEqual(set(principales + secundarios), set(self.ids))
                self.assertFalse(set(principales) & set(secundarios))
                self.assertEqual(len(principales), 6 if centro['modo'] == 'all' else 3)
                self.assertEqual(centro['principales'][0]['fecha'], '07/10/2026')
                self.assertEqual(centro['principales'][0]['categoria'], 'Seguimiento')
                if centro['modo'] == 'all':
                    self.assertEqual(centro['principales'][-1]['fecha'], '06/10/2026')
        vacio = organizar_notificaciones([], 'quiet', self.ficha_id)
        self.assertEqual(vacio['total'], 0)
        self.assertEqual(vacio['principales'], [])
        self.assertEqual(vacio['secundarios'], [])
        self.assertTrue(all(not item.leida for item in registros))
        repetido = Notificacion(id=99, tipo='general', fecha_creada=datetime(2026, 10, 7, 9))
        mismo_tema = organizar_notificaciones([registros[2], repetido], 'important', self.ficha_id)
        self.assertEqual(len(mismo_tema['secundarios']), 1)
        self.assertEqual(len(mismo_tema['secundarios'][0]['avisos']), 2)

    def test_pagina_todas_agrupa_sin_documentos_y_aisla_destinatarios(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.get_data(as_text=True)
        self.assertIn('6 sin leer', html)
        self.assertIn('07/10/2026', html)
        self.assertIn('06/10/2026', html)
        self.assertIn('Retroalimentación', html)
        self.assertEqual(html.count('class="notification-symbol"'), 6)
        self.assertNotIn('📌', html)
        self.assertNotIn('🔔', html)
        self.assertIn(f'/aprendiz/{self.ficha_id}/panel#tab-evidencias', html)
        self.assertNotIn('documento=', html)
        self.assertNotIn('name="documento"', html)
        self.assertNotIn('Solo Luis.', html)
        self.assertNotIn('Otra ficha.', html)
        self.assertNotIn('Solo instructor.', html)
        self.assertIn('no-store', respuesta.headers['Cache-Control'])

    def test_importantes_deja_opcionales_consultables_y_no_borra(self):
        self.modo('important')
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('Otros avisos', html)
        self.assertIn('<details', html)
        self.assertLess(html.index('Lee la retroalimentación.'), html.index('<details'))
        self.assertGreater(html.index('Mensaje general.'), html.index('<details'))
        self.assertIn('Revisa tu plan.', html)
        self.assertIn('name="csrf_token"', html)
        self.assertEqual(Notificacion.query.count(), 9)
        self.assertEqual(Notificacion.query.filter_by(leida=True).count(), 0)

    def test_silencioso_muestra_resumen_y_preserva_avisos_importantes(self):
        self.modo('quiet')
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('Modo silencioso', html)
        self.assertIn('3 avisos adicionales', html)
        self.assertIn('Lee la retroalimentación.', html)
        self.assertIn('Mensaje general.', html)
        self.assertIn('Leer un aviso no confirma que hayas realizado la actividad.', html)
        self.assertEqual(Notificacion.query.count(), 9)

    def test_sesion_obligatoria_no_confia_en_documento_ni_en_ficha_ajena(self):
        cliente = self.app.test_client()
        urls = [self.url + '?documento=30001', self.url + '/leer-todas',
                self.url + f'/{self.ids[0]}/leer']
        self.assertEqual(cliente.get(urls[0]).status_code, 302)
        for url in urls[1:]:
            self.assertEqual(cliente.post(url, data={'documento': '30001'}).status_code, 302)
        self.assertEqual(self.client.get(
            f'/aprendiz/{self.otra_ficha_id}/notificaciones?documento=30001').status_code, 302)
        with self.client.session_transaction() as sesion:
            sesion.pop('aprendiz_ficha_id')
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(Notificacion.query.filter_by(leida=True).count(), 0)

    def test_acceso_inactivo_no_consulta_ni_marca(self):
        db.session.get(Aprendiz, self.ana_id).activo = False
        db.session.commit()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url + '/leer-todas').status_code, 302)
        self.assertEqual(self.client.post(self.url + f'/{self.ids[0]}/leer').status_code, 302)
        self.assertEqual(Notificacion.query.filter_by(leida=True).count(), 0)

    def test_marca_individual_persiste_y_contador_actualiza_sin_borrar(self):
        respuesta = self.client.post(self.url + f'/{self.ids[0]}/leer',
                                     data={'learner_context': str(self.ana_id)}, follow_redirects=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('5 sin leer', respuesta.get_data(as_text=True))
        self.assertIn('Notificación marcada como leída.', respuesta.get_data(as_text=True))
        db.session.remove()
        notificacion = db.session.get(Notificacion, self.ids[0])
        self.assertTrue(notificacion.leida)
        self.assertIsNotNone(notificacion.leida_en)
        self.assertEqual(notificacion.mensaje, 'Revisa tu plan.')
        self.assertEqual(Notificacion.query.count(), 9)
        self.assertEqual(Notificacion.query.filter_by(leida=True).count(), 1)
        self.assertIn('Revisa tu plan.', respuesta.get_data(as_text=True))

    def test_marca_todas_solo_mismo_destinatario_ficha_y_refresca(self):
        respuesta = self.client.post(self.url + '/leer-todas',
                                     data={'documento': '30002', 'learner_context': str(self.ana_id)},
                                     follow_redirects=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('0 sin leer', respuesta.get_data(as_text=True))
        self.assertIn('class="notification-symbol"', respuesta.get_data(as_text=True))
        self.assertNotIn('🔔', respuesta.get_data(as_text=True))
        db.session.remove()
        self.assertEqual(Notificacion.query.count(), 9)
        self.assertTrue(all(db.session.get(Notificacion, item_id).leida for item_id in self.ids))
        self.assertFalse(any(db.session.get(Notificacion, item_id).leida for item_id in self.ajenos))
        self.assertIn('Revisa tu plan.', respuesta.get_data(as_text=True))

    def test_marca_individual_ajena_y_ausente_no_modifica_nada(self):
        for item_id in self.ajenos + [99999]:
            with self.subTest(item_id=item_id):
                respuesta = self.client.post(self.url + f'/{item_id}/leer',
                                             data={'learner_context': str(self.ana_id)})
                self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Notificacion.query.filter_by(leida=True).count(), 0)

    def test_csrf_no_permite_marcar_sin_token(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        for url in (self.url + '/leer-todas', self.url + f'/{self.ids[0]}/leer'):
            respuesta = self.client.post(url)
            self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Notificacion.query.filter_by(leida=True).count(), 0)
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('name="csrf_token"', html)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        respuesta = self.client.post(self.url + f'/{self.ids[0]}/leer',
                                     data={'csrf_token': token, 'learner_context': str(self.ana_id)})
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(db.session.get(Notificacion, self.ids[0]).leida)

    def test_instructor_conserva_vista_y_control_de_lectura(self):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor_id)
            sesion['_fresh'] = True
        respuesta = cliente.get('/instructor/notificaciones')
        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.get_data(as_text=True)
        self.assertIn('Centro de notificaciones', html)
        self.assertIn('Solo instructor.', html)
        self.assertNotIn('Lee la retroalimentación.', html)

    def test_estado_vacio_invita_volver_al_panel(self):
        Notificacion.query.filter_by(destinatario_tipo='aprendiz', destinatario_id=self.ana_id,
                                     ficha_id=self.ficha_id).delete()
        db.session.commit()
        respuesta = self.client.get(self.url)
        self.assertIn('No tienes notificaciones', respuesta.get_data(as_text=True))
        self.assertIn('Volver a mi panel', respuesta.get_data(as_text=True))
        self.assertIn('0 sin leer', respuesta.get_data(as_text=True))
        self.assertIn('class="notification-symbol"', respuesta.get_data(as_text=True))
        self.assertNotIn('🔔', respuesta.get_data(as_text=True))

    def test_opcionales_sin_importantes_y_viceversa_son_consultables(self):
        self.modo('quiet')
        Notificacion.query.filter(Notificacion.id.in_(self.ids[:3])).delete()
        db.session.commit()
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('No hay avisos importantes para revisar.', html)
        self.assertIn('3 avisos adicionales', html)
        self.assertIn('Mensaje general.', html)
        Notificacion.query.filter(Notificacion.id.in_(self.ids[3:])).delete()
        db.session.add(Notificacion(
            destinatario_tipo='aprendiz', destinatario_id=self.ana_id, ficha_id=self.ficha_id,
            mensaje='Advertencia vigente.', tipo='alerta', clave='reemplazo',
        ))
        db.session.commit()
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('Advertencia vigente.', html)
        self.assertNotIn('<details', html)
        self.assertNotIn('No hay avisos importantes para revisar.', html)

    def test_historial_no_oculta_avisos_antiguos_por_limite_de_cien(self):
        fecha = datetime(2026, 10, 1)
        db.session.add_all([
            Notificacion(destinatario_tipo='aprendiz', destinatario_id=self.ana_id,
                         ficha_id=self.ficha_id, tipo='general', clave=f'historico:{indice}',
                         mensaje=f'Histórico número {indice}.', fecha_creada=fecha)
            for indice in range(101)
        ])
        db.session.commit()
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('107 sin leer', html)
        self.assertIn('Histórico número 0.', html)
        self.assertIn('Histórico número 100.', html)

    def test_error_guardado_lectura_no_confirma_y_revierte(self):
        for url in (self.url + '/leer-todas', self.url + f'/{self.ids[0]}/leer'):
            with self.subTest(url=url), patch(
                'app.routes.seguimiento.db.session.commit', side_effect=SQLAlchemyError(),
            ):
                respuesta = self.client.post(url, data={'learner_context': str(self.ana_id)},
                                             follow_redirects=True)
            self.assertEqual(respuesta.status_code, 200)
            self.assertIn('No se pudo guardar la lectura.', respuesta.get_data(as_text=True))
            self.assertIn('6 sin leer', respuesta.get_data(as_text=True))
            db.session.remove()
            self.assertEqual(Notificacion.query.filter_by(leida=True).count(), 0)
            self.assertEqual(Notificacion.query.count(), 9)

    def test_formulario_antiguo_no_marca_nada_al_cambiar_la_sesion(self):
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn(f'name="learner_context" value="{self.ana_id}"', html)
        self.autenticar(documento='30002')
        for url in (self.url + '/leer-todas', self.url + f'/{self.ajenos[0]}/leer'):
            with self.subTest(url=url):
                respuesta = self.client.post(url, data={'learner_context': str(self.ana_id)},
                                             follow_redirects=True)
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn('La sesión cambió de aprendiz.', respuesta.get_data(as_text=True))
                self.assertIn('1 sin leer', respuesta.get_data(as_text=True))
        self.assertEqual(Notificacion.query.filter_by(leida=True).count(), 0)

    def test_contexto_ausente_invalido_o_duplicado_no_marca(self):
        for contexto in (None, '', '0', '-1', 'abc', str(self.luis_id),
                         [str(self.ana_id), str(self.ana_id)]):
            datos = {} if contexto is None else {'learner_context': contexto}
            for url in (self.url + '/leer-todas', self.url + f'/{self.ids[0]}/leer'):
                with self.subTest(contexto=contexto, url=url):
                    respuesta = self.client.post(url, data=datos)
                    self.assertEqual(respuesta.status_code, 302)
                    self.assertEqual(Notificacion.query.filter_by(leida=True).count(), 0)

    def test_lectura_repetida_conserva_fecha_y_no_borra(self):
        anterior = datetime(2026, 9, 1, 12)
        notificacion = db.session.get(Notificacion, self.ids[0])
        notificacion.leida = True
        notificacion.leida_en = anterior
        db.session.commit()
        respuesta = self.client.post(self.url + f'/{self.ids[0]}/leer',
                                     data={'learner_context': str(self.ana_id)})
        self.assertEqual(respuesta.status_code, 302)
        db.session.remove()
        self.assertEqual(db.session.get(Notificacion, self.ids[0]).leida_en, anterior)
        self.assertEqual(Notificacion.query.filter_by(leida=True).count(), 1)

    def test_fecha_y_hora_colombianas_en_frontera_de_dia_sin_cambiar_fuente(self):
        from app.features.experiencia_aprendiz.notifications import (
            clasificar_notificacion, organizar_notificaciones,
        )
        origen = datetime(2026, 10, 5, 4, 59)
        notificacion = db.session.get(Notificacion, self.ids[0])
        notificacion.fecha_creada = origen
        db.session.commit()
        clasificacion = clasificar_notificacion(notificacion, self.ficha_id)
        self.assertEqual(clasificacion['fecha_local'].isoformat(), '2026-10-04T23:59:00-05:00')
        consciente = Notificacion(id=999, tipo='alerta', leida=False,
                                  fecha_creada=datetime(2026, 10, 5, 5, 1, tzinfo=timezone.utc))
        centro = organizar_notificaciones([notificacion, consciente], 'all', self.ficha_id)
        self.assertEqual([grupo['fecha'] for grupo in centro['principales']],
                         ['05/10/2026', '04/10/2026'])
        self.assertEqual(centro['principales'][0]['avisos'][0]['fecha_local'].strftime('%H:%M'), '00:01')
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('04/10/2026 · Seguimiento', html)
        self.assertIn('<time datetime="2026-10-04T23:59:00-05:00">11:59 p. m.</time>', html)
        notificacion.fecha_creada = datetime(2026, 10, 5, 5, 1)
        db.session.commit()
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('<time datetime="2026-10-05T00:01:00-05:00">12:01 a. m.</time>', html)
        notificacion.fecha_creada = origen
        db.session.commit()
        db.session.remove()
        self.assertEqual(db.session.get(Notificacion, self.ids[0]).fecha_creada, origen)


if __name__ == '__main__':
    unittest.main()
