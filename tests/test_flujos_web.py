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
    NotaObservador,
    Notificacion,
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
        self.assertIn(b'Retiro Voluntario', pantalla.data)
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
            )
        self.assertEqual(respuesta.status_code, 302)
        entrega = Entrega.query.filter_by(
            tarea_id=self.tarea.id, aprendiz_id=self.aprendiz.id
        ).one()
        self.assertTrue(entrega.archivo_url)
        self.assertTrue(os.path.isfile(os.path.join(self.uploads.name, entrega.archivo_url)))

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
