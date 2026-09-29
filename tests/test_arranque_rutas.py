import tempfile
import unittest

from app import create_app


class RegistroRutasArranqueTestCase(unittest.TestCase):
    def test_arranque_no_oculta_rutas_fallidas_en_modo_degradado(self):
        with tempfile.TemporaryDirectory() as carpeta_subidas:
            app = create_app({
                'TESTING': True,
                'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                'SQLALCHEMY_ENGINE_OPTIONS': {},
                'UPLOAD_FOLDER': carpeta_subidas,
                'WTF_CSRF_ENABLED': False,
                'RATELIMIT_ENABLED': False,
            })

        self.assertEqual(app.config['STARTUP_ERRORS'], [])
        self.assertIn('atencion.fila_atencion', app.view_functions)
        self.assertIn('instructor.vision_general', app.view_functions)
        self.assertIn('aprendiz.pedir_turno', app.view_functions)
        self.assertIn('aprendiz.cancelar_turno', app.view_functions)


if __name__ == '__main__':
    unittest.main()
