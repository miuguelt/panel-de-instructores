"""Un solo criterio de asistencia: solo las faltas sin justificar restan.

Las faltas justificadas y las excusas médicas se informan aparte, pero no
bajan el porcentaje. El aprendiz y su instructor ven la misma cifra en todas
las pantallas.
"""

import secrets
import unittest
from datetime import date

from flask import template_rendered

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor
from app.models.alertas import ConfiguracionAlertas
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.services.asistencia import serie_asistencia
from app.services.resumen_ficha import calcular_semaforo, obtener_resumen_ficha_360

ESTADOS = ['ASISTE', 'FALTA', 'EXCUSA_MEDICA', 'FALTA_JUSTIFICADA']  # 1 sin justificar de 4 → 75 %


class CriterioAsistenciaTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
                               'RATELIMIT_ENABLED': False, 'SECRET_KEY': secrets.token_hex(16)})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.instructor = Instructor(nombre='Instructor', correo='criterio-asistencia@example.com')
        self.instructor.set_password(secrets.token_urlsafe(16))
        db.session.add(self.instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='6060', nombre_programa='ADSO', instructor_id=self.instructor.id)
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendiz = Aprendiz(documento='888', nombre='Ana', apellidos='Ruiz', ficha_id=self.ficha.id)
        db.session.add(self.aprendiz)
        db.session.flush()
        for dia, estado in enumerate(ESTADOS, start=1):
            sesion = SesionAsistencia(ficha_id=self.ficha.id, fecha=date(2026, 9, dia))
            db.session.add(sesion)
            db.session.flush()
            db.session.add(RegistroAsistencia(sesion_id=sesion.id, aprendiz_id=self.aprendiz.id, estado=estado))
        db.session.commit()
        self.cliente = self.app.test_client()
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True
        self.contextos = []
        template_rendered.connect(self._capturar, self.app)

    def tearDown(self):
        template_rendered.disconnect(self._capturar, self.app)
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _capturar(self, _app, template=None, context=None, **_extra):
        self.contextos.append(context or {})

    def _contexto(self, url, clave):
        respuesta = self.cliente.get(url)
        self.assertEqual(respuesta.status_code, 200, url)
        return next(c[clave] for c in reversed(self.contextos) if clave in c)

    def test_semaforo_de_alertas_y_llamado_a_lista(self):
        config = ConfiguracionAlertas(ficha_id=self.ficha.id)
        stats, _ = calcular_semaforo(self.ficha.id, [self.aprendiz], config)
        self.assertEqual(stats[self.aprendiz.id]['pct_asistencia'], 75.0)

    def test_vision_general(self):
        self.assertEqual(obtener_resumen_ficha_360(self.ficha)['pct_asistencia_global'], 75.0)

    def test_mis_fichas(self):
        extra = self._contexto('/instructor/', 'estadisticas_extra')[self.ficha.id]
        self.assertEqual(extra['pct_asistencia'], 75.0)

    def test_historial_del_instructor(self):
        self.assertEqual(self._contexto(
            f'/instructor/fichas/{self.ficha.id}/aprendices/{self.aprendiz.id}/historial', 'pct_asistencia'), 75.0)

    def test_modal_de_asistencia(self):
        self.assertEqual(self._contexto(
            f'/instructor/fichas/{self.ficha.id}/asistencia/aprendiz/{self.aprendiz.id}/modal', 'pct_asistencia'), 75.0)

    def test_panel_del_aprendiz(self):
        with self.cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = '888'
            sesion['aprendiz_ficha_id'] = self.ficha.id
        self.assertEqual(self._contexto(f'/aprendiz/{self.ficha.id}/panel', 'pct_asistencia'), 75.0)

    def test_tendencia_por_sesion(self):
        # Por sesión: solo la sesión de la falta sin justificar baja a 0 %.
        self.assertEqual([p['pct'] for p in serie_asistencia(self.ficha.id)], [100.0, 0.0, 100.0, 100.0])


if __name__ == '__main__':
    unittest.main()
