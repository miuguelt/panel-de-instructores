import unittest
from datetime import date, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory

import openpyxl

from app import create_app, db
from app.models import (
    Aprendiz,
    ConfiguracionAlertas,
    ConfiguracionRanking,
    Ficha,
    Instructor,
    RegistroAsistencia,
    SesionAsistencia,
    TurnoAseo,
    ArchivoFichaVersion,
    JuicioEvaluativo,
)


class AprendizAdministradorTestCase(unittest.TestCase):
    def setUp(self):
        self.uploads = TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'UPLOAD_FOLDER': self.uploads.name,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Instructor Principal',
            correo='admin-aprendices@sena.edu.co',
            rol='admin',
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()
        self.ficha = Ficha(
            codigo='2999999',
            codigo_ficha='2999999',
            nombre_programa='Análisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
            fecha_inicio=date.today(),
        )
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendices = [
            Aprendiz(
                documento=f'90000{i}',
                nombre=nombre,
                apellidos='Prueba',
                ficha_id=self.ficha.id,
                estado='EN_FORMACION',
            )
            for i, nombre in enumerate(('Ana', 'Bruno', 'Carmen'), start=1)
        ]
        db.session.add_all([
            ConfiguracionAlertas(ficha_id=self.ficha.id),
            ConfiguracionRanking(ficha_id=self.ficha.id),
            *self.aprendices,
        ])
        db.session.commit()
        self.cliente = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def _sesion_aprendiz(self, aprendiz=None):
        aprendiz = aprendiz or self.aprendices[0]
        with self.cliente.session_transaction() as estado:
            estado['aprendiz_documento'] = aprendiz.documento
            estado['aprendiz_ficha_id'] = self.ficha.id

    def _sesion_instructor(self):
        with self.cliente.session_transaction() as estado:
            estado['_user_id'] = str(self.instructor.id)
            estado['_fresh'] = True

    def test_instructor_puede_asignar_un_unico_aprendiz_administrador(self):
        self._sesion_instructor()

        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/aprendices/'
            f'{self.aprendices[1].id}/rol-administrativo',
            data={'accion': 'activar'},
        )

        self.assertEqual(respuesta.status_code, 302)
        db.session.expire_all()
        self.assertFalse(db.session.get(Aprendiz, self.aprendices[0].id).rol_administrativo)
        self.assertTrue(db.session.get(Aprendiz, self.aprendices[1].id).rol_administrativo)

    def test_aprendiz_administrador_gestiona_aseo_y_llamado_a_lista(self):
        self.aprendices[0].rol_administrativo = True
        db.session.commit()
        self._sesion_aprendiz()
        from app.services.festivos import es_dia_habil
        fecha = date.today() + timedelta(days=1)
        while not es_dia_habil(fecha):
            fecha += timedelta(days=1)

        generar = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/generar',
            data={
                'fecha_inicio': fecha.isoformat(),
                'fecha_fin': fecha.isoformat(),
            },
        )

        self.assertEqual(generar.status_code, 302)
        turno = TurnoAseo.query.filter_by(
            ficha_id=self.ficha.id,
            fecha=fecha,
        ).one()
        nuevo_primero = self.aprendices[1]
        nuevo_segundo = self.aprendices[2]
        editar = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno.id}/editar',
            data={
                'aprendiz_1_id': nuevo_primero.id,
                'aprendiz_2_id': nuevo_segundo.id,
                'observacion': 'Cambio operativo autorizado',
            },
        )
        self.assertEqual(editar.status_code, 302)
        db.session.refresh(turno)
        self.assertEqual(turno.generado_por, 'aprendiz_admin')
        self.assertEqual({turno.aprendiz_1_id, turno.aprendiz_2_id}, {
            nuevo_primero.id,
            nuevo_segundo.id,
        })

        cumplir = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno.id}/cumplir',
        )
        self.assertEqual(cumplir.status_code, 302)
        db.session.refresh(turno)
        self.assertEqual(turno.estado, 'cumplido')

        fecha_lista = date.today() + timedelta(days=2)
        asistencia = {'fecha': fecha_lista.isoformat()}
        for aprendiz in self.aprendices:
            asistencia[f'asistencia_{aprendiz.id}'] = 'ASISTE'
        llamado = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/asistencia/gestionar',
            data=asistencia,
        )
        self.assertEqual(llamado.status_code, 302)
        sesion = SesionAsistencia.query.filter_by(
            ficha_id=self.ficha.id,
            fecha=fecha_lista,
        ).one()
        self.assertEqual(sesion.registros.count(), 3)
        self.assertEqual(
            RegistroAsistencia.query.filter_by(
                sesion_id=sesion.id,
                estado='ASISTE',
            ).count(),
            3,
        )

    def test_aprendiz_sin_rol_no_puede_generar_ni_cumplir_aseo(self):
        self._sesion_aprendiz(self.aprendices[1])
        administrador = self.aprendices[0]
        administrador.rol_administrativo = True
        db.session.commit()
        from app.services.festivos import es_dia_habil
        fecha = date.today() + timedelta(days=1)
        while not es_dia_habil(fecha):
            fecha += timedelta(days=1)

        # 1. No puede generar turnos, aunque envíe el documento del administrador.
        respuesta = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/generar',
            data={
                'fecha_inicio': fecha.isoformat(),
                'fecha_fin': fecha.isoformat(),
                'documento': administrador.documento,
            },
            follow_redirects=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        turno = TurnoAseo.query.filter_by(ficha_id=self.ficha.id, fecha=fecha).first()
        self.assertIsNone(turno)

        # 2. Tampoco puede cambiar el estado de un turno existente.
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha,
            aprendiz_1_id=administrador.id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
        )
        db.session.add(turno)
        db.session.commit()
        resp_cumplir = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno.id}/cumplir',
            data={'documento': administrador.documento},
            follow_redirects=True,
        )
        self.assertEqual(resp_cumplir.status_code, 200)
        db.session.refresh(turno)
        self.assertEqual(turno.estado, 'programado')

        # 3. Asistencia / llamado a lista sigue estrictamente protegido para el aprendiz administrador
        fecha_asistencia = date.today() + timedelta(days=2)
        resp_asistencia = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/asistencia/gestionar',
            data={'fecha': fecha_asistencia.isoformat()},
            follow_redirects=True,
        )
        self.assertIn('solo está disponible para el aprendiz administrador'.encode(), resp_asistencia.data)

    def test_usuario_no_autorizado_no_puede_generar_turnos(self):
        with self.cliente.session_transaction() as s:
            s.clear()

        fecha = date.today() + timedelta(days=1)
        resp = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/generar',
            data={'fecha_inicio': fecha.isoformat(), 'fecha_fin': fecha.isoformat()},
            follow_redirects=True,
        )
        self.assertIn('No tienes permiso para generar turnos de aseo'.encode(), resp.data)

    def test_las_interfaces_delegadas_quedan_visibles_para_cada_rol(self):
        self._sesion_instructor()
        directorio = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/aprendices'
        )
        configuracion = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/aprendices/configuracion'
        )
        self.assertEqual(directorio.status_code, 200)
        self.assertEqual(configuracion.status_code, 200)
        self.assertIn(b'3 herramientas', directorio.data)
        self.assertIn(b'aria-describedby="archivo-aprendices-ayuda"', directorio.data)
        self.assertIn(b'aria-describedby="aprendiz-administrativo-ayuda"', directorio.data)
        self.assertIn(b'class="qr-loading"', directorio.data)
        self.assertNotIn(b'style="align-self: flex-end;"', directorio.data)
        self.assertIn(b'Guardar aprendiz administrador', configuracion.data)

        self.aprendices[0].rol_administrativo = True
        db.session.commit()
        self._sesion_aprendiz()
        gestion_aseo = self.cliente.get(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/gestionar'
        )
        llamado = self.cliente.get(
            f'/aprendiz/{self.ficha.id}/asistencia/gestionar'
        )
        self.assertEqual(gestion_aseo.status_code, 200)
        self.assertEqual(llamado.status_code, 200)
        self.assertIn(b'Guardar llamado a lista', llamado.data)
        self.assertIn(b'id="gestion-aseo-resumen"', gestion_aseo.data)
        self.assertIn(b'id="form-generar-turnos"', gestion_aseo.data)
        self.assertIn(b'id="form-asignar-turno"', gestion_aseo.data)
        self.assertIn(b'Registrar llamado a lista', gestion_aseo.data)

    def test_no_se_puede_delegar_el_rol_a_un_aprendiz_retirado(self):
        self.aprendices[2].estado = 'RETIRADO'
        db.session.commit()
        self._sesion_instructor()

        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/aprendices/'
            f'{self.aprendices[2].id}/rol-administrativo',
            data={'accion': 'activar'},
        )

        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(self.aprendices[2])
        self.assertFalse(self.aprendices[2].rol_administrativo)

    def test_la_carga_de_documentos_puede_dejar_asignado_el_rol(self):
        self._sesion_instructor()
        self.ficha.codigo_programa = '228117'
        db.session.commit()
        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.append(['Ficha de Caracterización:', '', self.ficha.codigo])
        hoja.append(['Código:', '', self.ficha.codigo_programa])
        hoja.append(['Denominación:', '', self.ficha.nombre_programa])
        for _ in range(10):
            hoja.append([])
        hoja.append(['Tipo de Documento', 'Número de Documento', 'Nombre', 'Apellidos', 'Estado',
                     'Competencia', 'Resultado de Aprendizaje', 'Juicio de Evaluación',
                     'Fecha y Hora del Juicio Evaluativo', 'Funcionario que registro el juicio evaluativo'])
        aprendiz = self.aprendices[2]
        hoja.append(['CC', aprendiz.documento, aprendiz.nombre, aprendiz.apellidos, 'EN_FORMACION',
                     'Competencia de prueba', 'Resultado de prueba', 'APROBADO', '01/10/2026', 'Instructor de prueba'])
        contenido = BytesIO()
        libro.save(contenido)
        datos_originales = contenido.getvalue()
        contenido.seek(0)
        respuesta = self.cliente.post(
            f'/instructor/fichas/{self.ficha.id}/cargar-excel',
            data={'aprendiz_administrativo_id': aprendiz.id, 'archivo': (contenido, 'reporte.xlsx')},
            content_type='multipart/form-data',
        )
        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(aprendiz)
        self.assertTrue(aprendiz.rol_administrativo)
        self.assertEqual(JuicioEvaluativo.query.filter_by(aprendiz_id=aprendiz.id).count(), 1)
        version = ArchivoFichaVersion.query.filter_by(ficha_id=self.ficha.id).one()
        from pathlib import Path
        self.assertEqual(Path(self.uploads.name, version.ruta_archivo).read_bytes(), datos_originales)

    def test_aprendiz_administrador_asigna_turno_manual_y_crea_sesion(self):
        self.aprendices[0].rol_administrativo = True
        db.session.commit()
        self._sesion_aprendiz(self.aprendices[0])

        fecha_manual = date.today() + timedelta(days=4)
        from app.services.festivos import es_festivo_colombia
        while es_festivo_colombia(fecha_manual):
            fecha_manual += timedelta(days=1)

        # 1. Asignación válida
        resp = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/asignar',
            data={
                'fecha': fecha_manual.isoformat(),
                'aprendiz_1_id': self.aprendices[1].id,
                'aprendiz_2_id': self.aprendices[2].id,
                'observacion': 'Asignación manual de delegada',
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        turno = TurnoAseo.query.filter_by(
            ficha_id=self.ficha.id, fecha=fecha_manual
        ).first()
        self.assertIsNotNone(turno)
        self.assertEqual(turno.generado_por, 'aprendiz_admin')
        self.assertIn('el aprendiz administrador Ana', turno.auditoria_1)
        # Verifica que la sesión de asistencia fue creada automáticamente
        sesion = SesionAsistencia.query.filter_by(
            ficha_id=self.ficha.id, fecha=fecha_manual
        ).first()
        self.assertIsNotNone(sesion)

        # 2. Intento de asignar al mismo aprendiz en ambas posiciones es rechazado
        resp_mismo = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/asignar',
            data={
                'fecha': (fecha_manual + timedelta(days=1)).isoformat(),
                'aprendiz_1_id': self.aprendices[1].id,
                'aprendiz_2_id': self.aprendices[1].id,
            },
            follow_redirects=True,
        )
        self.assertIn('dos aprendices diferentes'.encode(), resp_mismo.data)

        # 3. Intento de asignar a un aprendiz retirado es rechazado
        self.aprendices[2].estado = 'RETIRADO'
        db.session.commit()
        resp_retirado = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/asignar',
            data={
                'fecha': (fecha_manual + timedelta(days=2)).isoformat(),
                'aprendiz_1_id': self.aprendices[1].id,
                'aprendiz_2_id': self.aprendices[2].id,
            },
            follow_redirects=True,
        )
        self.assertIn('no está en formación activa'.encode(), resp_retirado.data)

    def test_panel_muestra_enlace_gestion_y_solicitudes_salientes(self):
        self.aprendices[0].rol_administrativo = True
        db.session.commit()
        self._sesion_aprendiz(self.aprendices[0])

        # Crear turno propio en fecha futura
        fecha_turno = date.today() + timedelta(days=3)
        turno_propio = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=fecha_turno,
            aprendiz_1_id=self.aprendices[0].id,
            aprendiz_2_id=self.aprendices[1].id,
            estado='programado',
            generado_por='sistema',
        )
        db.session.add(turno_propio)
        db.session.commit()

        # Enviar solicitud de intercambio hacia aprendiz 2 (Carmen)
        resp_intercambio = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/{turno_propio.id}/intercambiar',
            data={'aprendiz_recibe_id': self.aprendices[2].id},
            follow_redirects=True,
        )
        self.assertEqual(resp_intercambio.status_code, 200)

        # Cargar panel y verificar solicitud saliente y botón de gestión
        resp_panel = self.cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(resp_panel.status_code, 200)
        self.assertIn('Solicitud de intercambio enviada'.encode(), resp_panel.data)
        self.assertIn('Gestionar y asignar turnos de aseo'.encode(), resp_panel.data)


if __name__ == '__main__':
    unittest.main()

