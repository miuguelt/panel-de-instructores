import os
import unittest
from unittest.mock import Mock, patch

import redis

from app.services.importacion_jobs import (
    ColaImportacionesNoDisponible,
    _cliente_redis,
    _redis_destino,
)


class ImportacionJobsTestCase(unittest.TestCase):
    def test_redis_destino_no_expone_credenciales(self):
        destino = _redis_destino(
            'redis://:super-secret@redis-ow89qqy682ly5bmj0s1yrs1j:6379/0'
        )
        self.assertEqual(
            destino,
            'redis://redis-ow89qqy682ly5bmj0s1yrs1j:6379/0',
        )
        self.assertNotIn('super-secret', destino)

    def test_cliente_redis_hace_ping_antes_de_entregarlo(self):
        fake = Mock()
        with patch.dict(
            os.environ,
            {'REDIS_URL': 'redis://:secret@redis-host:6379/0'},
            clear=False,
        ), patch('redis.Redis.from_url', return_value=fake):
            self.assertIs(_cliente_redis(), fake)
        fake.ping.assert_called_once_with()

    def test_cliente_redis_imprime_error_util_para_endpoint_invalido(self):
        fake = Mock()
        fake.ping.side_effect = redis.exceptions.ConnectionError('Connection refused')
        with patch.dict(
            os.environ,
            {'REDIS_URL': 'redis://:super-secret@postgres-db:5432/control2'},
            clear=False,
        ), patch('redis.Redis.from_url', return_value=fake):
            with self.assertRaisesRegex(
                ColaImportacionesNoDisponible,
                r'Redis no responde en redis://postgres-db:5432/control2: ConnectionError',
            ) as contexto:
                _cliente_redis()
        self.assertNotIn('super-secret', str(contexto.exception))


if __name__ == '__main__':
    unittest.main()
