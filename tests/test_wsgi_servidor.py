"""Contrato de arranque del servidor de desarrollo definido en wsgi.py."""

import unittest

from wsgi import opciones_servidor


class OpcionesServidorTestCase(unittest.TestCase):
    def test_valores_por_defecto_quedan_en_loopback_ipv4(self):
        opciones = opciones_servidor({})
        self.assertEqual(opciones['host'], '127.0.0.1')
        self.assertEqual(opciones['port'], 8009)
        self.assertTrue(opciones['debug'])
        self.assertTrue(opciones['use_reloader'])
        self.assertEqual(opciones['reloader_type'], 'stat')
        self.assertEqual(opciones['reloader_interval'], 1)
        for patron in ('*venv*', '*__pycache__*', '*uploads*', '*logs*'):
            self.assertIn(patron, opciones['exclude_patterns'])

    def test_puerto_desde_entorno(self):
        self.assertEqual(opciones_servidor({'PORT': '8158'})['port'], 8158)

    def test_puerto_invalido_falla_con_mensaje(self):
        with self.assertRaisesRegex(ValueError, 'PORT'):
            opciones_servidor({'PORT': 'ocho'})

    def test_puerto_vacio_usa_el_predeterminado(self):
        self.assertEqual(opciones_servidor({'PORT': ''})['port'], 8009)

    def test_sin_debug_se_respeta_host_publico_y_sin_reloader(self):
        opciones = opciones_servidor({'FLASK_DEBUG': '0', 'HOST': '0.0.0.0'})
        self.assertEqual(opciones['host'], '0.0.0.0')
        self.assertFalse(opciones['debug'])
        self.assertFalse(opciones['use_reloader'])

    def test_con_debug_un_host_publico_se_fuerza_a_loopback(self):
        for host in ('::', '0.0.0.0', '192.168.1.20'):
            with self.subTest(host=host):
                opciones = opciones_servidor({'FLASK_DEBUG': '1', 'HOST': host})
                self.assertEqual(opciones['host'], '127.0.0.1')

    def test_con_debug_se_respetan_hosts_loopback(self):
        for host in ('127.0.0.1', '::1', 'localhost'):
            with self.subTest(host=host):
                self.assertEqual(opciones_servidor({'HOST': host})['host'], host)

    def test_host_vacio_usa_el_predeterminado(self):
        self.assertEqual(opciones_servidor({'HOST': '  '})['host'], '127.0.0.1')


if __name__ == '__main__':
    unittest.main()
