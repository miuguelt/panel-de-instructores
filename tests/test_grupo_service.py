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
    editar_grupo,
    crear_grupo_manual,
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

    def test_editar_grupo_actualiza_nombre_y_aprendices(self):
        instructor = Instructor(nombre='I', correo='c@c.com', password_hash='x')
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='123', nombre_programa='X', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.flush()

        a1 = Aprendiz(ficha_id=ficha.id, documento='1', nombre='A1', apellidos='B', estado='En formación')
        a2 = Aprendiz(ficha_id=ficha.id, documento='2', nombre='A2', apellidos='B', estado='En formación')
        a3 = Aprendiz(ficha_id=ficha.id, documento='3', nombre='A3', apellidos='B', estado='En formación')
        db.session.add_all([a1, a2, a3])
        db.session.flush()

        grupo = Grupo(ficha_id=ficha.id, nombre='Grupo Original', activo=True)
        db.session.add(grupo)
        db.session.flush()
        db.session.add(GrupoAprendiz(grupo_id=grupo.id, aprendiz_id=a1.id))
        db.session.commit()

        # Editar grupo: cambiar nombre y asignar a2 y a3 (removiendo a1)
        grupo_editado = editar_grupo(grupo.id, 'Grupo Alfa', [a2.id, a3.id])

        self.assertEqual(grupo_editado.nombre, 'Grupo Alfa')
        miembros_ids = {ap.id for ap in grupo_editado.aprendices}
        self.assertEqual(miembros_ids, {a2.id, a3.id})
        self.assertNotIn(a1.id, miembros_ids)

    def test_editar_grupo_reasigna_aprendiz_de_otro_grupo_activo(self):
        instructor = Instructor(nombre='I', correo='c@c.com', password_hash='x')
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='123', nombre_programa='X', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.flush()

        a1 = Aprendiz(ficha_id=ficha.id, documento='1', nombre='A1', apellidos='B', estado='En formación')
        a2 = Aprendiz(ficha_id=ficha.id, documento='2', nombre='A2', apellidos='B', estado='En formación')
        db.session.add_all([a1, a2])
        db.session.flush()

        g1 = Grupo(ficha_id=ficha.id, nombre='G1', activo=True)
        g2 = Grupo(ficha_id=ficha.id, nombre='G2', activo=True)
        db.session.add_all([g1, g2])
        db.session.flush()

        db.session.add(GrupoAprendiz(grupo_id=g1.id, aprendiz_id=a1.id))
        db.session.add(GrupoAprendiz(grupo_id=g2.id, aprendiz_id=a2.id))
        db.session.commit()

        # Asignar a2 a g1: a2 debe removerse de g2 y quedar en g1
        editar_grupo(g1.id, 'G1 Modificado', [a1.id, a2.id])

        self.assertEqual({ap.id for ap in g1.aprendices}, {a1.id, a2.id})
        # g2 ahora debe estar vacío
        self.assertEqual(len(g2.aprendices), 0)

    def test_editar_grupo_desasigna_aprendices_no_incluidos(self):
        instructor = Instructor(nombre='I', correo='c@c.com', password_hash='x')
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='123', nombre_programa='X', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.flush()

        a1 = Aprendiz(ficha_id=ficha.id, documento='1', nombre='A1', apellidos='B', estado='En formación')
        db.session.add(a1)
        db.session.flush()

        grupo = Grupo(ficha_id=ficha.id, nombre='Grupo', activo=True)
        db.session.add(grupo)
        db.session.flush()
        db.session.add(GrupoAprendiz(grupo_id=grupo.id, aprendiz_id=a1.id))
        db.session.commit()

        # Dejar grupo sin aprendices
        editar_grupo(grupo.id, 'Grupo Vacío', [])
        self.assertEqual(len(grupo.aprendices), 0)

    def test_editar_grupo_valida_nombre_y_existencia(self):
        instructor = Instructor(nombre='I', correo='c@c.com', password_hash='x')
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='123', nombre_programa='X', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.flush()
        grupo_inactivo = Grupo(ficha_id=ficha.id, nombre='Inactivo', activo=False)
        grupo_activo = Grupo(ficha_id=ficha.id, nombre='Activo', activo=True)
        db.session.add_all([grupo_inactivo, grupo_activo])
        db.session.commit()

        with self.assertRaisesRegex(ValueError, 'no existe o se encuentra inactivo'):
            editar_grupo(9999, 'Nuevo', [])

        with self.assertRaisesRegex(ValueError, 'no existe o se encuentra inactivo'):
            editar_grupo(grupo_inactivo.id, 'Nuevo', [])

        with self.assertRaisesRegex(ValueError, 'nombre del grupo no puede estar vacío'):
            editar_grupo(grupo_activo.id, '   ', [])

        with self.assertRaisesRegex(ValueError, 'superar los 100 caracteres'):
            editar_grupo(grupo_activo.id, 'A' * 101, [])

    def test_editar_grupo_rechaza_aprendices_de_otra_ficha_y_duplicados(self):
        instructor = Instructor(nombre='I', correo='c@c.com', password_hash='x')
        db.session.add(instructor)
        db.session.flush()
        ficha_a = Ficha(codigo='123', nombre_programa='A', instructor_id=instructor.id)
        ficha_b = Ficha(codigo='456', nombre_programa='B', instructor_id=instructor.id)
        db.session.add_all([ficha_a, ficha_b])
        db.session.flush()

        a_local = Aprendiz(ficha_id=ficha_a.id, documento='1', nombre='L', apellidos='B', estado='En formación')
        a_ajeno = Aprendiz(ficha_id=ficha_b.id, documento='2', nombre='X', apellidos='B', estado='En formación')
        db.session.add_all([a_local, a_ajeno])
        db.session.flush()

        grupo = Grupo(ficha_id=ficha_a.id, nombre='Grupo A', activo=True)
        db.session.add(grupo)
        db.session.commit()

        with self.assertRaisesRegex(ValueError, 'pertenecer a la ficha'):
            editar_grupo(grupo.id, 'G', [a_ajeno.id])

        with self.assertRaisesRegex(ValueError, 'solo puede asignarse una vez'):
            editar_grupo(grupo.id, 'G', [a_local.id, a_local.id])

        with self.assertRaisesRegex(ValueError, 'selección de aprendices no es válida'):
            editar_grupo(grupo.id, 'G', ['invalido'])

    def test_crear_grupo_manual_exitoso_y_validaciones(self):
        instructor = Instructor(nombre='I', correo='c@c.com', password_hash='x')
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo='123', nombre_programa='X', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.flush()

        a1 = Aprendiz(ficha_id=ficha.id, documento='1', nombre='A1', apellidos='B', estado='En formación')
        db.session.add(a1)
        db.session.commit()

        grupo = crear_grupo_manual(ficha.id, 'Equipo Manual', [a1.id])
        self.assertIsNotNone(grupo.id)
        self.assertEqual(grupo.nombre, 'Equipo Manual')
        self.assertEqual(len(grupo.aprendices), 1)

        # Crear grupo vacío
        grupo_vacio = crear_grupo_manual(ficha.id, 'Equipo Vacío')
        self.assertEqual(grupo_vacio.nombre, 'Equipo Vacío')
        self.assertEqual(len(grupo_vacio.aprendices), 0)

        with self.assertRaisesRegex(ValueError, 'nombre del grupo no puede estar vacío'):
            crear_grupo_manual(ficha.id, '  ')

        with self.assertRaisesRegex(ValueError, 'superar los 100 caracteres'):
            crear_grupo_manual(ficha.id, 'A' * 101)

        with self.assertRaisesRegex(ValueError, 'ficha especificada no existe'):
            crear_grupo_manual(9999, 'Nombre')

        # Editar sin pasar lista de aprendices (None por defecto)
        grupo_editado_sin_lista = editar_grupo(grupo.id, 'Nuevo Nombre')
        self.assertEqual(grupo_editado_sin_lista.nombre, 'Nuevo Nombre')
        self.assertEqual(len(grupo_editado_sin_lista.aprendices), 0)

