import unittest
from datetime import date, timedelta
from io import BytesIO
from unittest.mock import patch

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
)


class AprendizAdministradorTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
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
        fecha = date.today() + timedelta(days=1)

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

    def test_aprendiz_sin_rol_no_puede_modificar_aseo_ni_asistencia(self):
        self._sesion_aprendiz()
        fecha = date.today() + timedelta(days=1)

        respuesta = self.cliente.post(
            f'/aprendiz/{self.ficha.id}/turnos-aseo/generar',
            data={
                'fecha_inicio': fecha.isoformat(),
                'fecha_fin': fecha.isoformat(),
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(TurnoAseo.query.count(), 0)

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
        version = ArchivoFichaVersion(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            tipo='reporte_juicios',
            version=1,
            nombre_archivo='reporte.xlsx',
            ruta_archivo='fichas/reporte.xlsx',
            tamano_bytes=1,
            estado='pendiente',
        )
        resultado = {
            'ficha': self.ficha,
            'nuevos': 0,
            'actualizados': 0,
            'juicios_nuevos': 0,
            'juicios_actualizados': 0,
            'juicios_repetidos': 0,
            'errores': [],
        }
        with patch('app.routes.instructor.leer_metadata_archivo', return_value={}), \
                patch('app.routes.instructor.validar_reporte_ficha'), \
                patch('app.routes.instructor.crear_version', return_value=version), \
                patch('app.routes.instructor.importar_archivo', return_value=resultado), \
                patch('app.routes.instructor.actualizar_alertas_ficha'), \
                patch('app.routes.instructor.actualizar_participacion_ficha'):
            respuesta = self.cliente.post(
                f'/instructor/fichas/{self.ficha.id}/cargar-excel',
                data={
                    'aprendiz_administrativo_id': self.aprendices[2].id,
                    'archivo': (BytesIO(b'archivo de prueba'), 'reporte.xlsx'),
                },
                content_type='multipart/form-data',
            )

        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(self.aprendices[2])
        self.assertTrue(self.aprendices[2].rol_administrativo)


if __name__ == '__main__':
    unittest.main()
