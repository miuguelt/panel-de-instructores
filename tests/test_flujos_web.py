import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from io import BytesIO
from unittest.mock import patch

from flask import g
from sqlalchemy.exc import IntegrityError

from app import create_app, db
from app.models import (
    Alerta,
    Aprendiz,
    ConfiguracionAlertas,
    ConfiguracionAlertasComite,
    ConfiguracionAseo,
    ConfiguracionRanking,
    Entrega,
    Ficha,
    FichaInstructor,
    Instructor,
    RegistroAsistencia,
    SesionAsistencia,
    Tarea,
)


class FlujosWebTestCase(unittest.TestCase):
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

        self.instructor = Instructor(
            nombre='Instructor Principal',
            correo='principal@sena.edu.co',
            rol='admin',
        )
        self.instructor.set_password('clave-segura')
        self.ajeno = Instructor(
            nombre='Instructor Ajeno',
            correo='ajeno@sena.edu.co',
            rol='colaborador',
        )
        self.ajeno.set_password('clave-segura')
        db.session.add_all([self.instructor, self.ajeno])
        db.session.flush()

        self.ficha = Ficha(
            codigo='3000001',
            codigo_ficha='3000001',
            nombre_programa='Análisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
            fecha_inicio=date.today() - timedelta(days=30),
            fecha_fin=date.today() + timedelta(days=330),
        )
        db.session.add(self.ficha)
        db.session.flush()
        db.session.add_all([
            ConfiguracionAlertas(ficha_id=self.ficha.id),
            ConfiguracionAlertasComite(ficha_id=self.ficha.id),
            ConfiguracionRanking(ficha_id=self.ficha.id),
            ConfiguracionAseo(ficha_id=self.ficha.id),
        ])
        self.aprendiz = Aprendiz(
            documento='1000001',
            nombre='Ana',
            apellidos='Prueba',
            ficha_id=self.ficha.id,
        )
        self.otro_aprendiz = Aprendiz(
            documento='1000002',
            nombre='Bruno',
            apellidos='Prueba',
            ficha_id=self.ficha.id,
        )
        db.session.add_all([self.aprendiz, self.otro_aprendiz])
        db.session.flush()

        self.sesion = SesionAsistencia(ficha_id=self.ficha.id, fecha=date.today())
        db.session.add(self.sesion)
        db.session.flush()
        db.session.add_all([
            RegistroAsistencia(
                sesion_id=self.sesion.id,
                aprendiz_id=self.aprendiz.id,
                estado='ASISTE',
            ),
            RegistroAsistencia(
                sesion_id=self.sesion.id,
                aprendiz_id=self.otro_aprendiz.id,
                estado='ASISTE',
            ),
        ])
        self.tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo='Actividad de prueba',
            fecha_limite=datetime.utcnow() + timedelta(days=2),
        )
        db.session.add(self.tarea)
        db.session.flush()
        self.entrega = Entrega(
            tarea_id=self.tarea.id,
            aprendiz_id=self.aprendiz.id,
            enlace_repositorio='https://example.com/evidencia',
        )
        self.alerta_general = Alerta(
            ficha_id=self.ficha.id,
            aprendiz_id=None,
            tipo='cronograma',
            nivel='amarilla',
            titulo='Cierre próximo',
            mensaje='La ficha se acerca a su fecha de finalización.',
        )
        db.session.add_all([self.entrega, self.alerta_general])
        db.session.commit()

        self.cliente = self.app.test_client()
        self._autenticar(self.instructor)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def _autenticar(self, instructor):
        g.pop('_login_user', None)
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(instructor.id)
            sesion['_fresh'] = True

    def test_paginas_principales_y_reportes_responden(self):
        rutas = (
            '/instructor/',
            '/instructor/fichas',
            f'/instructor/fichas/{self.ficha.id}/aprendices',
            f'/instructor/fichas/{self.ficha.id}/aprendices/{self.aprendiz.id}/historial',
            f'/instructor/fichas/{self.ficha.id}/asistencia',
            f'/instructor/fichas/{self.ficha.id}/tareas',
            f'/instructor/tareas/{self.tarea.id}/entregas',
            f'/instructor/fichas/{self.ficha.id}/alertas',
            f'/instructor/fichas/{self.ficha.id}/casos-seguimiento',
            f'/instructor/fichas/{self.ficha.id}/ranking',
            f'/instructor/fichas/{self.ficha.id}/insignias',
            f'/instructor/fichas/{self.ficha.id}/turnos-aseo',
            '/instructor/notificaciones',
            f'/api/fichas/{self.ficha.id}/resumen',
            f'/instructor/fichas/{self.ficha.id}/reporte-asistencia?formato=excel',
            f'/instructor/fichas/{self.ficha.id}/reporte-asistencia?formato=pdf',
            f'/aprendiz/{self.ficha.id}',
            f'/aprendiz/{self.ficha.id}/panel?documento={self.aprendiz.documento}',
            f'/aprendiz/{self.ficha.id}/notificaciones?documento={self.aprendiz.documento}',
            '/api/health',
        )
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.cliente.get(ruta).status_code, 200)

        dashboard = self.cliente.get('/instructor/').data
        self.assertIn(b'class="card card-ficha"', dashboard)
        self.assertNotIn(b'<a class="card card-ficha"', dashboard)
        self.assertIn('Navegación principal'.encode(), dashboard)

    def test_login_logout_y_redireccion_son_seguros(self):
        cliente = self.app.test_client()
        respuesta = cliente.post(
            '/login?next=https://example.com/salida',
            data={'correo': self.instructor.correo, 'password': 'clave-segura'},
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta.headers['Location'].endswith('/instructor/'))

        self.assertEqual(cliente.get('/logout').status_code, 405)
        self.assertEqual(cliente.post('/logout').status_code, 302)
        self.assertEqual(cliente.get('/instructor/').status_code, 302)

    def test_entradas_invalidas_no_producen_error_500(self):
        solicitudes = (
            ('/instructor/fichas', {
                'codigo': '3000002',
                'nombre_programa': 'Programa',
                'fecha_inicio': 'fecha-invalida',
            }),
            (f'/instructor/fichas/{self.ficha.id}/asistencia', {
                'fecha': 'fecha-invalida',
            }),
            (f'/instructor/fichas/{self.ficha.id}/tareas', {
                'titulo': 'Tarea',
                'fecha_limite': 'fecha-invalida',
            }),
            (f'/instructor/fichas/{self.ficha.id}/alertas/config', {
                'umbral_amarillo': 'tres',
                'umbral_rojo': 'seis',
                'max_fallas_trimestre': 'tres',
            }),
        )
        for ruta, datos in solicitudes:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.cliente.post(ruta, data=datos).status_code, 302)

    def test_asistencia_persiste_si_falla_un_modulo_secundario(self):
        fecha = date.today() + timedelta(days=5)
        datos = {
            'fecha': fecha.isoformat(),
            f'asistencia_{self.aprendiz.id}': 'FALTA',
            f'asistencia_{self.otro_aprendiz.id}': 'ASISTE',
        }

        with patch(
            'app.routes.instructor.ajustar_turno_por_asistencia',
            side_effect=RuntimeError('secondary service unavailable'),
        ), patch(
            'app.routes.instructor.actualizar_alertas_ficha',
            side_effect=RuntimeError('alerts unavailable'),
        ), patch(
            'app.routes.instructor.actualizar_participacion_ficha',
            side_effect=RuntimeError('ranking unavailable'),
        ):
            respuesta = self.cliente.post(
                f'/instructor/fichas/{self.ficha.id}/asistencia',
                data=datos,
                follow_redirects=True,
            )

        self.assertEqual(respuesta.status_code, 200)
        db.session.remove()
        sesion = SesionAsistencia.query.filter_by(
            ficha_id=self.ficha.id, fecha=fecha
        ).one()
        registros = {
            registro.aprendiz_id: registro.estado
            for registro in sesion.registros.all()
        }
        self.assertEqual(registros, {
            self.aprendiz.id: 'FALTA',
            self.otro_aprendiz.id: 'ASISTE',
        })
        self.assertIn('Asistencia guardada correctamente', respuesta.data.decode())

    def test_instructor_ajeno_no_se_vincula_solo_con_el_codigo(self):
        self._autenticar(self.ajeno)
        respuesta = self.cliente.post('/instructor/fichas', data={
            'codigo': self.ficha.codigo,
            'nombre_programa': self.ficha.nombre_programa,
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertIsNone(FichaInstructor.query.filter_by(
            ficha_id=self.ficha.id,
            instructor_id=self.ajeno.id,
        ).first())

    def test_tareas_se_aislan_por_instructor_y_admin_ve_todas(self):
        db.session.add(FichaInstructor(
            ficha_id=self.ficha.id,
            instructor_id=self.ajeno.id,
        ))
        tarea_ajena = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.ajeno.id,
            titulo='Actividad del colaborador',
            fecha_limite=datetime.utcnow() + timedelta(days=2),
        )
        db.session.add(tarea_ajena)
        db.session.commit()

        self._autenticar(self.ajeno)
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={'titulo': 'Actividad creada por ruta'},
        )
        self.assertEqual(respuesta.status_code, 302)
        tarea_creada = Tarea.query.filter_by(titulo='Actividad creada por ruta').one()
        self.assertEqual(tarea_creada.instructor_id, self.ajeno.id)
        listado_ajeno = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/tareas')
        self.assertEqual(listado_ajeno.status_code, 200)
        self.assertIn(b'Actividad del colaborador', listado_ajeno.data)
        self.assertIn(b'Actividad creada por ruta', listado_ajeno.data)
        self.assertNotIn(b'Actividad de prueba', listado_ajeno.data)
        self.assertEqual(
            self.cliente.get(f'/instructor/tareas/{self.tarea.id}/entregas').status_code,
            302,
        )
        respuesta_calificacion = self.cliente.post(
            f'/instructor/entregas/{self.entrega.id}/calificar',
            data={'calificacion': '5.0', 'estado_revision': 'aprobada'},
        )
        self.assertEqual(respuesta_calificacion.status_code, 302)
        db.session.refresh(self.entrega)
        self.assertFalse(self.entrega.calificada)

        self._autenticar(self.instructor)
        listado_admin = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/tareas')
        self.assertEqual(listado_admin.status_code, 200)
        self.assertIn(b'Actividad de prueba', listado_admin.data)
        self.assertIn(b'Actividad del colaborador', listado_admin.data)

    def test_cargas_se_guardan_dentro_de_uploads_y_descarga_exige_acceso(self):
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={
                'titulo': 'Guía con material',
                'material_apoyo': (BytesIO(b'contenido material'), 'guia.pdf'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(respuesta.status_code, 302)
        tarea = Tarea.query.filter_by(titulo='Guía con material').one()
        self.assertFalse(os.path.isabs(tarea.material_apoyo_url))
        self.assertTrue(os.path.isfile(os.path.join(
            self.uploads.name,
            tarea.material_apoyo_url,
        )))

        g.pop('_login_user', None)
        cliente_publico = self.app.test_client()
        descarga = cliente_publico.get(
            f'/aprendiz/descargar/{tarea.material_apoyo_url}'
            f'?ficha_id={self.ficha.id}&documento={self.aprendiz.documento}'
        )
        self.assertEqual(descarga.status_code, 200)
        descarga.close()

        g.pop('_login_user', None)
        sin_identidad = cliente_publico.get(
            f'/aprendiz/descargar/{tarea.material_apoyo_url}'
        )
        self.assertEqual(sin_identidad.status_code, 404)
        sin_identidad.close()
        self.assertEqual(
            cliente_publico.get('/aprendiz/descargar/../config.py').status_code,
            404,
        )

        evidencia = cliente_publico.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{self.tarea.id}',
            data={
                'documento': self.aprendiz.documento,
                'archivo_evidencia': (BytesIO(b'evidencia'), 'evidencia.pdf'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(evidencia.status_code, 302)
        db.session.refresh(self.entrega)
        self.assertFalse(os.path.isabs(self.entrega.archivo_url))
        self.assertTrue(os.path.isfile(os.path.join(
            self.uploads.name,
            self.entrega.archivo_url,
        )))

    def test_evidencias_quedan_vinculadas_al_aprendiz_y_no_se_mezclan(self):
        pdf_ana = b'%PDF-1.4\n evidencia ANA\n%%EOF'
        pdf_bruno = b'%PDF-1.4\n evidencia BRUNO\n%%EOF'

        cliente_ana = self.app.test_client()
        cliente_ana.post(
            f'/aprendiz/{self.ficha.id}',
            data={'documento': self.aprendiz.documento},
        )
        respuesta_ana = cliente_ana.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{self.tarea.id}',
            data={
                'archivo_evidencia': (BytesIO(pdf_ana), 'ana.pdf'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(respuesta_ana.status_code, 302)

        cliente_bruno = self.app.test_client()
        cliente_bruno.post(
            f'/aprendiz/{self.ficha.id}',
            data={'documento': self.otro_aprendiz.documento},
        )
        respuesta_bruno = cliente_bruno.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{self.tarea.id}',
            data={
                'archivo_evidencia': (BytesIO(pdf_bruno), 'bruno.pdf'),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(respuesta_bruno.status_code, 302)

        db.session.refresh(self.entrega)
        entrega_bruno = Entrega.query.filter_by(
            tarea_id=self.tarea.id,
            aprendiz_id=self.otro_aprendiz.id,
        ).one()
        self.assertNotEqual(self.entrega.archivo_url, entrega_bruno.archivo_url)
        self.assertIn(
            f'ficha_{self.ficha.id}/instructor_{self.tarea.instructor_id}/'
            f'aprendiz_{self.aprendiz.id}/tarea_{self.tarea.id}',
            self.entrega.archivo_url,
        )
        self.assertIn(
            f'aprendiz_{self.otro_aprendiz.id}/tarea_{self.tarea.id}',
            entrega_bruno.archivo_url,
        )

        pagina = self.cliente.get(f'/instructor/tareas/{self.tarea.id}/entregas')
        self.assertEqual(pagina.status_code, 200)
        self.assertIn(
            f'/instructor/entregas/{self.entrega.id}/archivo'.encode(),
            pagina.data,
        )
        self.assertIn(
            f'/instructor/entregas/{entrega_bruno.id}/archivo'.encode(),
            pagina.data,
        )

        descarga_ana = self.cliente.get(
            f'/instructor/entregas/{self.entrega.id}/archivo'
        )
        descarga_bruno = self.cliente.get(
            f'/instructor/entregas/{entrega_bruno.id}/archivo'
        )
        self.assertEqual(descarga_ana.status_code, 200)
        self.assertEqual(descarga_bruno.status_code, 200)
        self.assertIn(b'evidencia ANA', descarga_ana.data)
        self.assertIn(b'evidencia BRUNO', descarga_bruno.data)

        self._autenticar(self.ajeno)
        self.assertEqual(
            self.cliente.get(
                f'/instructor/entregas/{self.entrega.id}/archivo'
            ).status_code,
            404,
        )

        self.assertEqual(
            cliente_ana.get(
                f'/aprendiz/descargar-evidencia/{entrega_bruno.id}'
            ).status_code,
            404,
        )
        self.assertEqual(
            cliente_ana.get(
                f'/aprendiz/descargar-evidencia/{self.entrega.id}'
            ).status_code,
            200,
        )

        with self.assertRaises(IntegrityError):
            db.session.add(Entrega(
                tarea_id=self.tarea.id,
                aprendiz_id=self.aprendiz.id,
                enlace_repositorio='https://example.com/duplicada',
            ))
            db.session.commit()
        db.session.rollback()

    def test_resolver_alerta_general_es_atomico_y_responde(self):
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/alertas/{self.alerta_general.id}/resolver'
        )
        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(self.alerta_general)
        self.assertEqual(self.alerta_general.estado, 'resuelta')
        self.assertIsNotNone(self.alerta_general.fecha_resuelta)

    def test_pagina_404_es_util(self):
        respuesta = self.cliente.get('/ruta-que-no-existe')
        self.assertEqual(respuesta.status_code, 404)
        self.assertIn('Página no encontrada'.encode(), respuesta.data)


if __name__ == '__main__':
    unittest.main()
