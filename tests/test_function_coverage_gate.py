import tempfile
import unittest
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.check_function_coverage import (
    iterar_funciones,
    lineas_cubiertas,
    main,
    revisar_cobertura_funciones,
)
from tests.conftest import RegistroFunciones


class FunctionCoverageGateTestCase(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temporal.name)
        (self.raiz / 'app').mkdir()
        self.modulo = self.raiz / 'app' / 'modulo.py'
        self.modulo.write_text(
            'def cubierta():\n'
            '    return 1\n'
            '\n'
            'def pendiente():\n'
            '    return 2\n'
            '\n'
            'class Servicio:\n'
            '    def ejecutar(self):\n'
            '        return 3\n'
            '\n'
            'def con_estado_global():\n'
            '    global cache\n'
            '    return cache\n',
            encoding='utf-8',
        )
        self.reporte = self.raiz / 'coverage.xml'
        self.reporte.write_text(
            '<?xml version="1.0" ?>'
            '<coverage><packages><package><classes>'
            '<class filename="app/modulo.py"><lines>'
            '<line number="2" hits="1"/><line number="5" hits="0"/>'
            '<line number="9" hits="0"/><line number="12" hits="0"/>'
            '<line number="13" hits="0"/>'
            '</lines></class></classes></package></packages></coverage>',
            encoding='utf-8',
        )

    def tearDown(self):
        self.temporal.cleanup()

    def test_iterar_funciones_incluye_funciones_y_metodos_con_linea_de_cuerpo(self):
        funciones = iterar_funciones(self.raiz / 'app')

        self.assertEqual(
            [(funcion['nombre'], funcion['linea_cuerpo']) for funcion in funciones],
            [('cubierta', 2), ('pendiente', 5), ('ejecutar', 9), ('con_estado_global', 13)],
        )

    def test_lineas_cubiertas_lee_rutas_y_lineas_del_xml(self):
        lineas = lineas_cubiertas(self.reporte)

        self.assertEqual(lineas['app/modulo.py'], {2})

    def test_revisar_cobertura_detecta_toda_funcion_sin_ejecucion(self):
        total, pendientes = revisar_cobertura_funciones(
            self.raiz / 'app', self.reporte
        )

        self.assertEqual(total, 4)
        self.assertEqual(
            [(funcion['nombre'], funcion['linea']) for funcion in pendientes],
            [('pendiente', 4), ('ejecutar', 8), ('con_estado_global', 11)],
        )

    def test_main_aprueba_cobertura_completa_y_rechaza_funciones_sin_prueba(self):
        xml_completo = self.raiz / 'completo.xml'
        xml_completo.write_text(
            self.reporte.read_text(encoding='utf-8').replace(
                'number="5" hits="0"', 'number="5" hits="1"'
            ).replace('number="9" hits="0"', 'number="9" hits="1"')
            .replace('number="13" hits="0"', 'number="13" hits="1"'),
            encoding='utf-8',
        )
        salida = StringIO()
        with redirect_stdout(salida):
            resultado_completo = main([
                '--source', str(self.raiz / 'app'),
                '--coverage-xml', str(xml_completo),
            ])
        self.assertEqual(resultado_completo, 0)
        self.assertIn('100%', salida.getvalue())

        salida = StringIO()
        with redirect_stdout(salida):
            resultado_incompleto = main([
                '--source', str(self.raiz / 'app'),
                '--coverage-xml', str(self.reporte),
            ])
        self.assertEqual(resultado_incompleto, 1)
        self.assertIn('pendiente', salida.getvalue())

    def test_lambda_creada_no_cuenta_como_ejecutada(self):
        self.modulo.write_text('def fabrica():\n    return lambda valor: valor + 1\n', encoding='utf-8')
        self.reporte.write_text('<coverage><class filename="app/modulo.py"><lines>'
            '<line number="2" hits="1"/></lines></class></coverage>', encoding='utf-8')
        registro = RegistroFunciones(self.raiz)
        espacio = {}
        exec(compile(self.modulo.read_text(encoding='utf-8'), str(self.modulo), 'exec'), espacio)
        anterior = sys.getprofile()
        try:
            sys.setprofile(registro.perfilar)
            callback = espacio['fabrica']()
        finally:
            sys.setprofile(anterior)
        self.assertTrue(callable(callback))
        registro.confirmar('prueba_fabrica')
        reporte = self.raiz / 'llamadas.json'
        registro.guardar(reporte)
        total, pendientes = revisar_cobertura_funciones(self.raiz / 'app', self.reporte, llamadas_json=reporte)
        self.assertEqual(total, 2)
        self.assertEqual([funcion['nombre'] for funcion in pendientes], ['<lambda>'])
        try:
            sys.setprofile(registro.perfilar)
            valor = callback(5)
        finally:
            sys.setprofile(anterior)
        self.assertEqual(valor, 6)
        registro.confirmar('prueba_callback')
        registro.guardar(reporte)
        self.assertEqual(revisar_cobertura_funciones(self.raiz / 'app', self.reporte, llamadas_json=reporte), (2, []))

def test_workflow_deploy_registra_y_verifica_las_invocaciones_reales():
    ruta = Path(__file__).resolve().parents[1] / '.github/workflows/deploy.yml'
    workflow = ruta.read_text(encoding='utf-8')

    assert '--function-calls-json=test-results/function-calls.json' in workflow
    assert '--calls-json test-results/function-calls.json' in workflow


if __name__ == '__main__':
    unittest.main()
