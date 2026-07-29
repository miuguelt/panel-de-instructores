import os
import subprocess
import sys
import unittest


class ConfigEnvironmentTestCase(unittest.TestCase):
    def test_variables_opcionales_vacias_no_rompen_el_arranque(self):
        entorno = os.environ.copy()
        entorno.update({
            'LOG_LEVEL': '',
            'DB_POOL_SIZE': '',
            'DB_MAX_OVERFLOW': '',
            'MAX_CONTENT_LENGTH': '',
            'SMTP_PORT': '',
            'WTF_CSRF_TIME_LIMIT': '',
        })
        resultado = subprocess.run(
            [
                sys.executable,
                '-c',
                'import config; print(config.Config.SQLALCHEMY_ENGINE_OPTIONS["pool_size"]); '
                'print(config.Config.SMTP_PORT)',
            ],
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertTrue(resultado.stdout.rstrip().endswith('8\n587'))
        self.assertIn('LOG_LEVEL llegó vacío', resultado.stderr)


if __name__ == '__main__':
    unittest.main()
