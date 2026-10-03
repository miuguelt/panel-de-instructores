"""Pruebas unitarias para comandos CLI de wsgi.py."""

import unittest
from unittest.mock import patch

from wsgi import alertas_auto_evaluar, app


class WsgiCliTestCase(unittest.TestCase):
    def setUp(self):
        self.runner = app.test_cli_runner()

    def test_alertas_auto_evaluar_cli_sin_verbose(self):
        with patch('app.services.alertas.ejecutar_revision_automatica', return_value=3) as mock_rev, \
             patch('app.services.alertas.vencer_planes_pendientes', return_value=1) as mock_venc:
            resultado = self.runner.invoke(alertas_auto_evaluar)
            self.assertEqual(resultado.exit_code, 0)
            mock_rev.assert_called_once()
            mock_venc.assert_called_once()
            self.assertEqual(resultado.output.strip(), '')

    def test_alertas_auto_evaluar_cli_con_verbose(self):
        with patch('app.services.alertas.ejecutar_revision_automatica', return_value=5) as mock_rev, \
             patch('app.services.alertas.vencer_planes_pendientes', return_value=2) as mock_venc:
            resultado = self.runner.invoke(alertas_auto_evaluar, ['--verbose'])
            self.assertEqual(resultado.exit_code, 0)
            mock_rev.assert_called_once()
            mock_venc.assert_called_once()
            self.assertIn('Revision automatica completada: 5 ficha(s) evaluadas, 2 plan(es) vencidos.', resultado.output)


if __name__ == '__main__':
    unittest.main()
