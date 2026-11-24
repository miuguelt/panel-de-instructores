"""Historial del aprendiz: cada cifra una vez y el detalle después de los indicadores."""

import re
import secrets
import unittest
from datetime import date

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor
from app.models.asistencia import RegistroAsistencia, SesionAsistencia


class HistorialRenderTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
                               'RATELIMIT_ENABLED': False, 'SECRET_KEY': secrets.token_hex(16)})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        instructor = Instructor(nombre='Instructor', correo='historial-render@example.com')
        instructor.set_password(secrets.token_urlsafe(16))
        db.session.add(instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='8181', nombre_programa='Programa Único De Prueba', instructor_id=instructor.id)
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendiz = Aprendiz(documento='55', nombre='Eva', apellidos='Paz', ficha_id=self.ficha.id,
                                 enlace_github='https://github.com/eva/proyecto')
        db.session.add(self.aprendiz)
        db.session.flush()
        for dia, estado in enumerate(['ASISTE', 'FALTA', 'EXCUSA_MEDICA', 'ASISTE'], start=1):
            sesion = SesionAsistencia(ficha_id=self.ficha.id, fecha=date(2026, 9, dia))
            db.session.add(sesion)
            db.session.flush()
            db.session.add(RegistroAsistencia(sesion_id=sesion.id, aprendiz_id=self.aprendiz.id, estado=estado))
        db.session.commit()
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(instructor.id)
            sesion['_fresh'] = True
        respuesta = cliente.get(f'/instructor/fichas/{self.ficha.id}/aprendices/{self.aprendiz.id}/historial')
        self.assertEqual(respuesta.status_code, 200)
        self.html = respuesta.get_data(as_text=True)
        self.contenido = self.html[self.html.index('<main'):]

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_un_solo_main(self):
        self.assertEqual(self.html.count('<main'), 1)

    def test_el_porcentaje_de_asistencia_aparece_una_vez(self):
        # 1 falta sin justificar de 4 sesiones: 75 %.
        # La tendencia mensual es otra lectura (por mes); se excluye del conteo.
        sin_meses = re.sub(r'<div class="report-month-list">[\s\S]*?</section>', '', self.contenido)
        self.assertEqual(sin_meses.count('>75%<'), 1)
        self.assertNotIn('Porcentaje de asistencia', self.contenido)
        self.assertNotIn('Estado integral del aprendiz', self.contenido)

    def test_programa_y_enlaces_una_sola_vez(self):
        self.assertEqual(self.contenido.count('Programa Único De Prueba'), 1)
        self.assertNotIn('🐱 GitHub', self.contenido)
        self.assertIn('https://github.com/eva/proyecto', self.contenido)

    def test_el_portafolio_va_despues_de_los_indicadores(self):
        self.assertLess(self.contenido.index('report-kpi-grid'), self.contenido.index('report-portafolio-card'))

    def test_seguimiento_no_mezcla_insignias(self):
        seguimiento = re.search(r'Seguimiento</span>[\s\S]*?</article>', self.contenido).group(0)
        self.assertNotIn('insignias', seguimiento)


if __name__ == '__main__':
    unittest.main()
