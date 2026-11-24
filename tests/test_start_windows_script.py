"""Contrato estático de start-windows.ps1: solo detiene procesos propios."""

from pathlib import Path
import re
import unittest

SCRIPT = (Path(__file__).resolve().parents[1] / 'start-windows.ps1').read_text(encoding='utf-8')


class StartWindowsScriptTestCase(unittest.TestCase):
    def test_no_usa_taskkill(self):
        self.assertNotIn('taskkill', SCRIPT.lower())

    def test_no_queda_la_funcion_duplicada_sin_filtro_listen(self):
        self.assertNotIn('Get-PortPids', SCRIPT)

    def test_define_filtro_de_procesos_del_proyecto(self):
        self.assertIn('function Get-ProjectServerPids', SCRIPT)
        cuerpo = SCRIPT.split('function Get-ProjectServerPids', 1)[1]
        self.assertIn('Win32_Process', cuerpo)
        self.assertIn('wsgi.py', cuerpo)
        self.assertIn('$PSScriptRoot', cuerpo)

    def test_stop_process_solo_sobre_pids_verificados(self):
        lineas = [l for l in SCRIPT.splitlines() if 'Stop-Process' in l]
        self.assertTrue(lineas)
        for linea in lineas:
            self.assertRegex(linea, r'Stop-Process -Id \$projectPid\b')
        self.assertEqual(len(re.findall(r'foreach \(\$projectPid in \(Get-ProjectServerPids', SCRIPT)), 2)

    def test_netstat_incluye_ipv6(self):
        self.assertNotRegex(SCRIPT, r'netstat[^\n|]*-p\s+tcp\b')

    def test_fija_host_loopback(self):
        self.assertIn("$env:HOST = '127.0.0.1'", SCRIPT)


if __name__ == '__main__':
    unittest.main()
