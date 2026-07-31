import unittest
from app import create_app, db
from app.models import Ficha, Instructor, FichaInstructor, JuicioEvaluativo, FichaCompetenciaSeleccionada


class CompetenciasSeleccionadasTestCase(unittest.TestCase):
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

        # Crear instructores
        self.inst1 = Instructor(nombre='Instructor Uno', correo='inst1@sena.edu.co')
        self.inst1.set_password('pass123')
        self.inst2 = Instructor(nombre='Instructor Dos', correo='inst2@sena.edu.co')
        self.inst2.set_password('pass123')
        db.session.add_all([self.inst1, self.inst2])
        db.session.commit()

        # Crear ficha
        self.ficha = Ficha(codigo=222333, nombre_programa='PROD SOFTWARE', instructor_id=self.inst1.id)
        db.session.add(self.ficha)
        db.session.commit()

        # Asociar inst2 a ficha
        fi = FichaInstructor(ficha_id=self.ficha.id, instructor_id=self.inst2.id)
        db.session.add(fi)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _autenticar(self, instructor):
        from flask import g
        g.pop('_login_user', None)
        with self.client.session_transaction() as sesion:
            sesion['_user_id'] = str(instructor.id)
            sesion['_fresh'] = True

    def test_toggle_competencia_seleccion(self):
        self._autenticar(self.inst1)

        # 1. Seleccionar competencia para inst1
        comp_name = "ESTABLECER REQUISITOS DEL SOFTWARE"
        res = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/toggle',
            json={'competencia': comp_name}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'selected')
        self.assertTrue(data['esta_seleccionada'])
        self.assertTrue(data['seleccionada_por']['es_propia'])
        self.assertEqual(data['seleccionada_por']['nombre'], 'Instructor Uno')

        # Verificar persisencia en DB
        sel_db = FichaCompetenciaSeleccionada.query.filter_by(
            ficha_id=self.ficha.id, competencia=comp_name
        ).first()
        self.assertIsNotNone(sel_db)
        self.assertEqual(sel_db.instructor_id, self.inst1.id)

        # 2. Deseleccionar por el mismo instructor (inst1)
        res2 = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/toggle',
            json={'competencia': comp_name}
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2['success'])
        self.assertEqual(data2['action'], 'deselected')
        self.assertFalse(data2['esta_seleccionada'])

        sel_db2 = FichaCompetenciaSeleccionada.query.filter_by(
            ficha_id=self.ficha.id, competencia=comp_name
        ).first()
        self.assertIsNone(sel_db2)

    def test_reinstalar_o_cambiar_seleccion_entre_instructores(self):
        # 1. inst1 selecciona la competencia
        self._autenticar(self.inst1)
        comp_name = "DISEÑAR LA SOLUCION DE SOFTWARE"
        self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/toggle',
            json={'competencia': comp_name}
        )

        # 2. inst2 hace login y toma la competencia
        self._autenticar(self.inst2)

        # inst2 hace toggle en la misma competencia
        res = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/toggle',
            json={'competencia': comp_name}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'selected')
        self.assertTrue(data['seleccionada_por']['es_propia'])
        self.assertEqual(data['seleccionada_por']['nombre'], 'Instructor Dos')

        sel_db = FichaCompetenciaSeleccionada.query.filter_by(
            ficha_id=self.ficha.id, competencia=comp_name
        ).first()
        self.assertEqual(sel_db.instructor_id, self.inst2.id)

    def test_verificacion_permisos(self):
        # Crear instructor3 sin acceso a la ficha
        inst3 = Instructor(nombre='Instructor Tres', correo='inst3@sena.edu.co')
        inst3.set_password('pass123')
        db.session.add(inst3)
        db.session.commit()

        self._autenticar(inst3)
        res = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/toggle',
            json={'competencia': 'COMPETENCIA PRUEBA'}
        )
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertFalse(data['success'])


if __name__ == '__main__':
    unittest.main()
