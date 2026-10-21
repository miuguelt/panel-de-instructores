"""Pruebas del validador de cobertura de funciones nuevas en Git."""

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.verificar_funciones_diff import (
    extraer_funciones_nuevas_diff,
    main,
    obtener_diff_git,
    verificar_cobertura_con_llamadas,
    verificar_pruebas_estaticas,
)


class VerificarFuncionesDiffTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_extraer_funciones_nuevas_ignora_tests_y_detecta_fuentes(self):
        diff_ejemplo = (
            "diff --git a/app/servicio.py b/app/servicio.py\n"
            "--- a/app/servicio.py\n"
            "+++ b/app/servicio.py\n"
            "@@ -10,0 +11,6 @@\n"
            "+def nueva_funcion(x, y):\n"
            "+    return x + y\n"
            "+\n"
            "+async def operacion_async():\n"
            "+    pass\n"
            "diff --git a/tests/test_servicio.py b/tests/test_servicio.py\n"
            "--- a/tests/test_servicio.py\n"
            "+++ b/tests/test_servicio.py\n"
            "@@ -20,0 +21,2 @@\n"
            "+def test_algo():\n"
            "+    assert True\n"
        )
        funciones = extraer_funciones_nuevas_diff(diff_ejemplo)
        self.assertEqual(len(funciones), 2)
        self.assertEqual(funciones[0]['nombre'], 'nueva_funcion')
        self.assertEqual(funciones[0]['archivo'], 'app/servicio.py')
        self.assertEqual(funciones[1]['nombre'], 'operacion_async')

    def test_verificar_cobertura_con_llamadas_detecta_aprobadas_y_faltantes(self):
        ruta_llamadas = self.raiz / 'calls.json'
        ruta_llamadas.write_text(
            json.dumps({
                'funciones': [
                    {
                        'archivo': 'app/servicio.py',
                        'nombre': 'probada',
                        'pruebas': ['test_uno', 'test_dos'],
                    }
                ]
            }),
            encoding='utf-8',
        )

        funciones = [
            {'archivo': 'app/servicio.py', 'nombre': 'probada', 'linea_declaracion': 'def probada():'},
            {'archivo': 'app/servicio.py', 'nombre': 'huerfana', 'linea_declaracion': 'def huerfana():'},
        ]

        resultado = verificar_cobertura_con_llamadas(funciones, str(ruta_llamadas))
        self.assertEqual(len(resultado['aprobadas']), 1)
        self.assertEqual(resultado['aprobadas'][0]['nombre'], 'probada')
        self.assertEqual(len(resultado['faltantes']), 1)
        self.assertEqual(resultado['faltantes'][0]['nombre'], 'huerfana')

    def test_verificar_pruebas_estaticas_encuentra_referencias_y_metodos_magicos(self):
        directorio_tests = self.raiz / 'tests'
        directorio_tests.mkdir()
        archivo_test = directorio_tests / 'test_demo.py'
        archivo_test.write_text(
            "from app.modelo import ClaseConMetodos\n"
            "def test_referencia():\n"
            "    resultado = funcion_normal()\n"
            "    assert resultado == 1\n",
            encoding='utf-8',
        )

        funciones = [
            {'archivo': 'app/servicio.py', 'nombre': 'funcion_normal', 'linea_declaracion': 'def funcion_normal():'},
            {'archivo': 'app/modelo.py', 'nombre': '__init__', 'linea_declaracion': 'def __init__(self):'},
            {'archivo': 'app/servicio.py', 'nombre': 'sin_prueba', 'linea_declaracion': 'def sin_prueba():'},
        ]

        resultado = verificar_pruebas_estaticas(funciones, raiz_proyecto=str(self.raiz))
        self.assertEqual(len(resultado['aprobadas']), 2)
        self.assertEqual(len(resultado['faltantes']), 1)
        self.assertEqual(resultado['faltantes'][0]['nombre'], 'sin_prueba')

    def test_obtener_diff_git_captura_salida_y_tolera_errores(self):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = 'diff simulado'
            salida = obtener_diff_git(en_stage=True)
            self.assertEqual(salida, 'diff simulado')

        with patch('subprocess.run', side_effect=OSError('Error simulado')):
            salida_error = obtener_diff_git(referencia='HEAD')
            self.assertEqual(salida_error, '')

    def test_main_sin_diff_y_sin_funciones_nuevas(self):
        with patch('scripts.verificar_funciones_diff.obtener_diff_git', return_value=''):
            salida = StringIO()
            with redirect_stdout(salida):
                codigo = main([])
            self.assertEqual(codigo, 0)
            self.assertIn('No se detectaron cambios', salida.getvalue())

        with patch('scripts.verificar_funciones_diff.obtener_diff_git', return_value='diff sin funciones'):
            salida = StringIO()
            with redirect_stdout(salida):
                codigo = main([])
            self.assertEqual(codigo, 0)
            self.assertIn('No se detectaron funciones nuevas', salida.getvalue())

    def test_main_con_faltantes_devuelve_uno_y_con_aprobadas_cero(self):
        diff_simulado = (
            "diff --git a/app/foo.py b/app/foo.py\n"
            "+++ b/app/foo.py\n"
            "+def nueva():\n"
            "+    pass\n"
        )
        with patch('scripts.verificar_funciones_diff.obtener_diff_git', return_value=diff_simulado):
            with patch('scripts.verificar_funciones_diff.verificar_pruebas_estaticas') as mock_verif:
                mock_verif.return_value = {
                    'aprobadas': [],
                    'faltantes': [{'archivo': 'app/foo.py', 'nombre': 'nueva', 'linea_declaracion': 'def nueva():'}],
                }
                salida = StringIO()
                with redirect_stdout(salida):
                    codigo_fallo = main(['--raiz', str(self.raiz)])
                self.assertEqual(codigo_fallo, 1)
                self.assertIn('REGLA 5.0 DE DEVBRAIN INCUMPLIDA', salida.getvalue())

                mock_verif.return_value = {
                    'aprobadas': [{'archivo': 'app/foo.py', 'nombre': 'nueva', 'linea_declaracion': 'def nueva():', 'pruebas': ['t']}],
                    'faltantes': [],
                }
                salida_ok = StringIO()
                with redirect_stdout(salida_ok):
                    codigo_exito = main(['--raiz', str(self.raiz)])
                self.assertEqual(codigo_exito, 0)
                self.assertIn('Todas las funciones nuevas cuentan con pruebas', salida_ok.getvalue())


if __name__ == '__main__':
    unittest.main()
