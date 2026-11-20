"""Cada ruta del instructor que usan las plantillas y la navegación existe.

La modularización de ``app/routes/instructor`` dejó sin registrar 23 rutas
(tareas, juicios, estadísticas, alertas, materiales, observador y entregas),
y cualquier página de ficha respondía con error 500 al construir el menú.
"""

import re
import unittest
from pathlib import Path

from app import create_app


RAIZ = Path(__file__).resolve().parents[1]

ENDPOINTS_RESTAURADOS = {
    'alertas', 'anotar_observador_tarea', 'calificar_entrega', 'descargar_archivo_entrega',
    'descargar_evidencia_plan', 'editar_nota_observador', 'editar_tarea', 'eliminar_material',
    'eliminar_nota_observador', 'eliminar_tarea', 'estadisticas', 'evaluar_entregas_en_bloque',
    'evidencias_faltantes', 'gestionar_prorroga_tarea', 'guardar_config_alertas', 'juicios',
    'materiales', 'observador', 'programar_competencia', 'registrar_actividad_clase', 'tareas',
    'toggle_competencia_seleccionada', 'ver_entregas',
}


class RutasInstructorRegistradasTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
        })
        cls.endpoints = {regla.endpoint for regla in cls.app.url_map.iter_rules()}

    def test_las_rutas_restauradas_estan_registradas(self):
        faltantes = {f'instructor.{nombre}' for nombre in ENDPOINTS_RESTAURADOS} - self.endpoints
        self.assertEqual(faltantes, set())

    def test_todo_url_for_del_instructor_apunta_a_una_ruta_existente(self):
        patron = re.compile(r"url_for\(\s*['\"](instructor\.[a-z_]+)['\"]")
        usados = {}
        for archivo in [*RAIZ.glob('app/**/*.py'), *RAIZ.glob('app/templates/**/*.html')]:
            for endpoint in patron.findall(archivo.read_text(encoding='utf-8')):
                usados.setdefault(endpoint, archivo.relative_to(RAIZ).as_posix())
        rotos = {endpoint: archivo for endpoint, archivo in usados.items() if endpoint not in self.endpoints}
        self.assertEqual(rotos, {}, 'Estos url_for apuntan a rutas que no existen.')

    def test_los_modulos_de_rutas_restaurados_no_superan_400_lineas(self):
        modulos = ['actividades_evidencias', 'alertas_materiales', 'competencias', 'entregas',
                   'estadisticas', 'juicios', 'observador', 'tareas']
        largos = {}
        for nombre in modulos:
            ruta = RAIZ / 'app' / 'routes' / 'instructor' / f'{nombre}.py'
            lineas = len(ruta.read_text(encoding='utf-8').splitlines())
            if lineas > 400:
                largos[nombre] = lineas
        self.assertEqual(largos, {})


if __name__ == '__main__':
    unittest.main()
