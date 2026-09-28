import unittest
from app import create_app, db
from app.models.instructor import Instructor
from app.models.ficha import Ficha
from app.models.aprendiz import Aprendiz
from app.models.grupo import Grupo

class TestGruposRoutes(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_generar_grupos_route(self):
        # Setup data
        inst = Instructor(nombre='I', correo='c@c.com', password_hash='x')
        db.session.add(inst)
        db.session.commit()
        
        ficha = Ficha(codigo='123', nombre_programa='X', instructor_id=inst.id)
        db.session.add(ficha)
        db.session.commit()

        aprendices_ids = []
        for i in range(5):
            a = Aprendiz(ficha_id=ficha.id, documento=str(i), nombre=f"A{i}", apellidos="B", estado="En formación")
            db.session.add(a)
            db.session.flush()
            aprendices_ids.append(a.id)
        db.session.commit()

        # Login
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(inst.id)
            sess['_fresh'] = True

        # Enviar petición POST
        response = self.client.post(f'/instructor/fichas/{ficha.id}/grupos/generar', data={
            'tamano_grupo': '2',
            'aprendices_ids[]': aprendices_ids
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Grupos generados exitosamente.', response.data)

        grupos_creados = Grupo.query.filter_by(ficha_id=ficha.id, activo=True).all()
        self.assertEqual(len(grupos_creados), 2)

    def test_otorgar_insignia_route(self):
        from app.models.insignia import Insignia, InsigniaOtorgada
        
        inst = Instructor(nombre='I', correo='c@c.com', password_hash='x')
        db.session.add(inst)
        db.session.commit()
        
        ficha = Ficha(codigo='123', nombre_programa='X', instructor_id=inst.id)
        db.session.add(ficha)
        db.session.commit()

        grupo = Grupo(ficha_id=ficha.id, nombre="Grupo 1")
        db.session.add(grupo)
        
        insignia = Insignia(ficha_id=ficha.id, nombre="Buena", descripcion="Test", icono="a")
        db.session.add(insignia)
        db.session.commit()

        # Login
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(inst.id)
            sess['_fresh'] = True

        response = self.client.post(f'/instructor/fichas/{ficha.id}/grupos/otorgar_insignia', data={
            'grupo_id': grupo.id,
            'insignia_id': insignia.id
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Insignia otorgada al grupo correctamente.', response.data)

        otorgada = InsigniaOtorgada.query.filter_by(grupo_id=grupo.id, insignia_id=insignia.id).first()
        self.assertIsNotNone(otorgada)
