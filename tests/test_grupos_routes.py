import unittest
from app import create_app, db
from app.models.instructor import Instructor
from app.models.ficha import Ficha
from app.models.aprendiz import Aprendiz
from app.models.grupo import Grupo, GrupoAprendiz
from app.models.insignia import Insignia, InsigniaOtorgada

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

    def test_listar_grupos_y_podio_para_ficha_autorizada(self):
        instructor, ficha = self._crear_instructor_con_ficha('a@example.com', 'A')
        grupo = Grupo(ficha_id=ficha.id, nombre='Grupo 1', activo=True)
        insignia = Insignia(ficha_id=ficha.id, nombre='Buena', descripcion='x', icono='x')
        db.session.add_all([grupo, insignia])
        db.session.commit()
        self._iniciar_sesion(instructor)

        listado = self.client.get(f'/instructor/fichas/{ficha.id}/grupos')
        podio = self.client.get(f'/instructor/fichas/{ficha.id}/grupos/podio')

        self.assertEqual(listado.status_code, 200)
        self.assertIn(b'Grupo 1', listado.data)
        self.assertEqual(podio.status_code, 200)
        self.assertIn(b'Grupo 1', podio.data)

    def test_otorgar_insignia_route(self):
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

        response_repetida = self.client.post(f'/instructor/fichas/{ficha.id}/grupos/otorgar_insignia', data={
            'grupo_id': grupo.id,
            'insignia_id': insignia.id
        }, follow_redirects=True)
        self.assertEqual(response_repetida.status_code, 200)
        self.assertIn(b'ya fue otorgada', response_repetida.data)
        self.assertEqual(InsigniaOtorgada.query.count(), 1)

    def _crear_instructor_con_ficha(self, correo, codigo):
        instructor = Instructor(nombre=correo, correo=correo, password_hash='x')
        db.session.add(instructor)
        db.session.flush()
        ficha = Ficha(codigo=codigo, nombre_programa='Programa', instructor_id=instructor.id)
        db.session.add(ficha)
        db.session.flush()
        return instructor, ficha

    def _iniciar_sesion(self, instructor):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(instructor.id)
            sess['_fresh'] = True

    def test_instructor_no_puede_ver_grupos_de_otra_ficha(self):
        instructor_a, ficha_a = self._crear_instructor_con_ficha('a@example.com', 'A')
        _, ficha_b = self._crear_instructor_con_ficha('b@example.com', 'B')
        db.session.commit()
        self._iniciar_sesion(instructor_a)

        response = self.client.get(f'/instructor/fichas/{ficha_b.id}/grupos')

        self.assertEqual(response.status_code, 404)

    def test_generar_grupos_rechaza_aprendiz_de_otra_ficha_sin_archivar_actuales(self):
        instructor, ficha = self._crear_instructor_con_ficha('a@example.com', 'A')
        _, otra_ficha = self._crear_instructor_con_ficha('b@example.com', 'B')
        grupo_existente = Grupo(ficha_id=ficha.id, nombre='Actual', activo=True)
        aprendiz_ajeno = Aprendiz(
            ficha_id=otra_ficha.id, documento='extranjero', nombre='Ajeno',
            apellidos='B', estado='En formación'
        )
        db.session.add_all([grupo_existente, aprendiz_ajeno])
        db.session.commit()
        self._iniciar_sesion(instructor)

        response = self.client.post(
            f'/instructor/fichas/{ficha.id}/grupos/generar',
            data={'tamano_grupo': '2', 'aprendices_ids[]': [str(aprendiz_ajeno.id)]},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'pertenezcan a esta ficha', response.data)
        self.assertTrue(db.session.get(Grupo, grupo_existente.id).activo)
        self.assertEqual(Grupo.query.filter_by(ficha_id=ficha.id).count(), 1)
        self.assertEqual(GrupoAprendiz.query.count(), 0)

    def test_generar_grupos_datos_invalidos_conservan_grupos_actuales(self):
        instructor, ficha = self._crear_instructor_con_ficha('a@example.com', 'A')
        aprendiz = Aprendiz(
            ficha_id=ficha.id, documento='1', nombre='Local', apellidos='B',
            estado='En formación'
        )
        grupo_existente = Grupo(ficha_id=ficha.id, nombre='Actual', activo=True)
        db.session.add_all([aprendiz, grupo_existente])
        db.session.commit()
        self._iniciar_sesion(instructor)
        url = f'/instructor/fichas/{ficha.id}/grupos/generar'
        formularios_invalidos = [
            {'tamano_grupo': '2'},
            {'tamano_grupo': '1', 'aprendices_ids[]': str(aprendiz.id)},
            {'tamano_grupo': 'no-numero', 'aprendices_ids[]': str(aprendiz.id)},
            {'tamano_grupo': '2', 'aprendices_ids[]': 'no-numero'},
            {'tamano_grupo': '2', 'aprendices_ids[]': ['9999']},
            {'tamano_grupo': '2', 'aprendices_ids[]': [str(aprendiz.id), str(aprendiz.id)]},
        ]

        for formulario in formularios_invalidos:
            with self.subTest(formulario=formulario):
                response = self.client.post(url, data=formulario, follow_redirects=True)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(db.session.get(Grupo, grupo_existente.id).activo)
                self.assertEqual(Grupo.query.filter_by(ficha_id=ficha.id).count(), 1)
                self.assertEqual(GrupoAprendiz.query.count(), 0)

    def test_otorgar_insignia_rechaza_grupo_o_insignia_de_otra_ficha(self):
        instructor, ficha = self._crear_instructor_con_ficha('a@example.com', 'A')
        _, otra_ficha = self._crear_instructor_con_ficha('b@example.com', 'B')
        grupo_local = Grupo(ficha_id=ficha.id, nombre='Local')
        grupo_ajeno = Grupo(ficha_id=otra_ficha.id, nombre='Ajeno')
        insignia_local = Insignia(ficha_id=ficha.id, nombre='Local', descripcion='x', icono='x')
        insignia_ajena = Insignia(ficha_id=otra_ficha.id, nombre='Ajena', descripcion='x', icono='x')
        db.session.add_all([grupo_local, grupo_ajeno, insignia_local, insignia_ajena])
        db.session.commit()
        self._iniciar_sesion(instructor)
        url = f'/instructor/fichas/{ficha.id}/grupos/otorgar_insignia'

        grupo_ajeno_response = self.client.post(url, data={
            'grupo_id': str(grupo_ajeno.id), 'insignia_id': str(insignia_local.id),
        }, follow_redirects=True)
        insignia_ajena_response = self.client.post(url, data={
            'grupo_id': str(grupo_local.id), 'insignia_id': str(insignia_ajena.id),
        }, follow_redirects=True)

        self.assertEqual(grupo_ajeno_response.status_code, 200)
        self.assertEqual(insignia_ajena_response.status_code, 200)
        self.assertEqual(InsigniaOtorgada.query.count(), 0)

    def test_ruta_podio_de_otra_ficha_no_es_accesible(self):
        instructor_a, _ = self._crear_instructor_con_ficha('a@example.com', 'A')
        _, ficha_b = self._crear_instructor_con_ficha('b@example.com', 'B')
        db.session.commit()
        self._iniciar_sesion(instructor_a)

        response = self.client.get(f'/instructor/fichas/{ficha_b.id}/grupos/podio')

        self.assertEqual(response.status_code, 404)

    def test_otorgar_insignia_rechaza_ids_que_no_sean_enteros(self):
        instructor, ficha = self._crear_instructor_con_ficha('a@example.com', 'A')
        db.session.commit()
        self._iniciar_sesion(instructor)

        response = self.client.post(
            f'/instructor/fichas/{ficha.id}/grupos/otorgar_insignia',
            data={'grupo_id': 'invalid', 'insignia_id': '1'},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'seleccionados', response.data)
        self.assertEqual(InsigniaOtorgada.query.count(), 0)

        response_sin_datos = self.client.post(
            f'/instructor/fichas/{ficha.id}/grupos/otorgar_insignia',
            data={},
            follow_redirects=True,
        )
        self.assertEqual(response_sin_datos.status_code, 200)
        self.assertIn(b'Faltan datos', response_sin_datos.data)
