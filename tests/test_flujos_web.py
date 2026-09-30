import os
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timedelta
from io import BytesIO
from unittest.mock import patch

from flask import g
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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
    NotaObservador,
    Notificacion,
    ProrrogaTarea,
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
            f'/instructor/fichas/{self.ficha.id}/evidencias-faltantes',
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
                self.assertEqual(self.cliente.get(ruta, follow_redirects=True).status_code, 200)

        dashboard = self.cliente.get('/instructor/').data
        self.assertIn(b'class="card card-ficha', dashboard)
        self.assertNotIn(b'<a class="card card-ficha', dashboard)
        self.assertIn('Navegación principal'.encode(), dashboard)

    def test_evidencias_faltantes_resume_estado_y_prorrogas_por_aprendiz(self):
        ahora = datetime.utcnow()
        tarea_vencida = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo='Informe vencido',
            fecha_limite=ahora - timedelta(days=2),
        )
        tarea_con_prorroga = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo='Informe con prórroga',
            fecha_limite=ahora - timedelta(days=2),
        )
        actividad_clase = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo='Actividad en clase',
            modalidad='clase',
        )
        carlos = Aprendiz(
            documento='1000003',
            nombre='Carlos',
            apellidos='Completo',
            ficha_id=self.ficha.id,
        )
        db.session.add_all([tarea_vencida, tarea_con_prorroga, actividad_clase, carlos])
        db.session.flush()

        db.session.add_all([
            Entrega(
                tarea_id=tarea_vencida.id,
                aprendiz_id=self.aprendiz.id,
                estado_revision='rechazada',
            ),
            ProrrogaTarea(
                tarea_id=tarea_con_prorroga.id,
                aprendiz_id=self.aprendiz.id,
                instructor_id=self.instructor.id,
                nueva_fecha_limite=ahora + timedelta(days=2),
                motivo='Entrega acordada',
            ),
        ])
        tareas = [self.tarea, tarea_vencida, tarea_con_prorroga, actividad_clase]
        db.session.add_all([
            Entrega(
                tarea_id=tarea.id,
                aprendiz_id=carlos.id,
                estado_revision='aprobada',
                registrada_por_instructor=(tarea.id == actividad_clase.id),
            )
            for tarea in tareas
        ])
        db.session.add(Entrega(
            tarea_id=actividad_clase.id,
            aprendiz_id=self.aprendiz.id,
            estado_revision='aprobada',
            registrada_por_instructor=True,
        ))
        db.session.commit()

        respuesta = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/evidencias-faltantes'
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(b'6 / 12', respuesta.data)
        self.assertIn(b'50%', respuesta.data)
        self.assertIn('Todo completo'.encode(), respuesta.data)
        self.assertIn('Corrección solicitada'.encode(), respuesta.data)
        self.assertIn('Prórroga vigente'.encode(), respuesta.data)
        self.assertIn('Actividad pendiente en clase'.encode(), respuesta.data)
        self.assertIn('Vencida'.encode(), respuesta.data)
        self.assertIn('Entregó y completó todas las tareas asignadas.', respuesta.get_data(as_text=True))

    def test_evidencias_faltantes_distingue_ficha_sin_tareas(self):
        db.session.delete(self.tarea)
        db.session.commit()

        respuesta = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/evidencias-faltantes'
        )

        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.get_data(as_text=True)
        self.assertIn('No hay tareas asignadas para esta ficha.', html)
        self.assertIn('Sin tareas', html)
        self.assertNotIn('Todo completo', html)
        self.assertNotIn('aria-valuenow=', html)

    def test_evidencias_faltantes_no_calcula_porcentaje_sin_aprendices_activos(self):
        self.aprendiz.estado = 'CERTIFICADO'
        self.otro_aprendiz.estado = 'CERTIFICADO'
        db.session.commit()

        respuesta = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/evidencias-faltantes'
        )

        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.get_data(as_text=True)
        self.assertIn('no hay aprendices activos en formación.', html)
        self.assertIn('No hay aprendices activos en formación para mostrar.', html)
        self.assertNotIn('aria-valuenow=', html)

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

    def test_editar_tarea_actualiza_datos_y_respeta_la_modalidad_con_registros(self):
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas/{self.tarea.id}/editar',
            data={
                'titulo': 'Actividad renombrada',
                'descripcion': 'Nuevo alcance',
                'modalidad': 'clase',
                'fecha_limite': '2030-01-15T10:30',
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(self.tarea)
        self.assertEqual(self.tarea.titulo, 'Actividad renombrada')
        self.assertEqual(self.tarea.descripcion, 'Nuevo alcance')
        self.assertEqual(self.tarea.fecha_limite, datetime(2030, 1, 15, 10, 30))
        self.assertIsNotNone(self.tarea.actualizada_en)
        # La tarea ya tiene una entrega: la modalidad no puede cambiar.
        self.assertEqual(self.tarea.modalidad, 'evidencia')
        self.assertEqual(Entrega.query.filter_by(tarea_id=self.tarea.id).count(), 1)

    def test_eliminar_tarea_borra_entregas_y_archivos_del_disco(self):
        self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={
                'titulo': 'Tarea desechable',
                'requiere_archivo': 'on',
                'material_apoyo': (BytesIO(b'%PDF-1.4\n material\n%%EOF'), 'guia.pdf'),
            },
            content_type='multipart/form-data',
        )
        tarea = Tarea.query.filter_by(titulo='Tarea desechable').one()

        cliente_publico = self.app.test_client()
        cliente_publico.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{tarea.id}',
            data={
                'documento': self.aprendiz.documento,
                'archivo_evidencia': (BytesIO(b'%PDF-1.4\n evidencia\n%%EOF'), 'evidencia.pdf'),
            },
            content_type='multipart/form-data',
        )
        entrega = Entrega.query.filter_by(tarea_id=tarea.id).one()
        rutas = [
            os.path.join(self.uploads.name, tarea.material_apoyo_url),
            os.path.join(self.uploads.name, entrega.archivo_url),
        ]
        for ruta in rutas:
            self.assertTrue(os.path.isfile(ruta))

        tarea_id = tarea.id
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas/{tarea_id}/eliminar'
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertIsNone(db.session.get(Tarea, tarea_id))
        self.assertEqual(Entrega.query.filter_by(tarea_id=tarea_id).count(), 0)
        for ruta in rutas:
            self.assertFalse(os.path.isfile(ruta))

    def test_instructor_ajeno_no_edita_ni_elimina_tarea_de_otro(self):
        db.session.add(FichaInstructor(
            ficha_id=self.ficha.id,
            instructor_id=self.ajeno.id,
        ))
        db.session.commit()
        self._autenticar(self.ajeno)

        edicion = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas/{self.tarea.id}/editar',
            data={'titulo': 'Secuestro de tarea'},
        )
        self.assertEqual(edicion.status_code, 302)
        borrado = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas/{self.tarea.id}/eliminar'
        )
        self.assertEqual(borrado.status_code, 302)

        db.session.refresh(self.tarea)
        self.assertEqual(self.tarea.titulo, 'Actividad de prueba')
        self.assertIsNotNone(db.session.get(Tarea, self.tarea.id))

    def test_actividad_de_clase_se_aprueba_sin_evidencia_del_aprendiz(self):
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={
                'titulo': 'Sustentación en clase',
                'modalidad': 'clase',
                'requiere_archivo': 'on',
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        actividad = Tarea.query.filter_by(titulo='Sustentación en clase').one()
        self.assertTrue(actividad.es_actividad_clase)
        # La modalidad de aula anula la exigencia de archivo aunque llegue marcada.
        self.assertFalse(actividad.requiere_archivo)

        listado = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/tareas')
        self.assertEqual(listado.status_code, 200)
        self.assertIn('Editar tarea'.encode(), listado.data)
        self.assertIn('Se revisa en clase'.encode(), listado.data)

        pantalla = self.cliente.get(f'/instructor/tareas/{actividad.id}/entregas')
        self.assertEqual(pantalla.status_code, 200)
        self.assertIn('Guardar cumplimiento'.encode(), pantalla.data)

        cliente_publico = self.app.test_client()
        intento = cliente_publico.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{actividad.id}',
            data={
                'documento': self.aprendiz.documento,
                'enlace_repositorio': 'https://example.com/no-deberia',
            },
        )
        self.assertEqual(intento.status_code, 302)
        self.assertEqual(Entrega.query.filter_by(tarea_id=actividad.id).count(), 0)

        aprobacion = self.cliente.post(
            f'/instructor/tareas/{actividad.id}/actividad-clase',
            data={
                'aprobados': [str(self.aprendiz.id)],
                'calificacion_general': '4.8',
                'observacion_general': 'Sustentó en clase',
            },
        )
        self.assertEqual(aprobacion.status_code, 302)
        registros = Entrega.query.filter_by(tarea_id=actividad.id).all()
        self.assertEqual(len(registros), 1)
        registro = registros[0]
        self.assertEqual(registro.aprendiz_id, self.aprendiz.id)
        self.assertTrue(registro.registrada_por_instructor)
        self.assertTrue(registro.calificada)
        self.assertEqual(registro.estado_revision, 'aprobada')
        self.assertEqual(registro.calificacion, '4.8')
        self.assertEqual(registro.revisada_por_id, self.instructor.id)
        self.assertIsNone(registro.archivo_url)
        self.assertTrue(registro.entregada_a_tiempo)

        # Desmarcar retira la aprobación previamente registrada.
        retiro = self.cliente.post(
            f'/instructor/tareas/{actividad.id}/actividad-clase',
            data={'aprobados': []},
        )
        self.assertEqual(retiro.status_code, 302)
        self.assertEqual(Entrega.query.filter_by(tarea_id=actividad.id).count(), 0)

    def test_aprobacion_en_aula_no_aplica_a_tareas_con_evidencia(self):
        respuesta = self.cliente.post(
            f'/instructor/tareas/{self.tarea.id}/actividad-clase',
            data={'aprobados': [str(self.otro_aprendiz.id)]},
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(
            Entrega.query.filter_by(
                tarea_id=self.tarea.id, aprendiz_id=self.otro_aprendiz.id
            ).count(),
            0,
        )

    def test_observador_registra_una_nota_fechada_y_la_deja_a_un_clic(self):
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/observador',
            data={
                'aprendiz_id': str(self.aprendiz.id),
                'tipo': 'positiva',
                'categoria': 'trabajo_equipo',
                'descripcion': 'Lideró la organización del ambiente.',
                'fecha': (date.today() - timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        nota = NotaObservador.query.one()
        self.assertEqual(nota.aprendiz_id, self.aprendiz.id)
        self.assertEqual(nota.instructor_id, self.instructor.id)
        self.assertEqual(nota.tipo, 'positiva')
        self.assertEqual(nota.categoria, 'trabajo_equipo')
        self.assertEqual(nota.fecha, date.today() - timedelta(days=1))
        self.assertIsNone(nota.actualizada_en)

        # Un enlace con aprendiz y tipo deja el formulario listo para escribir.
        pantalla = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/observador'
            f'?aprendiz_id={self.aprendiz.id}&nota_tipo=negativa'
        )
        self.assertEqual(pantalla.status_code, 200)
        self.assertIn(
            f'<option value="{self.aprendiz.id}" selected>'.encode(),
            pantalla.data.replace(b'\n', b' '),
        )
        self.assertIn(b'<option value="negativa" selected>', pantalla.data)

        historial = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/aprendices/{self.aprendiz.id}/historial'
        )
        self.assertIn('Lideró la organización del ambiente.'.encode(), historial.data)
        self.assertIn('Bitácora de formación integral'.encode(), historial.data)

        # El módulo se alcanza desde la navegación de la ficha, no solo por URL.
        self.assertIn(
            f'/instructor/fichas/{self.ficha.id}/observador'.encode(),
            self.cliente.get(f'/instructor/fichas/{self.ficha.id}/tareas').data,
        )

    def test_observador_rechaza_fecha_futura_y_aprendiz_de_otra_ficha(self):
        otra_ficha = Ficha(
            codigo='3000002',
            codigo_ficha='3000002',
            nombre_programa='Otro programa',
            instructor_id=self.instructor.id,
            fecha_inicio=date.today() - timedelta(days=10),
            fecha_fin=date.today() + timedelta(days=100),
        )
        db.session.add(otra_ficha)
        db.session.flush()
        externo = Aprendiz(
            documento='2000001',
            nombre='Carla',
            apellidos='Externa',
            ficha_id=otra_ficha.id,
        )
        db.session.add(externo)
        db.session.commit()

        futura = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/observador',
            data={
                'aprendiz_id': str(self.aprendiz.id),
                'descripcion': 'Hecho que todavía no ocurre.',
                'fecha': (date.today() + timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(futura.status_code, 302)

        ajena = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/observador',
            data={
                'aprendiz_id': str(externo.id),
                'descripcion': 'Aprendiz de otra ficha.',
            },
        )
        self.assertEqual(ajena.status_code, 302)

        sin_texto = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/observador',
            data={'aprendiz_id': str(self.aprendiz.id), 'descripcion': '   '},
        )
        self.assertEqual(sin_texto.status_code, 302)

        self.assertEqual(NotaObservador.query.count(), 0)

    def test_solo_el_autor_o_un_admin_gestiona_una_nota_del_observador(self):
        db.session.add(FichaInstructor(
            ficha_id=self.ficha.id,
            instructor_id=self.ajeno.id,
        ))
        nota = NotaObservador(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            instructor_id=self.instructor.id,
            tipo='negativa',
            categoria='puntualidad',
            descripcion='Llegó 40 minutos tarde a la sesión práctica.',
            fecha=date.today(),
        )
        db.session.add(nota)
        db.session.commit()

        self._autenticar(self.ajeno)
        edicion = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/observador/{nota.id}/editar',
            data={
                'aprendiz_id': str(self.aprendiz.id),
                'descripcion': 'Texto reescrito por otro instructor.',
            },
        )
        self.assertEqual(edicion.status_code, 302)
        borrado = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/observador/{nota.id}/eliminar'
        )
        self.assertEqual(borrado.status_code, 302)
        db.session.refresh(nota)
        self.assertEqual(nota.descripcion, 'Llegó 40 minutos tarde a la sesión práctica.')

        self._autenticar(self.instructor)
        propia = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/observador/{nota.id}/editar',
            data={
                'aprendiz_id': str(self.aprendiz.id),
                'tipo': 'negativa',
                'categoria': 'puntualidad',
                'descripcion': 'Llegó 40 minutos tarde; se acordó compromiso.',
                'fecha': date.today().isoformat(),
            },
        )
        self.assertEqual(propia.status_code, 302)
        db.session.refresh(nota)
        self.assertEqual(nota.descripcion, 'Llegó 40 minutos tarde; se acordó compromiso.')
        self.assertIsNotNone(nota.actualizada_en)

        eliminado = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/observador/{nota.id}/eliminar'
        )
        self.assertEqual(eliminado.status_code, 302)
        self.assertEqual(NotaObservador.query.count(), 0)

    def test_las_notas_alimentan_el_plan_de_mejoramiento_y_el_caso(self):
        db.session.add(NotaObservador(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            instructor_id=self.instructor.id,
            tipo='negativa',
            categoria='convivencia',
            descripcion='Interrumpió la sesión de forma reiterada.',
            fecha=date.today() - timedelta(days=2),
        ))
        # Tipo fuera de los que la revisión automática resuelve sola: el caso
        # debe seguir abierto cuando la vista recalcula las alertas.
        db.session.add(Alerta(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            tipo='convivencia',
            nivel='amarilla',
            titulo='Convivencia en el ambiente',
            mensaje='Requiere acompañamiento en convivencia.',
        ))
        db.session.commit()

        plan = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/planes-mejoramiento'
            f'?aprendiz_id={self.aprendiz.id}'
        )
        self.assertEqual(plan.status_code, 200)
        self.assertIn(b'Historial del observador', plan.data)
        self.assertIn('Interrumpió la sesión de forma reiterada.'.encode(), plan.data)

        # Sin aprendiz seleccionado no se filtra nada: el bloque no aparece.
        plan_sin_aprendiz = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/planes-mejoramiento'
        )
        self.assertNotIn(b'Historial del observador', plan_sin_aprendiz.data)

        casos = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/casos-seguimiento')
        self.assertEqual(casos.status_code, 200)
        self.assertIn(b'timeline-observador', casos.data)
        self.assertIn('Llamado de atención: Convivencia y respeto'.encode(), casos.data)

        # Texto largo y con caracteres de marcado: el borrador se arma con
        # Paragraph, así que debe ajustarse sin romper el PDF.
        db.session.add(NotaObservador(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            instructor_id=self.instructor.id,
            tipo='positiva',
            categoria='comunicacion',
            descripcion='Explicó <b>el ejercicio</b> a sus compañeros & sostuvo el ritmo. ' * 12,
            fecha=date.today(),
        ))
        db.session.commit()

        borrador = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/casos/{self.aprendiz.id}/reporte-comite'
        )
        self.assertEqual(borrador.status_code, 200)
        self.assertEqual(borrador.mimetype, 'application/pdf')
        self.assertTrue(borrador.data.startswith(b'%PDF'))

    def test_el_aprendiz_ve_en_su_panel_las_notas_registradas_sobre_el(self):
        db.session.add_all([
            NotaObservador(
                ficha_id=self.ficha.id,
                aprendiz_id=self.aprendiz.id,
                instructor_id=self.instructor.id,
                tipo='negativa',
                categoria='puntualidad',
                descripcion='Llegó tarde a la sesión práctica.',
                fecha=date.today(),
            ),
            NotaObservador(
                ficha_id=self.ficha.id,
                aprendiz_id=self.otro_aprendiz.id,
                instructor_id=self.instructor.id,
                tipo='negativa',
                categoria='convivencia',
                descripcion='Nota que pertenece a otro aprendiz.',
                fecha=date.today(),
            ),
        ])
        db.session.commit()

        # Un llamado de atención registrado desde el módulo avisa al aprendiz.
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/observador',
            data={
                'aprendiz_id': str(self.aprendiz.id),
                'tipo': 'negativa',
                'categoria': 'convivencia',
                'descripcion': 'Interrumpió la explicación del ejercicio.',
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        aviso = Notificacion.query.filter_by(
            destinatario_tipo='aprendiz',
            destinatario_id=self.aprendiz.id,
            tipo='observador',
        ).one()
        self.assertIn('llamado de atención', aviso.mensaje)

        cliente_publico = self.app.test_client()
        panel = cliente_publico.get(
            f'/aprendiz/{self.ficha.id}/panel?documento={self.aprendiz.documento}',
            follow_redirects=True,
        )
        self.assertEqual(panel.status_code, 200)
        self.assertIn('Constancias de tu formación integral'.encode(), panel.data)
        self.assertIn('Llegó tarde a la sesión práctica.'.encode(), panel.data)
        self.assertIn(b'Llamado de atenci', panel.data)
        # Cada aprendiz solo ve su propia bitácora.
        self.assertNotIn('Nota que pertenece a otro aprendiz.'.encode(), panel.data)

    def test_la_bitacora_conserva_a_los_aprendices_retirados(self):
        nota = NotaObservador(
            ficha_id=self.ficha.id,
            aprendiz_id=self.otro_aprendiz.id,
            instructor_id=self.instructor.id,
            tipo='negativa',
            categoria='compromiso',
            descripcion='Dejó de asistir a las asesorías acordadas.',
            fecha=date.today() - timedelta(days=5),
        )
        db.session.add(nota)
        self.otro_aprendiz.estado = 'RETIRO_VOLUNTARIO'
        db.session.commit()

        pantalla = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/observador')
        self.assertEqual(pantalla.status_code, 200)
        self.assertIn('Dejó de asistir a las asesorías acordadas.'.encode(), pantalla.data)
        # Sigue en el resumen y en el filtro, marcado con su estado.
        self.assertIn(b'retiro voluntario', pantalla.data.lower())
        self.assertIn(f'value="{self.otro_aprendiz.id}"'.encode(), pantalla.data)

        # Y su nota se puede seguir corrigiendo aunque ya no esté en formación.
        edicion = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/observador/{nota.id}/editar',
            data={
                'aprendiz_id': str(self.otro_aprendiz.id),
                'tipo': 'negativa',
                'categoria': 'compromiso',
                'descripcion': 'Dejó de asistir a las asesorías; se notificó al acudiente.',
                'fecha': (date.today() - timedelta(days=5)).isoformat(),
            },
        )
        self.assertEqual(edicion.status_code, 302)
        db.session.refresh(nota)
        self.assertEqual(
            nota.descripcion,
            'Dejó de asistir a las asesorías; se notificó al acudiente.',
        )

    def test_cargas_se_guardan_dentro_de_uploads_y_descarga_exige_acceso(self):
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/tareas',
            data={
                'titulo': 'Guía con material',
                'material_apoyo': (BytesIO(b'%PDF-1.4\n contenido material\n%%EOF'), 'guia.pdf'),
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
                'archivo_evidencia': (BytesIO(b'%PDF-1.4\n evidencia\n%%EOF'), 'evidencia.pdf'),
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

    def test_entrega_se_conserva_si_falla_un_servicio_secundario(self):
        cliente_publico = self.app.test_client()
        with patch(
            'app.routes.aprendiz.actualizar_alertas_ficha',
            side_effect=RuntimeError('alerts unavailable'),
        ), patch(
            'app.routes.aprendiz.actualizar_participacion_ficha',
            side_effect=RuntimeError('ranking unavailable'),
        ):
            respuesta = cliente_publico.post(
                f'/aprendiz/{self.ficha.id}/subir-evidencia/{self.tarea.id}',
                data={
                    'documento': self.aprendiz.documento,
                    'archivo_evidencia': (
                        BytesIO(b'%PDF-1.4\n evidencia durable\n%%EOF'),
                        'durable.pdf',
                    ),
                },
                content_type='multipart/form-data',
                follow_redirects=True,
            )
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(
            'La evidencia quedó guardada, pero no fue posible actualizar todos los indicadores'.encode('utf-8'),
            respuesta.data,
        )
        entrega = Entrega.query.filter_by(
            tarea_id=self.tarea.id, aprendiz_id=self.aprendiz.id
        ).one()
        self.assertTrue(entrega.archivo_url)
        self.assertTrue(os.path.isfile(os.path.join(self.uploads.name, entrega.archivo_url)))

    def test_aprendiz_puede_subir_zip_con_mime_generico_y_reemplazarlo(self):
        cliente_aprendiz = self.app.test_client()
        cliente_aprendiz.post(
            f'/aprendiz/{self.ficha.id}',
            data={'documento': self.aprendiz.documento},
        )
        contenido = BytesIO()
        with zipfile.ZipFile(contenido, 'w', zipfile.ZIP_DEFLATED) as paquete:
            paquete.writestr('src/Aplicacion.java', 'class Aplicacion {}')
        zip_valido = contenido.getvalue()

        primera = cliente_aprendiz.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{self.tarea.id}',
            data={
                'archivo_evidencia': (
                    BytesIO(b'%PDF-1.4\n evidencia inicial\n%%EOF'),
                    'inicial.pdf',
                ),
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(primera.status_code, 302)
        entrega = Entrega.query.filter_by(
            tarea_id=self.tarea.id, aprendiz_id=self.aprendiz.id
        ).one()
        ruta_anterior = os.path.join(self.uploads.name, entrega.archivo_url)
        self.assertTrue(os.path.isfile(ruta_anterior))

        respuesta = cliente_aprendiz.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{self.tarea.id}',
            data={
                'archivo_evidencia': (
                    BytesIO(zip_valido),
                    'proyecto.zip',
                    'application/octet-stream',
                ),
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('Evidencia guardada correctamente'.encode('utf-8'), respuesta.data)
        db.session.refresh(entrega)
        ruta_zip = os.path.join(self.uploads.name, entrega.archivo_url)
        self.assertTrue(os.path.isfile(ruta_zip))
        self.assertFalse(os.path.exists(ruta_anterior))
        with open(ruta_zip, 'rb') as archivo_guardado:
            self.assertEqual(archivo_guardado.read(), zip_valido)

        descarga = cliente_aprendiz.get(
            f'/aprendiz/descargar-evidencia/{entrega.id}'
        )
        try:
            self.assertEqual(descarga.status_code, 200)
            self.assertEqual(descarga.mimetype, 'application/zip')
            self.assertIn('attachment', descarga.headers['Content-Disposition'])
            self.assertEqual(descarga.data, zip_valido)
        finally:
            descarga.close()

    def test_zip_danado_muestra_error_y_no_crea_entrega(self):
        cliente_aprendiz = self.app.test_client()
        cliente_aprendiz.post(
            f'/aprendiz/{self.ficha.id}',
            data={'documento': self.aprendiz.documento},
        )
        respuesta = cliente_aprendiz.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{self.tarea.id}',
            data={
                'archivo_evidencia': (
                    BytesIO(b'PK\x03\x04archivo truncado'),
                    'proyecto.zip',
                    'application/octet-stream',
                ),
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('El archivo .zip está dañado o incompleto'.encode('utf-8'), respuesta.data)
        db.session.refresh(self.entrega)
        self.assertIsNone(self.entrega.archivo_url)
        self.assertFalse(any(archivos for _, _, archivos in os.walk(self.uploads.name)))

    def test_fallo_al_persistir_limpia_archivo_y_muestra_mensaje(self):
        cliente_aprendiz = self.app.test_client()
        cliente_aprendiz.post(
            f'/aprendiz/{self.ficha.id}',
            data={'documento': self.aprendiz.documento},
        )
        with patch(
            'app.routes.aprendiz.db.session.commit',
            side_effect=SQLAlchemyError('fallo de base de datos'),
        ):
            respuesta = cliente_aprendiz.post(
                f'/aprendiz/{self.ficha.id}/subir-evidencia/{self.tarea.id}',
                data={
                    'archivo_evidencia': (
                        BytesIO(b'%PDF-1.4\n evidencia\n%%EOF'),
                        'evidencia.pdf',
                    ),
                },
                content_type='multipart/form-data',
            )

        self.assertEqual(respuesta.status_code, 302)
        respuesta = cliente_aprendiz.get(respuesta.headers['Location'])
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('No fue posible registrar la evidencia'.encode('utf-8'), respuesta.data)
        db.session.refresh(self.entrega)
        self.assertIsNone(self.entrega.archivo_url)
        self.assertFalse(any(archivos for _, _, archivos in os.walk(self.uploads.name)))

    def test_http_413_devuelve_al_panel_con_limite_y_mensaje(self):
        cliente_aprendiz = self.app.test_client()
        cliente_aprendiz.post(
            f'/aprendiz/{self.ficha.id}',
            data={'documento': self.aprendiz.documento},
        )
        self.app.config['MAX_UPLOAD_BYTES'] = 1024 * 1024
        self.app.config['MAX_CONTENT_LENGTH'] = 256

        respuesta = cliente_aprendiz.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{self.tarea.id}',
            data={
                'archivo_evidencia': (
                    BytesIO(b'%PDF-1.4\n evidencia\n%%EOF'),
                    'evidencia.pdf',
                ),
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('la subida supera el límite de 1 MiB'.encode('utf-8'), respuesta.data)
        db.session.refresh(self.entrega)
        self.assertIsNone(self.entrega.archivo_url)
        self.assertFalse(any(archivos for _, _, archivos in os.walk(self.uploads.name)))

    def test_csrf_expirado_en_subida_vuelve_al_panel_con_mensaje(self):
        cliente_aprendiz = self.app.test_client()
        cliente_aprendiz.post(
            f'/aprendiz/{self.ficha.id}',
            data={'documento': self.aprendiz.documento},
        )
        self.app.config['WTF_CSRF_ENABLED'] = True

        respuesta = cliente_aprendiz.post(
            f'/aprendiz/{self.ficha.id}/subir-evidencia/{self.tarea.id}',
            data={
                'archivo_evidencia': (
                    BytesIO(b'%PDF-1.4\n evidencia\n%%EOF'),
                    'evidencia.pdf',
                ),
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('La sesión del formulario expiró'.encode('utf-8'), respuesta.data)
        db.session.refresh(self.entrega)
        self.assertIsNone(self.entrega.archivo_url)
        self.assertFalse(any(archivos for _, _, archivos in os.walk(self.uploads.name)))

    def test_evaluacion_masiva_actualiza_entregas_seleccionadas(self):
        entrega_bruno = Entrega(
            tarea_id=self.tarea.id,
            aprendiz_id=self.otro_aprendiz.id,
            enlace_repositorio='https://example.com/otra-evidencia',
        )
        db.session.add(entrega_bruno)
        db.session.commit()

        pagina = self.cliente.get(f'/instructor/tareas/{self.tarea.id}/entregas')
        self.assertEqual(pagina.status_code, 200)
        self.assertIn('Evaluación masiva'.encode('utf-8'), pagina.data)
        self.assertIn(b'data-entrega-checkbox', pagina.data)

        respuesta = self.cliente.post(
            f'/instructor/tareas/{self.tarea.id}/entregas/evaluar-en-bloque',
            data={
                'entrega_ids': [str(self.entrega.id), str(entrega_bruno.id)],
                'calificacion_general': '4.5',
                'estado_revision_general': 'aprobada',
                'feedback_general': 'Buen trabajo.',
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        for entrega in (self.entrega, entrega_bruno):
            db.session.refresh(entrega)
            self.assertTrue(entrega.calificada)
            self.assertEqual(entrega.calificacion, '4.5')
            self.assertEqual(entrega.estado_revision, 'aprobada')
            self.assertEqual(entrega.feedback, 'Buen trabajo.')
            self.assertEqual(entrega.revisada_por_id, self.instructor.id)

        self.assertEqual(Notificacion.query.filter_by(tipo='calificacion').count(), 2)

    def test_evaluacion_masiva_no_acepta_entrega_de_otra_tarea(self):
        otra_tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo='Otra actividad',
        )
        db.session.add(otra_tarea)
        db.session.flush()
        otra_entrega = Entrega(tarea_id=otra_tarea.id, aprendiz_id=self.aprendiz.id)
        db.session.add(otra_entrega)
        db.session.commit()

        respuesta = self.cliente.post(
            f'/instructor/tareas/{self.tarea.id}/entregas/evaluar-en-bloque',
            data={
                'entrega_ids': [str(self.entrega.id), str(otra_entrega.id)],
                'calificacion_general': '5.0',
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(self.entrega)
        db.session.refresh(otra_entrega)
        self.assertFalse(self.entrega.calificada)
        self.assertFalse(otra_entrega.calificada)

    def test_evaluacion_masiva_rechaza_nota_mayor_al_limite(self):
        respuesta = self.cliente.post(
            f'/instructor/tareas/{self.tarea.id}/entregas/evaluar-en-bloque',
            data={
                'entrega_ids': [str(self.entrega.id)],
                'calificacion_general': '12345678901',
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(self.entrega)
        self.assertFalse(self.entrega.calificada)

    def test_evaluacion_masiva_conserva_calificacion_si_falla_un_resumen(self):
        with patch(
            'app.routes.instructor.actualizar_alertas_ficha',
            side_effect=RuntimeError('alerts unavailable'),
        ), patch(
            'app.routes.instructor.actualizar_participacion_ficha',
            side_effect=RuntimeError('ranking unavailable'),
        ):
            respuesta = self.cliente.post(
                f'/instructor/tareas/{self.tarea.id}/entregas/evaluar-en-bloque',
                data={
                    'entrega_ids': [str(self.entrega.id)],
                    'calificacion_general': '4.0',
                },
            )

        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(self.entrega)
        self.assertTrue(self.entrega.calificada)
        self.assertEqual(self.entrega.calificacion, '4.0')

    def test_evaluacion_individual_registra_revisor_y_aisla_resumenes(self):
        with patch(
            'app.routes.instructor.actualizar_alertas_ficha',
            side_effect=RuntimeError('alerts unavailable'),
        ), patch(
            'app.routes.instructor.actualizar_participacion_ficha',
            side_effect=RuntimeError('ranking unavailable'),
        ):
            respuesta = self.cliente.post(
                f'/instructor/entregas/{self.entrega.id}/calificar',
                data={'calificacion': '4.0', 'estado_revision': 'aprobada'},
            )

        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(self.entrega)
        self.assertTrue(self.entrega.calificada)
        self.assertEqual(self.entrega.revisada_por_id, self.instructor.id)

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

    def test_filtros_raiz_modelos_y_servicios_que_faltaban(self):
        from datetime import date
        from pathlib import Path
        from types import SimpleNamespace

        from app.helpers import obtener_tamanos_materiales
        from app.models.aseo import TurnoAseo
        from app.models.atencion import TurnoAtencion
        from app.models.corte import Corte
        from app.models.material import MaterialFicha
        from app.models.observador import NotaObservador
        from app.services.alertas import ContextoFicha, obtener_config_asistencia
        from app.services.analisis_planeacion import _es_juicio_evaluado, _fecha_texto
        from app.services.archivos import ArchivoService
        from app.services.cortes import siguiente_nombre_corte
        from app.services.festivos import es_dia_habil, nombre_festivo_colombia
        from app.services.graficos_planeacion import _formato_mes_anio
        from app.services.ranking import _alias_aprendiz
        from app.services.recomendaciones import LogroAprendiz, Recomendacion
        from app.services.seguimiento_fases import FASES_PROYECTO, _fase_orden
        from app.services.versiones_archivos import ruta_version

        self.assertEqual(self.cliente.get('/').status_code, 302)
        self.assertEqual(self.app.jinja_env.filters['tipo_competencia']('Competencia técnica'), 'tecnica')
        self.assertEqual(self.app.jinja_env.filters['format_size'](1536), '1.5 KB')

        self.aprendiz.rol_administrativo = True
        self.assertTrue(self.aprendiz.es_aprendiz_administrador)
        self.assertTrue(self.aprendiz.incluido_en_planeacion)
        self.assertIn('Aprendiz', repr(self.aprendiz))
        self.assertIn('Instructor', repr(self.instructor))
        self.assertIn('Ficha', repr(self.ficha))
        self.assertIn('Sesion', repr(self.sesion))
        self.assertIn('Tarea', repr(self.tarea))
        self.assertIn('ProrrogaTarea', repr(ProrrogaTarea(
            tarea_id=self.tarea.id,
            aprendiz_id=self.aprendiz.id,
            instructor_id=self.instructor.id,
            nueva_fecha_limite=datetime.utcnow(),
        )))
        self.assertIn('NotaObservador', repr(NotaObservador(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            instructor_id=self.instructor.id,
            tipo='positiva',
            categoria='compromiso',
            descripcion='Buen trabajo',
        )))
        self.assertIn('MaterialFicha', repr(MaterialFicha(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            nombre_archivo='guia.pdf',
            url_archivo='materiales/guia.pdf',
        )))
        corte = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            nombre='Corte temporal',
            estado='cerrado',
        )
        self.assertTrue(corte.es_consultable)
        self.assertIn('Corte temporal', repr(corte))
        self.assertEqual(siguiente_nombre_corte(self.ficha.id, self.instructor.id), 'Corte 1')

        turno_aseo = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=date.today(),
            aprendiz_1=self.aprendiz,
            aprendiz_2=self.otro_aprendiz,
        )
        self.assertEqual(turno_aseo.aprendices, (self.aprendiz, self.otro_aprendiz))
        self.assertIn('TurnoAtencion', repr(TurnoAtencion(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            estado='esperando',
        )))

        self.tarea.fecha_limite = datetime.utcnow() - timedelta(days=1)
        self.entrega.fecha_entrega = datetime.utcnow()
        self.assertTrue(self.entrega.entregada_con_retraso)
        self.entrega.registrada_por_instructor = True
        self.assertFalse(self.entrega.entregada_con_retraso)

        contexto = ContextoFicha(self.ficha.id)
        self.assertIsNotNone(contexto.config_correo())
        self.assertIsNotNone(obtener_config_asistencia(self.ficha.id))
        self.assertEqual(_fecha_texto(date(2026, 9, 28)), '28/09/2026')
        self.assertTrue(_es_juicio_evaluado('APROBADO'))
        self.assertFalse(_es_juicio_evaluado('POR EVALUAR'))
        self.assertEqual(_formato_mes_anio(date(2026, 1, 1)), 'Ene 26')
        self.assertEqual(_alias_aprendiz(SimpleNamespace(id=7)), 'Aprendiz 007')
        self.assertEqual(_fase_orden(FASES_PROYECTO[0][0]), 0)
        self.assertEqual(nombre_festivo_colombia(date(2026, 1, 1)), 'Año Nuevo')
        self.assertFalse(es_dia_habil(date(2026, 1, 1)))
        self.assertTrue(es_dia_habil(date(2026, 1, 2)))
        self.assertEqual(Recomendacion('a', 'b', 'c', 'd', 'e', 'f').to_dict()['id'], 'a')
        self.assertEqual(LogroAprendiz('a', 'b', 'c', 'd', 'e', 'bronce', False, 0, 1, 0).to_dict()['codigo'], 'a')

        ruta = os.path.join(self.uploads.name, 'cobertura.txt')
        with open(ruta, 'wb') as archivo:
            archivo.write(b'prueba')
        self.assertEqual(ArchivoService.obtener_tamano('cobertura.txt'), 6)
        self.assertTrue(ArchivoService.existe('cobertura.txt'))
        self.assertEqual(ArchivoService.ruta_absoluta('cobertura.txt'), ruta)
        self.assertEqual(ruta_version(SimpleNamespace(ruta_archivo='cobertura.txt'))[1], Path('cobertura.txt'))

        obtener_config_asistencia(self.ficha.id)
        materiales = [SimpleNamespace(id=12, url_archivo='a.pdf')]
        with patch('app.helpers.ArchivoService.obtener_tamano', return_value=42) as obtener_tamano:
            self.assertEqual(obtener_tamanos_materiales(materiales, self.uploads.name), {12: 42})
            obtener_tamano.assert_called_once_with('a.pdf')

    def test_rutas_de_tareas_turnos_ranking_y_seguimiento_pendientes(self):
        from unittest.mock import patch

        from app.models.insignia import Insignia, InsigniaOtorgada
        from app.models.alertas import Notificacion
        from app.models.asistencia import RegistroAsistencia

        ficha_id = self.ficha.id
        aprendiz_id = self.aprendiz.id

        lista = self.cliente.get(f'/instructor/fichas/{ficha_id}/ranking/lista')
        self.assertEqual(lista.status_code, 200)
        self.assertEqual(lista.headers['Cache-Control'], 'no-store, no-cache, must-revalidate, max-age=0')
        respuesta = self.cliente.post(
            f'/instructor/fichas/{ficha_id}/ranking/configuracion',
            data={'peso_asistencia': '30', 'peso_evidencias': '40', 'peso_juicios': '30'},
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(self.cliente.post(
            f'/instructor/fichas/{ficha_id}/insignias/crear',
            data={'nombre': 'Constancia', 'descripcion': 'Cumplió su meta'},
        ).status_code, 302)
        insignia = Insignia.query.filter_by(ficha_id=ficha_id, nombre='Constancia').one()
        self.assertEqual(self.cliente.post(
            f'/instructor/fichas/{ficha_id}/insignias/otorgar',
            data={'aprendiz_id': str(aprendiz_id), 'insignia_id': str(insignia.id)},
        ).status_code, 302)
        self.assertIsNotNone(InsigniaOtorgada.query.filter_by(
            aprendiz_id=aprendiz_id, insignia_id=insignia.id,
        ).first())
        self.assertEqual(self.cliente.post(
            f'/instructor/fichas/{ficha_id}/insignias/{insignia.id}/estado',
        ).status_code, 302)

        estado = self.cliente.get(f'/instructor/fichas/{ficha_id}/importaciones/999999')
        self.assertEqual(estado.status_code, 404)
        self.assertEqual(self.cliente.post(
            f'/instructor/fichas/{ficha_id}/materiales/999999/eliminar',
        ).status_code, 302)
        self.assertEqual(self.cliente.get(
            f'/instructor/fichas/{ficha_id}/fila-atencion/estado-actual',
        ).status_code, 200)

        self.assertEqual(self.cliente.get(
            f'/aprendiz/{ficha_id}/descargar-reporte?documento={self.aprendiz.documento}',
        ).mimetype, 'application/pdf')
        registro = RegistroAsistencia.query.first()
        self.assertEqual(self.cliente.get(
            f'/aprendiz/descargar-soporte/{registro.id}',
        ).status_code, 404)
        with self.cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = self.aprendiz.documento
        self.assertEqual(self.cliente.post(
            f'/aprendiz/{ficha_id}/pedir-turno', data={'motivo': 'Consulta'},
        ).status_code, 302)
        self.assertEqual(self.cliente.post(
            f'/aprendiz/{ficha_id}/cancelar-turno',
        ).status_code, 302)

        self.assertEqual(self.cliente.post(
            f'/instructor/fichas/{ficha_id}/turnos-aseo/999999/editar',
            data={
                'aprendiz_1_id': str(aprendiz_id),
                'aprendiz_2_id': str(self.otro_aprendiz.id),
            },
        ).status_code, 302)
        self.assertEqual(self.cliente.post(
            f'/instructor/fichas/{ficha_id}/turnos-aseo/config',
            data={'aviso_horas': '36', 'excluir_ausentes': 'on'},
        ).status_code, 302)
        self.assertEqual(self.cliente.post(
            f'/instructor/fichas/{ficha_id}/turnos-aseo/exclusion/999999',
        ).status_code, 302)
        self.assertEqual(self.cliente.post(
            f'/aprendiz/{ficha_id}/turnos-aseo/999999/intercambiar',
            data={'documento': self.aprendiz.documento, 'aprendiz_recibe_id': str(self.otro_aprendiz.id)},
        ).status_code, 302)
        self.assertEqual(self.cliente.post(
            f'/aprendiz/{ficha_id}/intercambios/999999/responder',
            data={'documento': self.aprendiz.documento, 'accion': 'rechazar'},
        ).status_code, 302)

        notificacion = Notificacion(
            destinatario_tipo='instructor', destinatario_id=self.instructor.id,
            ficha_id=ficha_id, mensaje='Aviso', tipo='general', clave='test-route-coverage',
        )
        db.session.add(notificacion)
        db.session.commit()
        self.assertEqual(self.cliente.post(
            f'/instructor/notificaciones/{notificacion.id}/leer?redirect_url=/instructor/notificaciones',
        ).status_code, 302)
        self.assertEqual(self.cliente.post('/instructor/notificaciones/leer-todas').status_code, 302)
        self.assertEqual(self.cliente.post(
            f'/instructor/fichas/{ficha_id}/alertas/config-comite',
            data={'umbral_fallas_consecutivas': '4', 'porcentaje_minimo_asistencia': '80'},
        ).status_code, 302)
        self.assertEqual(self.cliente.post(
            f'/instructor/fichas/{ficha_id}/alertas/999999/observacion',
            data={'observaciones': 'Revisado'},
        ).status_code, 302)
        self.assertEqual(self.cliente.post(
            f'/instructor/fichas/{ficha_id}/alertas/999999/escalar',
        ).status_code, 302)
        with patch('app.routes.seguimiento.actualizar_alertas_ficha') as actualizar:
            self.assertEqual(self.cliente.post(
                f'/instructor/fichas/{ficha_id}/alertas/auto-evaluar',
            ).status_code, 302)
            actualizar.assert_called_once_with(ficha_id)

        self.assertEqual(self.cliente.post(
            f'/aprendiz/{ficha_id}/notificaciones/{notificacion.id}/leer',
            data={'documento': self.aprendiz.documento},
        ).status_code, 302)
        self.assertEqual(self.cliente.post(
            f'/aprendiz/{ficha_id}/notificaciones/leer-todas',
            data={'documento': self.aprendiz.documento},
        ).status_code, 302)

    def test_registro_y_manejador_de_caida_de_redis(self):
        from redis.exceptions import RedisError

        with self.cliente.session_transaction() as sesion:
            sesion.clear()
        respuesta = self.cliente.post('/registro', data={})
        self.assertEqual(respuesta.status_code, 200)

        intentos = {'total': 0}

        def falla_una_vez():
            intentos['total'] += 1
            if intentos['total'] == 1:
                raise RedisError('redis intermitente')
            return 'recuperado'

        runtime_app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'UPLOAD_FOLDER': self.uploads.name,
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        runtime_app.add_url_rule('/test/redis-runtime', 'test_redis_runtime', falla_una_vez)
        respuesta = runtime_app.test_client().get('/test/redis-runtime')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.get_data(as_text=True), 'recuperado')
        self.assertEqual(intentos['total'], 2)

    def test_servicios_de_importacion_y_fases_que_faltaban(self):
        from datetime import date
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        from app.services.importacion_jobs import encolar_importacion
        from app.services.fases_dashboard import (
            _calcular_con_planeacion,
            _obtener_planeacion_parseada,
        )

        cliente = Mock()
        with patch('app.services.importacion_jobs._cliente_redis', return_value=cliente):
            encolar_importacion(73, 'fichas')
        cliente.rpush.assert_called_once_with('fichas', '73')
        cliente.close.assert_called_once_with()

        version = SimpleNamespace(
            id=987654321,
            tamano_bytes=1,
            hash_sha256='sin-archivo',
            ruta_archivo='archivo-inexistente.xlsx',
        )
        self.assertIsNone(_obtener_planeacion_parseada(version))

        seguimiento = {
            'fases': [{'orden': 0, 'nombre': 'Análisis'}],
            'fase_esperada': {'orden': 1, 'nombre': 'Planeación'},
            'fase_real': {'orden': 0, 'nombre': 'Análisis'},
            'estado': 'en_riesgo',
            'resultados': {'total': 4, 'aprobados': 2, 'evaluados': 3, 'pendientes': 1, 'porcentaje_aprobados': 50},
        }
        analisis = {'resumen': {'aprendices_analizados': 2}, 'items': []}
        with (
            patch('app.services.fases_dashboard.ultima_version', return_value=None),
            patch('app.services.fases_dashboard.construir_analisis', return_value=analisis),
            patch('app.services.fases_dashboard.construir_calendario', return_value=[]),
            patch('app.services.fases_dashboard.construir_linea_tiempo', return_value=[]),
            patch('app.services.fases_dashboard.construir_seguimiento_fases', return_value=seguimiento),
        ):
            resultado = _calcular_con_planeacion(
                self.ficha,
                version,
                {'planeacion': []},
                date.today(),
            )
        self.assertEqual(resultado['desfase_fases'], 1)
        self.assertEqual(resultado['resumen_raps']['pendientes'], 1)
        self.assertIn('Retraso de 1 fase', resultado['mensaje_veredicto'])

    def test_registro_de_blueprints(self):
        from unittest.mock import Mock, patch

        from app.routes import registrar_rutas
        from app.routes import instructor as instructor_routes

        app_falso = Mock()
        app_falso.config = {'STARTUP_ERRORS': []}
        registrar_rutas(app_falso)
        self.assertEqual(app_falso.register_blueprint.call_count, 13)
        self.assertEqual(app_falso.config['STARTUP_ERRORS'], [])


if __name__ == '__main__':
    unittest.main()
