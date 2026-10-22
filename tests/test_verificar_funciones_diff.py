"""Pruebas del validador de cobertura de funciones nuevas en Git."""

import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.verificar_funciones_diff import (
    _resumen_pytest,
    cargar_llamadas,
    ejecutar_pruebas_relacionadas,
    extraer_funciones_nuevas_diff,
    funciones_sin_evidencia,
    fusionar_llamadas,
    main,
    motivos_evidencia_desactualizada,
    obtener_diff_git,
    refrescar_evidencia,
    refrescar_evidencia_completa,
    ruta_evidencia_por_defecto,
    seleccionar_pruebas,
    verificar_cobertura_con_llamadas,
    verificar_pruebas_estaticas,
)

DIFF_NUEVA = (
    "diff --git a/app/foo.py b/app/foo.py\n"
    "+++ b/app/foo.py\n"
    "+def nueva():\n"
    "+    pass\n"
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


class RefrescoEvidenciaTestCase(unittest.TestCase):
    """La caché de ejecución se refresca sola en vez de bloquear con datos viejos."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temp_dir.name)
        (self.raiz / 'app').mkdir()
        (self.raiz / 'app' / 'foo.py').write_text('def nueva():\n    return 1\n', encoding='utf-8')
        (self.raiz / 'tests').mkdir()
        (self.raiz / 'tests' / 'test_foo.py').write_text(
            'def test_nueva():\n    assert True\n', encoding='utf-8'
        )
        self.evidencia = self.raiz / 'test-results' / 'function-calls.json'
        self.funciones = [
            {'archivo': 'app/foo.py', 'nombre': 'nueva', 'linea_declaracion': 'def nueva():'},
        ]

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _registro_fresco(destino, pruebas=('tests/test_foo.py::test_nueva',)):
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps({'funciones': [{
                'archivo': 'app/foo.py', 'nombre': 'nueva',
                'linea_inicio': 1, 'pruebas': list(pruebas),
            }]}),
            encoding='utf-8',
        )

    def _ejecutar_falso(self, codigo=0, salida=''):
        def falso(archivos, destino, raiz, tiempo_limite):
            if codigo == 0:
                self._registro_fresco(destino)
            return {'codigo': codigo, 'salida': salida, 'segundos': 0.1,
                    'error': None, 'archivos': archivos}
        return falso

    def test_seleccionar_pruebas_elige_por_modulo_importacion_y_nombre(self):
        (self.raiz / 'tests' / 'test_aseo_extra.py').write_text(
            'def test_x():\n    assert True\n', encoding='utf-8'
        )
        (self.raiz / 'tests' / 'test_importa.py').write_text(
            'from app.services.aseo import cargas_pendientes\n', encoding='utf-8'
        )
        (self.raiz / 'tests' / 'test_ajeno.py').write_text(
            'def test_y():\n    assert True\n', encoding='utf-8'
        )
        funciones = [{'archivo': 'app/services/aseo.py', 'nombre': '_cargas_totales',
                      'linea_declaracion': 'def _cargas_totales('}]

        elegidos = seleccionar_pruebas(funciones, self.raiz)

        self.assertIn('tests/test_aseo_extra.py', elegidos)
        self.assertNotIn('tests/test_ajeno.py', elegidos)
        self.assertNotIn('tests/test_importa.py', elegidos, 'la primera pasada no arrastra suites ajenas')

        ampliados = seleccionar_pruebas(funciones, self.raiz, ampliar=True)
        self.assertIn('tests/test_importa.py', ampliados)

        (self.raiz / 'tests' / 'test_referencia.py').write_text(
            'def test_z():\n    valor = cargas_pendientes\n', encoding='utf-8'
        )
        elegidos_por_nombre = seleccionar_pruebas(
            [{'archivo': 'app/otro.py', 'nombre': 'cargas_pendientes',
              'linea_declaracion': 'def cargas_pendientes('}],
            self.raiz,
        )
        self.assertIn('tests/test_referencia.py', elegidos_por_nombre)

    def test_seleccionar_pruebas_sin_candidatas_devuelve_vacio(self):
        self.assertEqual(seleccionar_pruebas([], self.raiz), [])
        self.assertEqual(
            seleccionar_pruebas([{'archivo': 'worker.py', 'nombre': 'inexistente',
                                  'linea_declaracion': 'def inexistente():'}], self.raiz),
            [],
        )

    def test_motivos_evidencia_desactualizada_detecta_ausencia_y_antiguedad(self):
        self.assertEqual(
            motivos_evidencia_desactualizada(self.funciones, self.evidencia, self.raiz),
            ['no hay registro de ejecución de pruebas'],
        )

        self.evidencia.parent.mkdir(parents=True)
        self.evidencia.write_text(
            json.dumps({'funciones': [{'archivo': 'app/foo.py', 'nombre': 'otra', 'pruebas': ['t']}]}),
            encoding='utf-8',
        )
        self.assertIn(
            'sin invocación registrada',
            motivos_evidencia_desactualizada(self.funciones, self.evidencia, self.raiz)[0],
        )

        self._registro_fresco(self.evidencia)
        self.assertEqual(motivos_evidencia_desactualizada(self.funciones, self.evidencia, self.raiz), [])

        atrasado = (self.raiz / 'app' / 'foo.py').stat().st_mtime - 120
        os.utime(self.evidencia, (atrasado, atrasado))
        self.assertIn(
            'anterior al último cambio',
            motivos_evidencia_desactualizada(self.funciones, self.evidencia, self.raiz)[0],
        )

    def test_cargar_llamadas_tolera_archivo_ausente_o_corrupto(self):
        self.assertEqual(cargar_llamadas(self.raiz / 'nada.json'), {'funciones': []})
        roto = self.raiz / 'roto.json'
        roto.write_text('{no es json', encoding='utf-8')
        self.assertEqual(cargar_llamadas(roto), {'funciones': []})

    def test_fusionar_llamadas_acumula_pruebas_y_actualiza_la_linea(self):
        previas = {'funciones': [
            {'archivo': 'app/a.py', 'nombre': 'f', 'linea_inicio': 10, 'pruebas': ['t1']},
            {'archivo': 'app/a.py', 'nombre': 'fuera', 'linea_inicio': 5, 'pruebas': ['t9']},
        ]}
        nuevas = {'pruebas_aprobadas': 2, 'funciones': [
            {'archivo': 'app/a.py', 'nombre': 'f', 'linea_inicio': 12, 'pruebas': ['t2']},
            {'archivo': 'app/a.py', 'nombre': 'g', 'linea_inicio': 20, 'pruebas': ['t3']},
        ]}

        fusion = fusionar_llamadas(previas, nuevas)
        por_nombre = {entrada['nombre']: entrada for entrada in fusion['funciones']}

        self.assertEqual(por_nombre['f']['pruebas'], ['t1', 't2'])
        self.assertEqual(por_nombre['f']['linea_inicio'], 12)
        self.assertEqual(por_nombre['g']['pruebas'], ['t3'])
        self.assertEqual(por_nombre['fuera']['pruebas'], ['t9'])
        self.assertEqual(fusion['pruebas_aprobadas'], 2)

    def test_ruta_evidencia_por_defecto_prefiere_el_registro_existente(self):
        self.assertEqual(
            ruta_evidencia_por_defecto(self.raiz),
            self.raiz / 'test-results' / 'function-calls.json',
        )
        alternativa = self.raiz / 'test-results' / 'calls.json'
        alternativa.parent.mkdir(parents=True)
        alternativa.write_text('{}', encoding='utf-8')
        self.assertEqual(ruta_evidencia_por_defecto(self.raiz), alternativa)

    def test_resumen_pytest_recorta_a_las_ultimas_lineas_utiles(self):
        self.assertEqual(_resumen_pytest(''), '')
        self.assertEqual(_resumen_pytest('a\n\n  \nb\n'), 'a\nb')
        self.assertEqual(len(_resumen_pytest('\n'.join(str(i) for i in range(40))).splitlines()), 12)

    def test_ejecutar_pruebas_relacionadas_invoca_pytest_con_el_registro(self):
        destino = self.raiz / 'test-results' / 'fresco.json'
        with patch('scripts.verificar_funciones_diff.subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = 'ok'
            mock_run.return_value.stderr = ''
            resultado = ejecutar_pruebas_relacionadas(['tests/test_foo.py'], destino, self.raiz, 60)

        comando = mock_run.call_args[0][0]
        self.assertIn('tests/test_foo.py', comando)
        self.assertIn(f'--function-calls-json={destino}', comando)
        self.assertEqual(mock_run.call_args[1]['cwd'], str(self.raiz))
        self.assertEqual(resultado['codigo'], 0)
        self.assertTrue(destino.parent.exists())

    def test_ejecutar_pruebas_relacionadas_reporta_tiempo_agotado(self):
        destino = self.raiz / 'test-results' / 'fresco.json'
        with patch(
            'scripts.verificar_funciones_diff.subprocess.run',
            side_effect=subprocess.TimeoutExpired(cmd='pytest', timeout=1),
        ):
            resultado = ejecutar_pruebas_relacionadas(['tests/test_foo.py'], destino, self.raiz, 1)

        self.assertIsNone(resultado['codigo'])
        self.assertIn('tiempo agotado', resultado['error'])

    def test_refrescar_evidencia_fusiona_y_limpia_el_temporal(self):
        with patch(
            'scripts.verificar_funciones_diff.ejecutar_pruebas_relacionadas',
            side_effect=self._ejecutar_falso(),
        ):
            resultado = refrescar_evidencia(self.funciones, self.raiz, self.evidencia)

        self.assertEqual(resultado['estado'], 'actualizada')
        guardado = json.loads(self.evidencia.read_text(encoding='utf-8'))
        self.assertEqual(guardado['funciones'][0]['nombre'], 'nueva')
        self.assertFalse((self.evidencia.parent / '.function-calls-fresco.json').exists())

    def test_refrescar_evidencia_sin_pruebas_relacionadas_no_ejecuta(self):
        with patch('scripts.verificar_funciones_diff.ejecutar_pruebas_relacionadas') as mock_run:
            resultado = refrescar_evidencia([], self.raiz, self.evidencia)
        self.assertEqual(resultado['estado'], 'sin_pruebas')
        mock_run.assert_not_called()

    def test_refrescar_evidencia_reporta_pruebas_fallidas_y_sin_recoleccion(self):
        with patch(
            'scripts.verificar_funciones_diff.ejecutar_pruebas_relacionadas',
            side_effect=self._ejecutar_falso(codigo=1, salida='FAILED test_nueva'),
        ):
            fallidas = refrescar_evidencia(self.funciones, self.raiz, self.evidencia)
        self.assertEqual(fallidas['estado'], 'pruebas_fallidas')

        with patch(
            'scripts.verificar_funciones_diff.ejecutar_pruebas_relacionadas',
            side_effect=self._ejecutar_falso(codigo=5),
        ):
            vacia = refrescar_evidencia(self.funciones, self.raiz, self.evidencia)
        self.assertEqual(vacia['estado'], 'sin_pruebas')

    def test_funciones_sin_evidencia_ignora_registros_sin_pruebas(self):
        self.evidencia.parent.mkdir(parents=True)
        self.evidencia.write_text(json.dumps({'funciones': [
            {'archivo': 'app/foo.py', 'nombre': 'nueva', 'linea_inicio': 1, 'pruebas': []},
        ]}), encoding='utf-8')

        self.assertEqual(
            [item['nombre'] for item in funciones_sin_evidencia(self.funciones, self.evidencia)],
            ['nueva'],
        )
        self._registro_fresco(self.evidencia)
        self.assertEqual(funciones_sin_evidencia(self.funciones, self.evidencia), [])

    def test_seleccionar_pruebas_respeta_los_archivos_ya_ejecutados(self):
        elegidos = seleccionar_pruebas(self.funciones, self.raiz, excluir=('tests/test_foo.py',))
        self.assertNotIn('tests/test_foo.py', elegidos)

    def test_refrescar_evidencia_completa_amplia_solo_si_falta_una_funcion(self):
        segunda = {'archivo': 'app/foo.py', 'nombre': 'otra', 'linea_declaracion': 'def otra():'}
        llamadas = []

        def falso(funciones, raiz, ruta, tiempo_limite, ampliar=False, excluir=()):
            llamadas.append({'nombres': [f['nombre'] for f in funciones],
                             'ampliar': ampliar, 'excluir': tuple(excluir)})
            entradas = [
                {'archivo': f['archivo'], 'nombre': f['nombre'], 'linea_inicio': 1,
                 'pruebas': ['tests/test_foo.py::t']}
                for f in funciones if ampliar or f['nombre'] == 'nueva'
            ]
            ruta = Path(ruta)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(
                json.dumps(fusionar_llamadas(cargar_llamadas(ruta), {'funciones': entradas})),
                encoding='utf-8',
            )
            return {'estado': 'actualizada', 'archivos': ['tests/test_foo.py'],
                    'segundos': 0.1, 'salida': '', 'error': None}

        with patch('scripts.verificar_funciones_diff.refrescar_evidencia', side_effect=falso):
            pasos = refrescar_evidencia_completa(self.funciones + [segunda], self.raiz, self.evidencia)

        self.assertEqual(len(pasos), 2)
        self.assertFalse(llamadas[0]['ampliar'])
        self.assertTrue(llamadas[1]['ampliar'])
        self.assertEqual(llamadas[1]['nombres'], ['otra'])
        self.assertEqual(llamadas[1]['excluir'], ('tests/test_foo.py',))

    def test_refrescar_evidencia_completa_se_detiene_si_la_primera_paso_cubre(self):
        def falso(funciones, raiz, ruta, tiempo_limite, ampliar=False, excluir=()):
            ruta = Path(ruta)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(json.dumps({'funciones': [
                {'archivo': f['archivo'], 'nombre': f['nombre'], 'linea_inicio': 1, 'pruebas': ['t']}
                for f in funciones
            ]}), encoding='utf-8')
            return {'estado': 'actualizada', 'archivos': ['tests/test_foo.py'],
                    'segundos': 0.1, 'salida': '', 'error': None}

        with patch('scripts.verificar_funciones_diff.refrescar_evidencia',
                   side_effect=falso) as mock_refresco:
            pasos = refrescar_evidencia_completa(self.funciones, self.raiz, self.evidencia)

        self.assertEqual(len(pasos), 1)
        self.assertEqual(mock_refresco.call_count, 1)

    def test_main_refresca_la_evidencia_y_certifica_sin_usar_el_estatico(self):
        with patch('scripts.verificar_funciones_diff.obtener_diff_git', return_value=DIFF_NUEVA), \
             patch('scripts.verificar_funciones_diff.ejecutar_pruebas_relacionadas',
                   side_effect=self._ejecutar_falso()), \
             patch('scripts.verificar_funciones_diff.verificar_pruebas_estaticas',
                   side_effect=AssertionError('no debía usarse el respaldo estático')):
            salida = StringIO()
            with redirect_stdout(salida):
                codigo = main(['--raiz', str(self.raiz)])

        self.assertEqual(codigo, 0)
        self.assertIn('Registro actualizado', salida.getvalue())
        self.assertIn('Todas las funciones nuevas cuentan con pruebas', salida.getvalue())
        self.assertTrue(self.evidencia.exists())

    def test_main_bloquea_cuando_las_pruebas_relacionadas_fallan(self):
        with patch('scripts.verificar_funciones_diff.obtener_diff_git', return_value=DIFF_NUEVA), \
             patch('scripts.verificar_funciones_diff.ejecutar_pruebas_relacionadas',
                   side_effect=self._ejecutar_falso(codigo=1, salida='FAILED tests/test_foo.py::test_nueva')):
            salida = StringIO()
            with redirect_stdout(salida):
                codigo = main(['--raiz', str(self.raiz)])

        self.assertEqual(codigo, 1)
        self.assertIn('Las pruebas relacionadas fallaron', salida.getvalue())
        self.assertIn('FAILED tests/test_foo.py::test_nueva', salida.getvalue())

    def test_main_degrada_a_referencias_estaticas_si_pytest_no_arranca(self):
        aprobadas = {
            'aprobadas': [{'archivo': 'app/foo.py', 'nombre': 'nueva',
                           'linea_declaracion': 'def nueva():', 'pruebas': ['tests/test_foo.py']}],
            'faltantes': [],
        }
        with patch('scripts.verificar_funciones_diff.obtener_diff_git', return_value=DIFF_NUEVA), \
             patch('scripts.verificar_funciones_diff.ejecutar_pruebas_relacionadas',
                   return_value={'codigo': None, 'salida': '', 'segundos': 1.0,
                                 'error': 'tiempo agotado tras 1s'}), \
             patch('scripts.verificar_funciones_diff.verificar_pruebas_estaticas',
                   return_value=aprobadas):
            salida = StringIO()
            with redirect_stdout(salida):
                codigo = main(['--raiz', str(self.raiz)])

        self.assertEqual(codigo, 0)
        self.assertIn('No se pudo ejecutar pytest', salida.getvalue())
        self.assertIn('referencias en archivos de prueba', salida.getvalue())

    def test_main_sin_auto_juzga_con_el_registro_tal_cual(self):
        self.evidencia.parent.mkdir(parents=True)
        self.evidencia.write_text(json.dumps({'funciones': []}), encoding='utf-8')

        with patch('scripts.verificar_funciones_diff.obtener_diff_git', return_value=DIFF_NUEVA), \
             patch('scripts.verificar_funciones_diff.ejecutar_pruebas_relacionadas',
                   side_effect=AssertionError('--sin-auto no debe refrescar')):
            salida = StringIO()
            with redirect_stdout(salida):
                codigo = main(['--raiz', str(self.raiz), '--sin-auto'])

        self.assertEqual(codigo, 1)
        self.assertIn('REGLA 5.0 DE DEVBRAIN INCUMPLIDA', salida.getvalue())


if __name__ == '__main__':
    unittest.main()
