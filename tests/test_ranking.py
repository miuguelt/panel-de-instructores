import unittest
from datetime import date, datetime, timedelta

from app import create_app, db
from app.models import (
    Aprendiz,
    ConfiguracionRanking,
    Entrega,
    Ficha,
    Insignia,
    InsigniaOtorgada,
    Instructor,
    PuntajeHistorico,
    RegistroAsistencia,
    SesionAsistencia,
    Tarea,
)
from app.services.ranking import actualizar_participacion_ficha, calcular_ranking


class RankingTestCase(unittest.TestCase):
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
            nombre='Instructor Prueba',
            correo='pruebas@sena.edu.co',
            rol='admin',
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()
        self.ficha = Ficha(
            codigo='2999999',
            nombre_programa='Análisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
        )
        db.session.add(self.ficha)
        db.session.flush()
        self.ana = Aprendiz(
            documento='1001',
            nombre='Ana',
            apellidos='Ávila',
            ficha_id=self.ficha.id,
        )
        self.bruno = Aprendiz(
            documento='1002',
            nombre='Bruno',
            apellidos='Bello',
            ficha_id=self.ficha.id,
        )
        db.session.add_all([self.ana, self.bruno])
        db.session.add(ConfiguracionRanking(ficha_id=self.ficha.id))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _sesion(self, dias_atras, estados):
        sesion = SesionAsistencia(
            ficha_id=self.ficha.id,
            fecha=date.today() - timedelta(days=dias_atras),
        )
        db.session.add(sesion)
        db.session.flush()
        for aprendiz, estado in estados:
            db.session.add(RegistroAsistencia(
                sesion_id=sesion.id,
                aprendiz_id=aprendiz.id,
                estado=estado,
            ))

    def test_falla_justificada_no_baja_porcentaje_ni_penaliza(self):
        self._sesion(2, [(self.ana, 'ASISTE'), (self.bruno, 'ASISTE')])
        self._sesion(1, [(self.ana, 'FALTA_JUSTIFICADA'), (self.bruno, 'ASISTE')])
        self._sesion(0, [(self.ana, 'FALTA'), (self.bruno, 'ASISTE')])
        db.session.commit()

        filas, _ = calcular_ranking(self.ficha.id)
        por_id = {fila['aprendiz'].id: fila for fila in filas}

        self.assertEqual(por_id[self.ana.id]['porcentaje_asistencia'], 50.0)
        self.assertEqual(por_id[self.ana.id]['penalizacion'], 1.0)
        self.assertEqual(por_id[self.bruno.id]['porcentaje_asistencia'], 100.0)
        self.assertEqual(por_id[self.bruno.id]['penalizacion'], 0.0)

    def test_sin_actividad_el_puntaje_inicia_en_cero(self):
        filas, _ = calcular_ranking(self.ficha.id)
        self.assertTrue(all(fila['puntaje_total'] == 0 for fila in filas))

    def test_entregas_tempranas_otorgan_logros_permanentes(self):
        for numero in range(5):
            tarea = Tarea(
                ficha_id=self.ficha.id,
                instructor_id=self.instructor.id,
                titulo=f'Actividad {numero + 1}',
                fecha_limite=datetime.utcnow() + timedelta(days=numero + 2),
            )
            db.session.add(tarea)
            db.session.flush()
            db.session.add(Entrega(
                tarea_id=tarea.id,
                aprendiz_id=self.ana.id,
                fecha_entrega=datetime.utcnow(),
            ))
        db.session.commit()

        actualizar_participacion_ficha(self.ficha.id)
        nombres = {
            otorgamiento.insignia.nombre
            for otorgamiento in InsigniaOtorgada.query.filter_by(
                aprendiz_id=self.ana.id
            ).all()
        }
        self.assertIn('Primero en Entregar', nombres)
        self.assertIn('Nunca Tarde', nombres)
        self.assertEqual(PuntajeHistorico.query.count(), 2)

        # Recalcular no quita ni duplica los logros.
        actualizar_participacion_ficha(self.ficha.id)
        self.assertEqual(
            InsigniaOtorgada.query.filter_by(aprendiz_id=self.ana.id).count(),
            len(nombres),
        )

    def test_paginas_y_exportaciones_responden(self):
        actualizar_participacion_ficha(self.ficha.id)
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True

        rutas = (
            f'/instructor/fichas/{self.ficha.id}/ranking',
            f'/instructor/fichas/{self.ficha.id}/insignias',
            f'/instructor/fichas/{self.ficha.id}/ranking/exportar?formato=excel',
            f'/instructor/fichas/{self.ficha.id}/ranking/exportar?formato=pdf',
            f'/instructor/fichas/{self.ficha.id}/insignias/exportar?formato=excel',
            f'/instructor/fichas/{self.ficha.id}/insignias/exportar?formato=pdf',
            f'/aprendiz/{self.ficha.id}/panel?documento={self.ana.documento}',
        )
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(cliente.get(ruta).status_code, 200)

        self.assertEqual(Insignia.query.filter_by(ficha_id=self.ficha.id).count(), 9)


if __name__ == '__main__':
    unittest.main()
