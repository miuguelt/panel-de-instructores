"""Solo coordinación (o administración) entra a la gestión de equipos ejecutores."""

import unittest

from app import create_app, db
from app.models import Instructor


class CoordinacionRequeridaTest(unittest.TestCase):
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
        self.usuarios = {}
        for rol in ('instructor', 'coordinacion', 'admin'):
            usuario = Instructor(nombre=f'Usuario {rol}', correo=f'{rol}@practica.test', rol=rol)
            usuario.set_password('clave-de-prueba')
            db.session.add(usuario)
            self.usuarios[rol] = usuario
        db.session.commit()
        self.cliente = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _entrar(self, rol):
        with self.cliente.session_transaction() as estado:
            estado['_user_id'] = str(self.usuarios[rol].id)
            estado['_fresh'] = True
        return self.cliente.get('/programacion/equipos/')

    def test_sin_sesion_lleva_al_ingreso(self):
        respuesta = self.cliente.get('/programacion/equipos/')
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/login', respuesta.headers['Location'])
        self.assertIn('next=', respuesta.headers['Location'])

    def test_instructor_sin_rol_de_coordinacion_recibe_403(self):
        self.assertEqual(self._entrar('instructor').status_code, 403)

    def test_coordinacion_y_administracion_ven_los_equipos(self):
        for rol in ('coordinacion', 'admin'):
            with self.subTest(rol=rol):
                respuesta = self._entrar(rol)
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn('Usuario instructor', respuesta.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
