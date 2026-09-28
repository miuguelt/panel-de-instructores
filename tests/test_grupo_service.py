from app.models.instructor import Instructor
import unittest
from app import create_app, db
from app.models.ficha import Ficha
from app.models.aprendiz import Aprendiz
from app.models.grupo import Grupo, GrupoAprendiz
from app.services.grupo_service import crear_grupos_aleatorios, archivar_grupos_de_ficha

class TestGrupoService(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_crear_grupos_distribucion_sobrantes(self):
        """Prueba que los sobrantes se distribuyan equitativamente."""
        inst = Instructor(nombre='I', correo='c@c.com', password_hash='x'); db.session.add(inst); db.session.commit(); ficha = Ficha(codigo='123', nombre_programa='X', instructor_id=inst.id)
        db.session.add(ficha)
        db.session.commit()

        ids_aprendices = []
        for i in range(10):
            a = Aprendiz(ficha_id=ficha.id, documento=str(i), nombre=f"A{i}", apellidos="B", estado="En formación")
            db.session.add(a)
            db.session.flush()
            ids_aprendices.append(a.id)
        db.session.commit()

        grupos = crear_grupos_aleatorios(ficha.id, ids_aprendices, tamano_grupo=3)
        
        self.assertEqual(len(grupos), 3)
        tamanos = sorted([len(g.aprendices) for g in grupos])
        self.assertEqual(tamanos, [3, 3, 4])

    def test_archivar_grupos(self):
        inst = Instructor(nombre='I', correo='c@c.com', password_hash='x'); db.session.add(inst); db.session.commit(); ficha = Ficha(codigo='123', nombre_programa='X', instructor_id=inst.id)
        db.session.add(ficha)
        db.session.commit()

        g = Grupo(ficha_id=ficha.id, nombre="Test G1", activo=True)
        db.session.add(g)
        db.session.commit()

        archivar_grupos_de_ficha(ficha.id)

        g_actualizado = db.session.get(Grupo, g.id)
        self.assertFalse(g_actualizado.activo)
