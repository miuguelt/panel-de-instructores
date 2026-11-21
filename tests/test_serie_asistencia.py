"""Serie de asistencia por sesión para la tendencia del llamado a lista."""

import secrets
import unittest
from datetime import date

from app import create_app, db
from app.models import Ficha, Instructor
from app.models.aprendiz import Aprendiz
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.services.asistencia import serie_asistencia


class SerieAsistenciaTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        instructor = Instructor(nombre='Instructor', correo='serie@example.com')
        instructor.set_password(secrets.token_urlsafe(16))
        db.session.add(instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='111', nombre_programa='ADSO', instructor_id=instructor.id)
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendices = [Aprendiz(documento=str(i), nombre=f'A{i}', apellidos='B', ficha_id=self.ficha.id)
                           for i in range(4)]
        db.session.add_all(self.aprendices)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def sesion(self, fecha, estados, ficha_id=None):
        sesion = SesionAsistencia(ficha_id=ficha_id or self.ficha.id, fecha=fecha)
        db.session.add(sesion)
        db.session.flush()
        for aprendiz, estado in zip(self.aprendices, estados):
            db.session.add(RegistroAsistencia(sesion_id=sesion.id, aprendiz_id=aprendiz.id, estado=estado))
        db.session.commit()
        return sesion

    def test_porcentaje_por_sesion_en_orden_cronologico(self):
        self.sesion(date(2026, 3, 2), ['ASISTE', 'FALTA', 'TARDANZA', 'EXCUSA_MEDICA'])
        self.sesion(date(2026, 3, 1), ['ASISTE', 'ASISTE', 'ASISTE', 'ASISTE'])
        serie = serie_asistencia(self.ficha.id)
        self.assertEqual([p['fecha'] for p in serie], [date(2026, 3, 1), date(2026, 3, 2)])
        # Tardanza cuenta como presencia; faltas y excusas no.
        self.assertEqual([p['pct'] for p in serie], [100.0, 50.0])
        self.assertEqual(serie[1]['presentes'], 2)
        self.assertEqual(serie[1]['registros'], 4)

    def test_limita_a_las_ultimas_sesiones(self):
        for dia in range(1, 8):
            self.sesion(date(2026, 4, dia), ['ASISTE', 'FALTA', 'ASISTE', 'ASISTE'])
        serie = serie_asistencia(self.ficha.id, limite=3)
        self.assertEqual([p['fecha'].day for p in serie], [5, 6, 7])

    def test_sesion_sin_registros_se_omite_y_sin_sesiones_queda_vacia(self):
        self.assertEqual(serie_asistencia(self.ficha.id), [])
        db.session.add(SesionAsistencia(ficha_id=self.ficha.id, fecha=date(2026, 5, 1)))
        db.session.commit()
        self.assertEqual(serie_asistencia(self.ficha.id), [])

    def test_filtra_por_corte(self):
        sesion = self.sesion(date(2026, 6, 1), ['ASISTE'] * 4)
        sesion.corte_id = 99
        db.session.commit()
        self.sesion(date(2026, 6, 2), ['FALTA'] * 4)
        self.assertEqual([p['pct'] for p in serie_asistencia(self.ficha.id, corte_id=99)], [100.0])
        self.assertEqual(len(serie_asistencia(self.ficha.id)), 2)


if __name__ == '__main__':
    unittest.main()


class ResumenAsistenciaAprendizTest(unittest.TestCase):
    """El porcentaje y el texto «X de Y sesiones» salen de la misma fórmula."""

    def test_solo_las_faltas_sin_justificar_restan(self):
        from app.services.asistencia import resumen_asistencia_aprendiz
        resumen = resumen_asistencia_aprendiz(total_sesiones=20, faltas_no_justificadas=3)
        self.assertEqual(resumen, {'pct': 85.0, 'sesiones_cumplidas': 17, 'total_sesiones': 20})

    def test_sin_sesiones_no_hay_porcentaje(self):
        from app.services.asistencia import resumen_asistencia_aprendiz
        self.assertEqual(resumen_asistencia_aprendiz(0, 0),
                         {'pct': None, 'sesiones_cumplidas': 0, 'total_sesiones': 0})

    def test_mas_faltas_que_sesiones_se_acota(self):
        from app.services.asistencia import resumen_asistencia_aprendiz
        self.assertEqual(resumen_asistencia_aprendiz(2, 5)['pct'], 0.0)
