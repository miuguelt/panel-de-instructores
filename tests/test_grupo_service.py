from app.models.instructor import Instructor
import unittest
from app import create_app, db
from app.models.ficha import Ficha
from app.models.aprendiz import Aprendiz
from app.models.grupo import Grupo, GrupoAprendiz
from app.services.grupo_service import (
    crear_grupos_aleatorios,
    archivar_grupo,
    archivar_grupos_de_ficha,
)

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

    def test_archivar_grupo_devuelve_true_y_archiva(self):
        instructor = Instructor(nombre='I', correo='c@c.com', password_hash='x')
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='123', nombre_programa='X', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.flush()
        grupo = Grupo(ficha_id=ficha.id, nombre='Grupo 1', activo=True)
        db.session.add(grupo)
        db.session.commit()

        resultado = archivar_grupo(grupo.id)

        self.assertTrue(resultado)
        self.assertFalse(db.session.get(Grupo, grupo.id).activo)

    def test_archivar_grupo_inexistente_devuelve_false(self):
        self.assertFalse(archivar_grupo(9999))

    def test_crear_grupos_rechaza_aprendices_de_otra_ficha(self):
        instructor = Instructor(nombre='I', correo='c@c.com', password_hash='x')
        db.session.add(instructor)
        db.session.flush()
        ficha_a = Ficha(codigo='123', nombre_programa='A', instructor_id=instructor.id)
        ficha_b = Ficha(codigo='456', nombre_programa='B', instructor_id=instructor.id)
        db.session.add_all([ficha_a, ficha_b])
        db.session.flush()
        aprendiz = Aprendiz(
            ficha_id=ficha_b.id, documento='1', nombre='Ajeno', apellidos='B',
            estado='En formación'
        )
        db.session.add(aprendiz)
        db.session.commit()

        with self.assertRaisesRegex(ValueError, 'pertenecer a la ficha'):
            crear_grupos_aleatorios(ficha_a.id, [aprendiz.id], tamano_grupo=2)

        self.assertEqual(Grupo.query.filter_by(ficha_id=ficha_a.id).count(), 0)
        self.assertEqual(GrupoAprendiz.query.count(), 0)

    def test_crear_grupos_rechaza_ids_duplicados(self):
        instructor = Instructor(nombre='I', correo='c@c.com', password_hash='x')
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='123', nombre_programa='A', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.flush()
        aprendiz = Aprendiz(
            ficha_id=ficha.id, documento='1', nombre='Uno', apellidos='B',
            estado='En formación'
        )
        db.session.add(aprendiz)
        db.session.commit()

        with self.assertRaisesRegex(ValueError, 'solo puede asignarse'):
            crear_grupos_aleatorios(ficha.id, [aprendiz.id, aprendiz.id], tamano_grupo=2)

        self.assertEqual(Grupo.query.count(), 0)

    def test_crear_grupos_maneja_sin_seleccion_y_tamano_no_positivo(self):
        self.assertEqual(crear_grupos_aleatorios(123, [], tamano_grupo=3), [])
        self.assertEqual(crear_grupos_aleatorios(123, [1], tamano_grupo=0), [])
        self.assertEqual(Grupo.query.count(), 0)

    def test_crear_grupos_rechaza_id_mal_formado_y_aprendiz_inexistente(self):
        instructor = Instructor(nombre='I', correo='c@c.com', password_hash='x')
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='123', nombre_programa='X', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.commit()

        with self.assertRaisesRegex(ValueError, 'selección de aprendices no es válida'):
            crear_grupos_aleatorios(ficha.id, ['inválido'], tamano_grupo=2)
        with self.assertRaisesRegex(ValueError, 'pertenecer a la ficha'):
            crear_grupos_aleatorios(ficha.id, [9999], tamano_grupo=2)
        self.assertEqual(Grupo.query.count(), 0)
