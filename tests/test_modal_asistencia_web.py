import re
import tempfile
import unittest
from datetime import date, timedelta

from flask import g

from app import create_app, db
from app.models import (
    Aprendiz,
    ConfiguracionAlertas,
    Ficha,
    Instructor,
    RegistroAsistencia,
    SesionAsistencia,
)


class ModalAsistenciaWebTestCase(unittest.TestCase):
    """El modal de asistencia debe entregar el calendario ya coloreado y
    ligado al aprendiz solicitado, sin depender del estado del cliente."""

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
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='3000009',
            codigo_ficha='3000009',
            nombre_programa='Análisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
            fecha_inicio=date.today() - timedelta(days=30),
            fecha_fin=date.today() + timedelta(days=330),
        )
        db.session.add(self.ficha)
        db.session.flush()
        db.session.add(ConfiguracionAlertas(ficha_id=self.ficha.id))

        self.falton = Aprendiz(documento='2000001', nombre='Ana',
                               apellidos='Faltante', ficha_id=self.ficha.id)
        self.cumplido = Aprendiz(documento='2000002', nombre='Bruno',
                                 apellidos='Cumplido', ficha_id=self.ficha.id)
        db.session.add_all([self.falton, self.cumplido])
        db.session.flush()

        self.dia_falta = date.today() - timedelta(days=2)
        self.dia_tardanza = date.today() - timedelta(days=1)
        for fecha, estado_falton, estado_cumplido in (
            (self.dia_falta, 'FALTA', 'ASISTE'),
            (self.dia_tardanza, 'TARDANZA', 'ASISTE'),
        ):
            sesion = SesionAsistencia(ficha_id=self.ficha.id, fecha=fecha)
            db.session.add(sesion)
            db.session.flush()
            db.session.add_all([
                RegistroAsistencia(sesion_id=sesion.id,
                                   aprendiz_id=self.falton.id,
                                   estado=estado_falton),
                RegistroAsistencia(sesion_id=sesion.id,
                                   aprendiz_id=self.cumplido.id,
                                   estado=estado_cumplido),
            ])
        db.session.commit()

        self.cliente = self.app.test_client()
        g.pop('_login_user', None)
        with self.cliente.session_transaction() as sesion_web:
            sesion_web['_user_id'] = str(self.instructor.id)
            sesion_web['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def _abrir_modal(self, aprendiz):
        respuesta = self.cliente.get(
            f'/instructor/fichas/{self.ficha.id}/asistencia/aprendiz/{aprendiz.id}/modal'
        )
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.get_data(as_text=True)

    def _celdas_pintadas(self, html):
        celdas = re.findall(
            r'<div class="cal-day-cell([^"]*)"\s+data-iso="([^"]+)"', html
        )
        return {iso: clases.strip() for clases, iso in celdas if clases.strip()}

    def test_calendario_llega_coloreado_desde_el_servidor(self):
        pintadas = self._celdas_pintadas(self._abrir_modal(self.falton))
        self.assertEqual(pintadas.get(self.dia_falta.isoformat()), 'is-falta-nj')
        self.assertEqual(pintadas.get(self.dia_tardanza.isoformat()), 'is-tardanza')

    def test_cada_aprendiz_recibe_sus_propios_colores(self):
        pintadas = self._celdas_pintadas(self._abrir_modal(self.cumplido))
        self.assertEqual(pintadas.get(self.dia_falta.isoformat()), 'is-asiste')
        self.assertEqual(pintadas.get(self.dia_tardanza.isoformat()), 'is-asiste')
        self.assertNotIn('is-falta-nj', ''.join(pintadas.values()))

    def test_los_datos_y_el_script_viven_dentro_del_modal(self):
        html = self._abrir_modal(self.falton)
        cuerpo_modal = html[html.index('data-asistencia-modal'):html.rindex('</div>')]
        self.assertIn('data-asistencia-data', cuerpo_modal)
        self.assertIn('data-calendar-grid', cuerpo_modal)
        # Sin declaraciones globales: htmx reejecuta el script en cada apertura.
        self.assertNotIn('const asistenciaMapData =', html)

    def test_el_modal_identifica_al_aprendiz(self):
        html = self._abrir_modal(self.cumplido)
        self.assertIn(f'data-aprendiz-id="{self.cumplido.id}"', html)


if __name__ == '__main__':
    unittest.main()
