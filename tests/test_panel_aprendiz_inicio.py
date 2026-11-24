"""Inicio del panel del aprendiz: cada indicador una vez, con ayudas visuales y sin datos inventados."""

import re
import unittest
from datetime import date

from app import db
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from tests import test_experiencia_panel as base


class PanelAprendizInicioTest(unittest.TestCase):
    # Reutiliza el escenario del inicio (instructor, ficha, aprendiz y entregas) sin repetir sus pruebas.
    setUp = base.ExperienciaPanelTestCase.setUp
    tearDown = base.ExperienciaPanelTestCase.tearDown
    panel = base.ExperienciaPanelTestCase.panel

    @staticmethod
    def cabecera(html):
        return re.search(r'<header class="card panel-header-card[^"]*"[^>]*>(.*?)</header>', html, re.S).group(1)

    def registrar_asistencia(self, estados):
        for dia, estado in enumerate(estados, start=1):
            sesion = SesionAsistencia(ficha_id=self.ficha_id, fecha=date(2026, 3, dia))
            db.session.add(sesion)
            db.session.flush()
            db.session.add(RegistroAsistencia(sesion_id=sesion.id, aprendiz_id=self.aprendiz_id, estado=estado))
        db.session.commit()

    def test_cinta_con_tres_indicadores_graficos(self):
        html, _ = self.panel()
        cabecera = self.cabecera(html)
        self.assertEqual(cabecera.count('class="viz-donut '), 2)
        self.assertIn('aria-label="Asistencia: sin datos"', cabecera)
        self.assertIn('aria-label="RAPs aprobados: sin datos"', cabecera)
        self.assertIn('Evidencias por entregar', cabecera)
        self.assertNotIn('quick-ribbon-item', cabecera)

    def test_porcentaje_y_texto_de_asistencia_coinciden(self):
        self.registrar_asistencia(['ASISTE', 'FALTA', 'EXCUSA_MEDICA', 'ASISTE'])
        html, _ = self.panel()
        cabecera = self.cabecera(html)
        # Solo la falta sin justificar resta: 3 de 4 sesiones = 75 %.
        self.assertIn('aria-label="Asistencia: 75%"', cabecera)
        self.assertIn('3 de 4 sesiones', cabecera)
        self.assertNotIn('2 de 4 sesiones', html)
        self.assertNotIn('2/4 sesiones', html)

    def test_prioridades_primero_lo_academico_y_el_aseo_al_final(self):
        html, _ = self.panel()
        prioridades = html[html.index('learner-priority-dashboard'):html.index('learner-navigation-sticky')]
        self.assertLess(prioridades.index('priority-card-alerts'), prioridades.index('priority-card-cleaning'))
        self.assertNotIn('priority-card-performance', prioridades)

    def test_el_turno_con_el_instructor_va_despues_de_las_prioridades(self):
        html, _ = self.panel()
        self.assertLess(html.index('learner-priority-dashboard'), html.index('id="seccion-turno-atencion"'))

    def test_umbrales_de_color_unicos(self):
        self.registrar_asistencia(['ASISTE'] * 7 + ['FALTA'] * 3)
        html, _ = self.panel()
        # 70 % de asistencia: por debajo del umbral verde (80) y sobre el amarillo (60).
        self.assertIn('viz-donut viz-donut--warning', self.cabecera(html))

    def test_la_pestana_de_evidencias_cuenta_lo_mismo_que_la_cabecera(self):
        html, _ = self.panel()
        kpi = re.search(r'Evidencias por entregar\s*</span>\s*<strong class="viz-kpi-value">(\d+)', self.cabecera(html))
        self.assertIsNotNone(kpi)
        insignia = re.search(r'id="tab-evidencias-counter"[^>]*>(\d+)<', html)
        if int(kpi.group(1)):
            self.assertEqual(insignia.group(1), kpi.group(1))
        else:
            self.assertIsNone(insignia)

    def test_estado_del_aprendiz_usa_el_vocabulario_del_semaforo(self):
        html, _ = self.panel()
        estado = re.search(r'learner-status-pill">([^<]+)<', html).group(1)
        self.assertIn(estado, ('Excelente', 'Al día', 'En seguimiento', 'Riesgo alto'))

    def test_pestanas_y_barra_movil_usan_las_mismas_etiquetas(self):
        html, _ = self.panel()
        pestanas = re.findall(r'<span class="tab-label">([^<]+)</span>', html)
        barra = re.search(r'<nav class="learner-bottom-nav"[\s\S]*?</nav>', html).group(0)
        self.assertEqual(pestanas, re.findall(r'<span>([^<]+)</span>', barra))

    def test_cabecera_sin_ranking_y_con_acciones_secundarias_plegadas(self):
        cabecera = self.cabecera(self.panel()[0])
        self.assertNotIn('learner-podium-badge', cabecera)
        self.assertIn('popovertarget="aprendiz-mas-acciones"', cabecera)
        self.assertNotIn('% Global', self.panel()[0])


def test_flujo_de_evidencias_en_barra_apilada():
    caso = PanelAprendizInicioTest('test_umbrales_de_color_unicos')
    caso.setUp()
    try:
        html, _ = caso.panel()
        assert 'Tus 2 evidencias entregadas: Con cambios solicitados 1, Revisión aprobada 1' in html
        assert 'experience-official-progress' not in html
    finally:
        caso.tearDown()


if __name__ == '__main__':
    unittest.main()
