import os
import tempfile
import unittest
from datetime import datetime, timedelta
from io import BytesIO

from app import create_app, db
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.grupo import Grupo, GrupoMensaje
from app.models.instructor import Instructor
from app.models.alertas import Notificacion
from app.models.tarea import Entrega, Tarea
from app.services.alertas import ContextoFicha, _incumplimientos_academicos
from app.services.alertas import notificar_calificacion


class TrabajosGrupalesTestCase(unittest.TestCase):
    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'UPLOAD_FOLDER': self.uploads.name,
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        self.cliente = self.app.test_client()

        self.instructor = Instructor(
            nombre='Instructor de prueba',
            correo='instructor@example.com',
            rol='admin',
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()
        self.ficha = Ficha(
            codigo='3000001',
            nombre_programa='Análisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
        )
        db.session.add(self.ficha)
        db.session.flush()
        self.grupo = Grupo(ficha_id=self.ficha.id, nombre='Equipo Águila', activo=True)
        self.otro_grupo = Grupo(ficha_id=self.ficha.id, nombre='Equipo Cóndor', activo=True)
        self.aprendiz = Aprendiz(
            ficha_id=self.ficha.id, documento='1001', nombre='Ana', apellidos='Díaz'
        )
        self.companero = Aprendiz(
            ficha_id=self.ficha.id, documento='1002', nombre='Luis', apellidos='Pérez'
        )
        self.ajeno = Aprendiz(
            ficha_id=self.ficha.id, documento='1003', nombre='Sara', apellidos='León'
        )
        self.sin_grupo = Aprendiz(
            ficha_id=self.ficha.id, documento='1004', nombre='Mario', apellidos='Rojas'
        )
        db.session.add_all([
            self.grupo, self.otro_grupo, self.aprendiz, self.companero,
            self.ajeno, self.sin_grupo,
        ])
        db.session.flush()
        self.grupo.aprendices.extend([self.aprendiz, self.companero])
        self.otro_grupo.aprendices.append(self.ajeno)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def _iniciar_sesion_instructor(self):
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True

    def _iniciar_sesion_aprendiz(self, aprendiz):
        with self.cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = aprendiz.documento
            sesion['aprendiz_ficha_id'] = self.ficha.id

    def _crear_tarea_grupal(self):
        self._iniciar_sesion_instructor()
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={
                'titulo': 'Informe colaborativo',
                'descripcion': 'Consoliden los resultados del equipo.',
                'modalidad': 'evidencia',
                'requiere_archivo': 'on',
                'tipo_asignacion': 'grupal',
                'grupos_ids[]': [str(self.grupo.id)],
            },
            follow_redirects=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        return Tarea.query.filter_by(titulo='Informe colaborativo').one()

    def test_instructor_asigna_trabajo_a_grupos_activos_de_su_ficha(self):
        tarea = self._crear_tarea_grupal()

        self.assertTrue(tarea.es_grupal)
        self.assertEqual([grupo.id for grupo in tarea.grupos], [self.grupo.id])

    def test_instructor_rechaza_grupo_de_otra_ficha_y_actividad_grupal_en_clase(self):
        otra_ficha = Ficha(
            codigo='3000002', nombre_programa='Otro programa', instructor_id=self.instructor.id
        )
        db.session.add(otra_ficha)
        db.session.flush()
        grupo_ajeno = Grupo(ficha_id=otra_ficha.id, nombre='Grupo ajeno', activo=True)
        db.session.add(grupo_ajeno)
        db.session.commit()
        self._iniciar_sesion_instructor()
        url = f'/instructor/fichas/{self.ficha.id}/tareas'

        grupo_ajeno_response = self.cliente.post(url, data={
            'titulo': 'No debe crearse', 'modalidad': 'evidencia',
            'tipo_asignacion': 'grupal', 'grupos_ids[]': [str(grupo_ajeno.id)],
        }, follow_redirects=True)
        clase_grupal_response = self.cliente.post(url, data={
            'titulo': 'Actividad presencial', 'modalidad': 'clase',
            'tipo_asignacion': 'grupal', 'grupos_ids[]': [str(self.grupo.id)],
        }, follow_redirects=True)

        self.assertEqual(grupo_ajeno_response.status_code, 200)
        self.assertEqual(clase_grupal_response.status_code, 200)
        self.assertIsNone(Tarea.query.filter_by(titulo='No debe crearse').first())
        self.assertIsNone(Tarea.query.filter_by(titulo='Actividad presencial').first())

    def test_aprendices_del_grupo_ven_el_trabajo_y_comparten_una_sola_entrega(self):
        tarea = self._crear_tarea_grupal()
        self._iniciar_sesion_aprendiz(self.aprendiz)

        panel_antes = self.cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(panel_antes.status_code, 200)
        self.assertIn('Equipo Águila'.encode(), panel_antes.data)
        self.assertIn('Informe colaborativo'.encode(), panel_antes.data)
        self.assertIn('pendiente'.encode(), panel_antes.data.lower())

        entrega_response = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{tarea.id}',
            data={
                'archivo_evidencia': (
                    BytesIO(b'%PDF-1.4\n evidencia del equipo\n%%EOF'),
                    'avance.pdf',
                ),
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        self.assertEqual(entrega_response.status_code, 200)
        entrega = Entrega.query.filter_by(tarea_id=tarea.id, grupo_id=self.grupo.id).one()
        self.assertEqual(entrega.aprendiz_id, self.aprendiz.id)
        self.assertIn(
            f'grupo_{self.grupo.id}/tarea_{tarea.id}', entrega.archivo_url
        )
        self.assertTrue(os.path.isfile(os.path.join(self.uploads.name, entrega.archivo_url)))

        self._iniciar_sesion_aprendiz(self.companero)
        panel_despues = self.cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(panel_despues.status_code, 200)
        self.assertIn('Entregada por el grupo'.encode(), panel_despues.data)
        self.assertEqual(Entrega.query.filter_by(tarea_id=tarea.id, grupo_id=self.grupo.id).count(), 1)

        evidencia = self.cliente.get(
            f'/aprendiz/descargar-evidencia/{entrega.id}'
        )
        self.assertEqual(evidencia.status_code, 200)
        self.assertIn(b'evidencia del equipo', evidencia.data)

    def test_aprendiz_de_otro_grupo_no_puede_entregar_trabajo_ajeno(self):
        tarea = self._crear_tarea_grupal()
        self._iniciar_sesion_aprendiz(self.ajeno)

        respuesta = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{tarea.id}',
            data={'enlace_repositorio': 'https://example.com/ajeno'},
            follow_redirects=True,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Entrega.query.filter_by(tarea_id=tarea.id).count(), 0)

    def test_chat_persistente_es_asincrono_y_solo_accesible_al_grupo_activo(self):
        self._iniciar_sesion_aprendiz(self.aprendiz)
        url = f'/aprendiz/{self.ficha.id}/grupo/mensajes'
        inicial = self.cliente.get(url)
        self.assertEqual(inicial.status_code, 200)
        self.assertEqual(inicial.json['messages'], [])

        enviado = self.cliente.post(url, json={'contenido': 'Revisemos el avance mañana.'})
        self.assertEqual(enviado.status_code, 201)
        mensaje_id = enviado.json['message']['id']
        self.assertEqual(GrupoMensaje.query.count(), 1)

        self._iniciar_sesion_aprendiz(self.companero)
        nuevos = self.cliente.get(f'{url}?despues_id={mensaje_id - 1}')
        self.assertEqual(nuevos.status_code, 200)
        self.assertEqual(nuevos.json['messages'][0]['contenido'], 'Revisemos el avance mañana.')
        self.assertEqual(nuevos.json['messages'][0]['autor'], 'Ana Díaz')
        segundo = self.cliente.post(url, json={'contenido': 'Yo llevo el resumen.'})
        self.assertEqual(segundo.status_code, 201)
        incremento = self.cliente.get(f'{url}?despues_id={mensaje_id}')
        self.assertEqual(
            [mensaje['contenido'] for mensaje in incremento.json['messages']],
            ['Yo llevo el resumen.'],
        )

        self._iniciar_sesion_aprendiz(self.ajeno)
        otro_grupo = self.cliente.get(url)
        self.assertEqual(otro_grupo.status_code, 200)
        self.assertEqual(otro_grupo.json['messages'], [])
        mensaje_aislado = self.cliente.post(
            url, json={'contenido': 'Mensaje del Equipo Cóndor.'}
        )
        self.assertEqual(mensaje_aislado.status_code, 201)
        self.assertEqual(
            db.session.get(GrupoMensaje, mensaje_aislado.json['message']['id']).grupo_id,
            self.otro_grupo.id,
        )

        self._iniciar_sesion_aprendiz(self.sin_grupo)
        sin_grupo = self.cliente.get(url)
        rechazado = self.cliente.post(url, json={'contenido': 'Mensaje sin grupo'})
        self.assertEqual(sin_grupo.status_code, 404)
        self.assertEqual(rechazado.status_code, 404)
        self.assertEqual(GrupoMensaje.query.count(), 3)

    def test_chat_rechaza_mensajes_vacios_y_mayores_a_1200_caracteres(self):
        self._iniciar_sesion_aprendiz(self.aprendiz)
        url = f'/aprendiz/{self.ficha.id}/grupo/mensajes'

        vacio = self.cliente.post(url, json={'contenido': '   '})
        extenso = self.cliente.post(url, json={'contenido': 'x' * 1201})

        self.assertEqual(vacio.status_code, 400)
        self.assertEqual(extenso.status_code, 400)
        self.assertEqual(GrupoMensaje.query.count(), 0)

    def test_chat_acepta_1200_caracteres_y_rechaza_cursor_invalido(self):
        self._iniciar_sesion_aprendiz(self.aprendiz)
        url = f'/aprendiz/{self.ficha.id}/grupo/mensajes'

        respuesta = self.cliente.post(url, json={'contenido': 'x' * 1200})
        cursor_invalido = self.cliente.get(f'{url}?despues_id=no-numero')

        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(len(respuesta.json['message']['contenido']), 1200)
        self.assertEqual(cursor_invalido.status_code, 400)
        self.assertEqual(GrupoMensaje.query.count(), 1)

    def test_instructor_revisa_una_entrega_por_grupo(self):
        tarea = self._crear_tarea_grupal()
        db.session.add(Entrega(
            tarea_id=tarea.id,
            aprendiz_id=self.aprendiz.id,
            grupo_id=self.grupo.id,
            enlace_repositorio='https://example.com/equipo',
        ))
        db.session.commit()
        self._iniciar_sesion_instructor()

        respuesta = self.cliente.get(f'/instructor/tareas/{tarea.id}/entregas')

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('Equipo Águila'.encode(), respuesta.data)
        self.assertIn('https://example.com/equipo'.encode(), respuesta.data)

    def test_entrega_grupal_cubre_a_integrantes_y_no_afecta_a_otros_grupos(self):
        tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo='Evidencia grupal vencida',
            fecha_limite=datetime.utcnow() - timedelta(days=1),
            es_grupal=True,
            grupos=[self.grupo],
        )
        db.session.add(tarea)
        db.session.commit()
        ahora = datetime.utcnow()

        contexto = ContextoFicha(self.ficha.id, ahora=ahora)
        self.assertIn(
            tarea,
            _incumplimientos_academicos(
                self.aprendiz.id, self.ficha.id, ahora, contexto
            ),
        )
        self.assertIn(
            tarea,
            _incumplimientos_academicos(
                self.companero.id, self.ficha.id, ahora, contexto
            ),
        )
        self.assertEqual(
            _incumplimientos_academicos(
                self.ajeno.id, self.ficha.id, ahora, contexto
            ),
            [],
        )
        self.assertEqual(
            _incumplimientos_academicos(
                self.sin_grupo.id, self.ficha.id, ahora, contexto
            ),
            [],
        )

        db.session.add(Entrega(
            tarea_id=tarea.id,
            aprendiz_id=self.aprendiz.id,
            grupo_id=self.grupo.id,
            enlace_repositorio='https://example.com/equipo',
            fecha_entrega=tarea.fecha_limite - timedelta(hours=1),
        ))
        db.session.commit()
        contexto = ContextoFicha(self.ficha.id, ahora=ahora)

        self.assertEqual(
            _incumplimientos_academicos(
                self.aprendiz.id, self.ficha.id, ahora, contexto
            ),
            [],
        )
        self.assertEqual(
            _incumplimientos_academicos(
                self.companero.id, self.ficha.id, ahora, contexto
            ),
            [],
        )

        self._iniciar_sesion_instructor()
        tablero = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/evidencias-faltantes'
        )
        self.assertEqual(tablero.status_code, 200)
        self.assertIn(b'2 / 2', tablero.data)

    def test_calificacion_de_entrega_grupal_notifica_a_todo_el_grupo(self):
        tarea = self._crear_tarea_grupal()
        tarea.grupos.append(self.otro_grupo)
        db.session.commit()
        entrega = Entrega(
            tarea_id=tarea.id,
            aprendiz_id=self.aprendiz.id,
            grupo_id=self.grupo.id,
            enlace_repositorio='https://example.com/equipo',
        )
        db.session.add(entrega)
        db.session.flush()
        entrega.calificada = True
        entrega.revisada_en = datetime.utcnow()

        notificar_calificacion(entrega, self.ficha.id)

        self.assertEqual(
            {registro.destinatario_id for registro in Notificacion.query.filter_by(
                destinatario_tipo='aprendiz', tipo='calificacion'
            ).all()},
            {self.aprendiz.id, self.companero.id},
        )


if __name__ == '__main__':
    unittest.main()
