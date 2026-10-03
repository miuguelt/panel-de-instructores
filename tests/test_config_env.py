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
        self.assertTrue(resultado.stdout.rstrip().endswith('4\n587'))
        self.assertIn('LOG_LEVEL llegó vacío', resultado.stderr)

    def test_normalizar_db_url_soporta_postgres_y_psycopg3(self):
        import config
        self.assertEqual(
            config._normalize_db_url('postgres://user:pass@127.0.0.1:5432/dbname'),
            'postgresql+psycopg2://user:pass@127.0.0.1:5432/dbname',
        )
        self.assertEqual(
            config._normalize_db_url('postgresql+psycopg://user:pass@127.0.0.1:5432/dbname'),
            'postgresql+psycopg2://user:pass@127.0.0.1:5432/dbname',
        )
        self.assertEqual(
            config._normalize_db_url('sqlite:///:memory:'),
            'sqlite:///:memory:',
        )
        self.assertEqual(
            config._normalize_db_url('postgresql+psycopg2://user:pass@127.0.0.1:5432/dbname'),
            'postgresql+psycopg2://user:pass@127.0.0.1:5432/dbname',
        )
        self.assertEqual(config._normalize_db_url(''), '')

    def test_env_int_tolerancia_y_limites(self):
        import config
        # Valor ausente
        self.assertEqual(config._env_int('VARIABLE_INEXISTENTE_XYZ', 42), 42)
        # Valor vacío
        os.environ['TEST_ENV_INT_VAL'] = '   '
        self.assertEqual(config._env_int('TEST_ENV_INT_VAL', 10), 10)
        # Valor inválido
        os.environ['TEST_ENV_INT_VAL'] = 'no_es_entero'
        self.assertEqual(config._env_int('TEST_ENV_INT_VAL', 15), 15)
        # Por debajo del mínimo
        os.environ['TEST_ENV_INT_VAL'] = '-5'
        self.assertEqual(config._env_int('TEST_ENV_INT_VAL', 20, minimum=0), 20)
        # Por encima del máximo
        os.environ['TEST_ENV_INT_VAL'] = '1000'
        self.assertEqual(config._env_int('TEST_ENV_INT_VAL', 50, maximum=100), 50)
        # Valor válido
        os.environ['TEST_ENV_INT_VAL'] = '25'
        self.assertEqual(config._env_int('TEST_ENV_INT_VAL', 0, minimum=1, maximum=50), 25)
        os.environ.pop('TEST_ENV_INT_VAL', None)

    def test_secret_key_efimera_en_produccion_con_insegura(self):
        entorno = os.environ.copy()
        entorno.update({
            'FLASK_ENV': 'production',
            'SECRET_KEY': 'dev-key-change-me',
        })
        resultado = subprocess.run(
            [
                sys.executable,
                '-c',
                'import config; print(config.SECRET_KEY_IS_EPHEMERAL); print(len(config.Config.SECRET_KEY))',
            ],
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn('True\n128', resultado.stdout)
        self.assertIn('SECRET_KEY insegura o vacia', resultado.stderr)


if __name__ == '__main__':
    unittest.main()
