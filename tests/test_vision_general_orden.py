"""Contrato de la visión general: primero el tiempo y la fase, sin datos inventados."""

import re
import secrets
import unittest
from datetime import date
from unittest.mock import patch

from flask import render_template, url_for

from app import create_app, db
from app.models import Ficha, Instructor


RECOMENDACION = {
    'id': 1, 'severidad': 'preventiva', 'icono': '💡', 'metrica_destacada': None,
    'titulo': 'Revisar la asistencia de la semana',
    'mensaje': 'Hay aprendices con inasistencias seguidas.',
    'accion_texto': None, 'accion_url': None,
}


class VisionGeneralOrdenTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        self.instructor = Instructor(nombre='Instructor de prueba', correo='vision-orden@example.com')
        self.instructor.set_password(secrets.token_urlsafe(24))
        db.session.add(self.instructor)
        db.session.commit()
        self.cliente = self.app.test_client()
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def crear_ficha(self, inicio=None, fin=None):
        ficha = Ficha(
            codigo='3336361', codigo_ficha='3336361', codigo_programa='228118',
            nombre_programa='Tecnólogo en Desarrollo de Software',
            instructor_id=self.instructor.id, fecha_inicio=inicio, fecha_fin=fin,
        )
        db.session.add(ficha)
        db.session.commit()
        return ficha

    def pagina(self, ficha, recomendaciones=None):
        with patch('app.services.recomendaciones.obtener_recomendaciones_ficha',
                   return_value=recomendaciones or []):
            respuesta = self.cliente.get(f'/instructor/fichas/{ficha.id}/resumen')
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.get_data(as_text=True)

    @staticmethod
    def bloque_tiempo(html):
        bloque = re.search(r'<section class="ficha-time-hero[^"]*"[^>]*>(.*?)</section>', html, re.S)
        assert bloque, 'No se encontró el bloque de tiempo y fase'
        return bloque.group(1)

    def test_tiempo_y_fase_van_despues_de_la_cabecera_y_antes_de_la_atencion(self):
        ficha = self.crear_ficha(date(2026, 1, 1), date(2027, 12, 31))
        html = self.pagina(ficha, recomendaciones=[RECOMENDACION])

        cabecera = html.index('</header>')
        tiempo = html.index('class="ficha-time-hero')
        urgente = html.index('class="urgent-panel"')
        recomendaciones = html.index('id="centro-recomendaciones"')
        indicadores = html.index('class="vision-bento-section"')

        self.assertLess(cabecera, tiempo)
        self.assertLess(tiempo, urgente)
        self.assertLess(urgente, recomendaciones)
        self.assertLess(recomendaciones, indicadores)

    def test_sin_recomendaciones_el_tiempo_sigue_antes_de_la_atencion(self):
        ficha = self.crear_ficha(date(2026, 1, 1), date(2027, 12, 31))
        html = self.pagina(ficha)

        self.assertNotIn('id="centro-recomendaciones"', html)
        self.assertLess(html.index('class="ficha-time-hero'), html.index('class="urgent-panel"'))

    def test_el_bloque_de_tiempo_muestra_inicio_productiva_y_fin_de_ficha(self):
        ficha = self.crear_ficha(date(2026, 1, 1), date(2027, 12, 31))
        bloque = self.bloque_tiempo(self.pagina(ficha))

        self.assertRegex(bloque, r'Inicio productiva:</span>\s*<strong>30/06/2027</strong>')
        self.assertRegex(bloque, r'Fin de la ficha:</span>\s*<strong>31/12/2027</strong>')
        self.assertRegex(bloque, r'Etapa productiva:</span>\s*<strong>6 meses</strong>')

    def test_ficha_sin_planeacion_ni_juicios_no_inventa_fases_ni_duracion(self):
        ficha = self.crear_ficha()
        html = self.pagina(ficha)
        bloque = self.bloque_tiempo(html)
        # The RAP audit modal keeps fixed phase filter buttons; they are labels, not ficha data.
        sin_modal = re.sub(r'<dialog id="modal-raps-vencidos".*?</dialog>', '', html, flags=re.S)
        self.assertNotEqual(sin_modal, html)

        for inventado in ('Ejecución', 'Análisis', '6 meses'):
            self.assertNotIn(inventado, sin_modal)
        self.assertIn('Sin datos', bloque)
        with self.app.test_request_context():
            enlace = url_for('planeacion.analisis', ficha_id=ficha.id)
        self.assertRegex(bloque, rf'<a\b[^>]*href="{re.escape(enlace)}"[^>]*>\s*Cargar planeación\s*</a>')
        self.assertRegex(bloque, r'Fase esperada:</span>\s*<strong>Sin datos</strong>')
        self.assertRegex(bloque, r'Fase real \(RAPs\):</span>\s*<strong>Sin datos</strong>')
        self.assertRegex(bloque, r'Etapa productiva:</span>\s*<strong>Sin datos</strong>')

    def test_rastreador_de_fases_no_inventa_fases_cuando_faltan(self):
        ficha = self.crear_ficha()
        fases_data = {
            'disponible': True, 'planeacion_sincronizada': False, 'desfase_fases': 0,
            'fase_esperada': None, 'fase_real': None, 'fases': [],
            'resumen_raps': {'total': 3, 'esperados': 1, 'aprobados': 0},
            'mensaje_veredicto': 'Faltan datos para comparar las fases.',
        }
        with self.app.test_request_context():
            html = render_template('instructor/_ficha_fases_tracker.html',
                                   fases_data=fases_data, ficha=ficha)
        self.assertNotIn('Ejecución', html)
        self.assertNotIn('Análisis', html)
        self.assertEqual(html.count('Sin datos'), 2)

    def test_rastreador_trata_fase_real_sin_raps_como_sin_datos(self):
        ficha = self.crear_ficha()
        fases_data = {
            'disponible': True, 'planeacion_sincronizada': False, 'desfase_fases': 0,
            'fase_esperada': {'nombre': 'Fechas pendientes', 'icono': '📅', 'orden': 0},
            'fase_real': {'nombre': 'ANÁLISIS', 'icono': '🔍', 'orden': 0, 'resultados_total': 0},
            'fases': [], 'resumen_raps': {'total': 0},
            'mensaje_veredicto': 'Configura las fechas de la ficha.',
        }
        with self.app.test_request_context():
            html = render_template('instructor/_ficha_fases_tracker.html',
                                   fases_data=fases_data, ficha=ficha)
        comparacion = re.search(r'class="fases-comparison-summary">(.*?)</div>\s*</div>', html, re.S)
        self.assertIsNotNone(comparacion)
        self.assertNotIn('Análisis', comparacion.group(1))
        self.assertEqual(comparacion.group(1).count('Sin datos'), 2)

    def test_rastreador_conserva_fases_reales(self):
        ficha = self.crear_ficha()
        fases_data = {
            'disponible': True, 'planeacion_sincronizada': True, 'desfase_fases': 1,
            'fase_esperada': {'nombre': 'EJECUCIÓN', 'icono': '⚙️', 'orden': 2},
            'fase_real': {'nombre': 'PLANEACIÓN', 'icono': '📐', 'orden': 1, 'resultados_total': 20},
            'fases': [], 'resumen_raps': {'total': 0},
            'mensaje_veredicto': 'Retraso de 1 fase.',
        }
        with self.app.test_request_context():
            html = render_template('instructor/_ficha_fases_tracker.html',
                                   fases_data=fases_data, ficha=ficha)
        self.assertIn('Ejecución', html)
        self.assertIn('Planeación', html)
        self.assertNotIn('Sin datos', html)


if __name__ == '__main__':
    unittest.main()
