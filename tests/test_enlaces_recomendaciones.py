"""Las recomendaciones llevan a lugares que existen y no anuncian datos que no hay.

- Cada `accion_url` del instructor corresponde a una ruta registrada (antes
  tres apuntaban a /vision-general, que respondía 404).
- Cada ancla del panel del aprendiz (#...) existe como id en sus plantillas.
- «Formación sincronizada» solo se anuncia si hay fase esperada y fase real
  con RAPs; sin datos no se afirma que la ficha va al día.
"""

import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from app import create_app
from app.services.recomendaciones import _evaluar_ritmo_fases_instructor

APP = Path(__file__).resolve().parents[1] / 'app'
FUENTE = (APP / 'services' / 'recomendaciones.py').read_text(encoding='utf-8')


def ids_del_panel_aprendiz():
    ids = set()
    for ruta in (APP / 'templates' / 'aprendiz').rglob('*.html'):
        ids.update(re.findall(r'id="([\w-]+)', ruta.read_text(encoding='utf-8')))
    return ids


class EnlacesRecomendacionesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False})

    def test_las_rutas_del_instructor_existen(self):
        adaptador = self.app.url_map.bind('localhost')
        rutas = re.findall(r"accion_url=f'(/instructor/[^']+)'", FUENTE)
        self.assertGreater(len(rutas), 5)
        for ruta in rutas:
            concreta = re.sub(r'\{[^}]+\}', '1', ruta)
            with self.subTest(ruta=ruta):
                endpoint, _ = adaptador.match(concreta, method='GET')
                self.assertTrue(endpoint)

    def test_las_anclas_del_aprendiz_existen(self):
        ids = ids_del_panel_aprendiz()
        anclas = re.findall(r"accion_url=f?'#([\w-]+?)(?:\{[^}]+\})?'", FUENTE)
        self.assertGreater(len(anclas), 5)
        for ancla in anclas:
            with self.subTest(ancla=ancla):
                # Las anclas con id variable (#experiencia-tarea-{id}) se comparan por su prefijo.
                self.assertTrue(ancla in ids or any(i.startswith(ancla) for i in ids), ancla)


class SincronizadaSinDatosTest(unittest.TestCase):
    ficha = SimpleNamespace(id=1)

    def fases(self, fase_real):
        return {'disponible': True, 'desfase_fases': 0, 'resumen_raps': {},
                'fase_esperada': {'nombre': 'EJECUCIÓN', 'orden': 3}, 'fase_real': fase_real}

    def titulos(self, fases_data):
        return [r.titulo for r in _evaluar_ritmo_fases_instructor(self.ficha, fases_data, {'configurado': True})]

    def test_sin_raps_no_se_anuncia_al_dia(self):
        for fase_real in ({'nombre': 'Sin definir'}, {'nombre': 'EJECUCIÓN', 'resultados_total': 0}, {}):
            with self.subTest(fase_real=fase_real):
                self.assertFalse(any('sincronizada' in t for t in self.titulos(self.fases(fase_real))))

    def test_con_datos_reales_si_se_anuncia(self):
        fases = self.fases({'nombre': 'EJECUCIÓN', 'resultados_total': 12, 'resultados_aprobados': 9})
        self.assertIn('Formación sincronizada en fase de Ejecución', self.titulos(fases))

    def test_sin_fechas_tampoco(self):
        fases = self.fases({'nombre': 'EJECUCIÓN', 'resultados_total': 12})
        fases['fase_esperada'] = {'nombre': 'Fechas pendientes'}
        self.assertFalse(any('sincronizada' in t for t in self.titulos(fases)))


if __name__ == '__main__':
    unittest.main()
