"""Contrato de la navegación y contexto de la ficha en planeación."""

import re
import secrets
import unittest
from datetime import date
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app import create_app, db
from app.models import Ficha, Instructor
from tests.apoyo_planeacion import crear_planeacion_xlsx


class PlaneacionUXTestCase(unittest.TestCase):
    def setUp(self):
        self.archivos = TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'UPLOAD_FOLDER': self.archivos.name,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        instructor = Instructor(nombre='Instructor de prueba', correo='planeacion-ux@example.com')
        instructor.set_password(secrets.token_urlsafe(24))
        db.session.add(instructor)
        db.session.flush()
        self.ficha = Ficha(
            codigo='3336360', codigo_ficha='3336360', codigo_programa='228118',
            nombre_programa='Tecnólogo en Analisis y Desarrollo de Software',
            instructor_id=instructor.id, fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 12, 31),
        )
        db.session.add(self.ficha)
        db.session.commit()
        self.cliente = self.app.test_client()
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(instructor.id)
            sesion['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.archivos.cleanup()

    def pagina(self, con_planeacion=False):
        if con_planeacion:
            ruta = crear_planeacion_xlsx(self.archivos.name)
            with ruta.open('rb') as archivo:
                respuesta = self.cliente.post(
                    f'/instructor/fichas/{self.ficha.id}/planeacion/cargar',
                    data={'archivo_planeacion': (archivo, ruta.name)},
                    content_type='multipart/form-data',
                )
                self.assertEqual(respuesta.status_code, 302)
        respuesta = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/planeacion')
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.get_data(as_text=True)

    def test_la_cabecera_identifica_la_ficha_y_ofrece_cargar_fuentes(self):
        html = self.pagina()
        self.assertRegex(html, r'<h1[^>]*>Planeación de la ficha</h1>')
        contexto = re.search(r'class="pl-heading-context"[^>]*>(.*?)</(?:div|p)>', html, re.S)
        self.assertIsNotNone(contexto)
        self.assertIn(self.ficha.codigo, contexto.group(1))
        self.assertIn(self.ficha.nombre_programa, contexto.group(1))
        self.assertRegex(html, r'<a\b[^>]*href="#centro-carga"[^>]*>')
        self.assertIn(f'data-ficha-id="{self.ficha.id}"', html)
        self.assertIn('js/planeacion_navegacion.js', html)

    def test_navegacion_separa_analisis_secundarios_sin_perder_destinos(self):
        html = self.pagina(con_planeacion=True)
        nav = re.search(r'<nav\b[^>]*class="pl-subnav"[^>]*>(.*?)</nav>', html, re.S)
        self.assertIsNotNone(nav)
        secundarios = re.search(r'<details\b[^>]*class="pl-nav-more"[^>]*>(.*?)</details>', nav.group(1), re.S)
        self.assertIsNotNone(secundarios)
        self.assertIn('Más análisis', secundarios.group(1))
        principales = nav.group(1).replace(secundarios.group(0), '')
        for destino in ['seccion-resumen', 'seccion-gantt', 'seccion-riesgos', 'seccion-detalle', 'documentos']:
            self.assertIn(f'href="#{destino}"', principales)
        for destino in re.findall(r'href="#([^"]+)"', nav.group(1)):
            self.assertIn(f'id="{destino}"', html)
        self.assertNotIn('href="#seccion-curva-s"', principales)
        self.assertIn('href="#seccion-curva-s"', secundarios.group(1))

    def test_ficha_vacia_no_ofrece_secciones_de_analisis_inexistentes(self):
        html = self.pagina()
        self.assertTrue('href="#seccion-gantt"' not in html, 'El cronograma vacío no debe ofrecerse.')
        self.assertTrue('id="centro-carga"' in html)
        self.assertTrue('id="documentos"' in html)
        visible = re.sub(r'<(?:script|style)\b.*?</(?:script|style)>', '', html, flags=re.S)
        self.assertTrue('undefined' not in visible)
        self.assertTrue(bool(re.search(r'<a[^>]*href="#centro-carga"[^>]*>\s*Cargar archivos\s*</a>', html)), 'El estado vacío necesita una acción directa de carga.')

    def test_cronograma_muestra_etiquetas_estables_y_acciones_accesibles(self):
        html = self.pagina(con_planeacion=True)
        cronograma = re.search(r'<div\b[^>]*class="pl-gantt-wrap"[^>]*>', html)
        self.assertIsNotNone(cronograma)
        self.assertIn('role="region"', cronograma.group(0))
        self.assertIn('aria-label="Cronograma planificado y avance por trimestre"', cronograma.group(0))
        tarjetas = re.findall(r'<article\b[^>]*class="pl-gantt-row[^>]*>(.*?)</article>', html, re.S)
        self.assertGreater(len(tarjetas), 0)
        for tarjeta in tarjetas:
            self.assertRegex(tarjeta, r'<button\b[^>]*class="pl-btn-pedagogico"[^>]*aria-label="Abrir ficha pedagógica de [^"]+"')
            self.assertIn('Ver ficha', tarjeta)
            self.assertIn('pl-gantt-progress', tarjeta)
            self.assertIn('% aprobados', tarjeta)
        self.assertIn('Desplaza el cronograma horizontalmente para consultar todos los trimestres', html)
        self.assertNotRegex(html, r'class="pl-gantt-row[^>]*role="button"')

    def test_carga_ofrece_nombres_accesibles_y_anuncia_resultados(self):
        html = self.pagina()
        for nombre in ['archivo_planeacion', 'archivo_juicios', 'archivo_programa']:
            entrada = re.search(r'<input\b[^>]*name="' + nombre + r'"[^>]*>', html)
            self.assertIsNotNone(entrada)
            self.assertRegex(entrada.group(0), r'aria-label="[^"]+"')
        feedback = re.search(r'<[^>]+id="pl-carga-feedback"[^>]*>', html)
        self.assertIsNotNone(feedback)
        self.assertIn('role="status"', feedback.group(0))
        self.assertIn('aria-live="polite"', feedback.group(0))

    def test_error_de_lectura_anuncia_el_problema_y_ofrece_reintento(self):
        self.pagina(con_planeacion=True)
        with patch('app.routes.planeacion.parsear_planeacion', side_effect=ValueError('Archivo no legible')):
            html = self.pagina()
        alerta = re.search(r'<div[^>]*role="alert"[^>]*>(.*?)</div>\s*</div>', html, re.S)
        self.assertIsNotNone(alerta)
        self.assertIn('La planeación no está disponible', alerta.group(1))
        self.assertIn('Archivo no legible', alerta.group(1))
        self.assertIn('Reintentar', alerta.group(1))
        self.assertIn(f'href="/instructor/fichas/{self.ficha.id}/planeacion"', alerta.group(1))
