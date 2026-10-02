"""Contrato de la navegación y contexto de la ficha en planeación."""

import re
import json
import secrets
import unittest
from datetime import date, datetime
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor, JuicioEvaluativo
from app.models import ArchivoFichaVersion, ResultadoCalculadoFicha, TIPO_PLANEACION
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
        self.assertIn('En celular, el periodo aparece debajo de cada competencia', html)
        self.assertNotRegex(html, r'class="pl-gantt-row[^>]*role="button"')

    def test_cronograma_ofrece_rap_con_conteos_y_detalle_por_aprendiz(self):
        self.pagina(con_planeacion=True)
        ana = Aprendiz(ficha_id=self.ficha.id, documento='111', nombre='Ana', apellidos='Prueba', estado='EN FORMACION')
        beatriz = Aprendiz(ficha_id=self.ficha.id, documento='222', nombre='Beatriz', apellidos='Prueba', estado='EN FORMACION')
        retirado = Aprendiz(ficha_id=self.ficha.id, documento='333', nombre='Retirado', apellidos='Prueba', estado='RETIRADO')
        db.session.add_all([ana, beatriz, retirado])
        db.session.flush()
        db.session.add(JuicioEvaluativo(ficha_id=self.ficha.id, aprendiz_id=ana.id,
            resultado_aprendizaje='601390 - Identificar la dinámica organizacional del SENA.',
            juicio='NO APROBADO', funcionario_registro='Instructora evaluadora', fecha_juicio=datetime(2026, 9, 15)))
        db.session.commit()
        html = self.pagina()
        datos = json.loads(re.search(r'<script id="pl-evaluaciones-json"[^>]*>(.*?)</script>', html, re.S).group(1))
        induccion = next(d for d in datos.values() if d['nombre'] == 'Inducción')
        self.assertEqual(induccion['resumen']['total'], 2)
        self.assertEqual(induccion['resumen']['evaluados'], 1)
        self.assertEqual(induccion['resumen']['pendientes'], 1)
        self.assertEqual(induccion['resultados'][0]['aprendices'][0]['instructor'], 'Instructora evaluadora')
        self.assertNotIn(retirado.id, [a['id'] for a in induccion['aprendices']])
        self.assertIn('data-evaluacion-target="tramo-0"', html)
        self.assertIn('Resultados de aprendizaje', html)
        self.assertIn('Ver aprendices', html)
        self.assertRegex(html, r'<strong>1</strong> evaluado</span>')
        self.assertRegex(html, r'<strong>1</strong> pendiente</span>')
        self.assertIn('js/planeacion_evaluaciones.js', html)
        self.assertRegex(html, r'<dialog[^>]*id="pl-evaluaciones"[^>]*aria-labelledby="pl-evaluaciones-titulo"')
        self.assertIn('601390', html)
        # Una nueva consulta debe reflejar el juicio persistido más reciente.
        db.session.add(JuicioEvaluativo(ficha_id=self.ficha.id, aprendiz_id=beatriz.id,
            resultado_aprendizaje='601390 - Identificar la dinámica organizacional del SENA.',
            juicio='APROBADO', funcionario_registro='Otro instructor', fecha_juicio=datetime(2026, 9, 16)))
        db.session.commit()
        actualizado = json.loads(re.search(r'<script id="pl-evaluaciones-json"[^>]*>(.*?)</script>', self.pagina(), re.S).group(1))
        self.assertEqual(actualizado['tramo-0']['resumen']['pendientes'], 0)

    def test_el_detalle_de_evaluaciones_conserva_el_aislamiento_de_la_ficha(self):
        self.pagina(con_planeacion=True)
        ajeno = Instructor(nombre='Instructor ajeno', correo='ajeno@example.com')
        ajeno.set_password(secrets.token_urlsafe(24))
        db.session.add(ajeno)
        db.session.commit()
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(ajeno.id)
        from flask import g
        g.pop('_login_user', None)
        respuesta = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/planeacion')
        self.assertEqual(respuesta.status_code, 302)
        self.assertNotIn('pl-evaluaciones-json', respuesta.get_data(as_text=True))

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
        from app.models import ArchivoFichaVersion, TIPO_PLANEACION
        version = ArchivoFichaVersion.query.filter_by(
            ficha_id=self.ficha.id, tipo=TIPO_PLANEACION
        ).one()
        version.contenido_extraido_json = None
        version.contenido_extraido_version = None
        db.session.commit()
        with patch('app.routes.planeacion.parsear_planeacion', side_effect=ValueError('Archivo no legible')):
            html = self.pagina()
        alerta = re.search(r'<div[^>]*role="alert"[^>]*>(.*?)</div>\s*</div>', html, re.S)
        self.assertIsNotNone(alerta)
        self.assertIn('La planeación no está disponible', alerta.group(1))
        self.assertIn('Archivo no legible', alerta.group(1))
        self.assertIn('Reintentar', alerta.group(1))
        self.assertIn(f'href="/instructor/fichas/{self.ficha.id}/planeacion"', alerta.group(1))

    def test_analisis_reutiliza_extraccion_y_panorama_persistidos(self):
        self.pagina(con_planeacion=True)
        version = ArchivoFichaVersion.query.filter_by(
            ficha_id=self.ficha.id, tipo=TIPO_PLANEACION
        ).one()
        self.assertTrue(version.contenido_extraido_json)
        self.assertEqual(version.contenido_extraido_version, 'planeacion-v1')
        self.assertEqual(ResultadoCalculadoFicha.query.filter_by(tipo='panorama').count(), 1)

        with (
            patch('app.routes.planeacion.parsear_planeacion', side_effect=AssertionError('No debe abrir el Excel')),
            patch('app.routes.planeacion.construir_panorama', side_effect=AssertionError('No debe recalcular el panorama')),
        ):
            respuesta = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/planeacion')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(ResultadoCalculadoFicha.query.filter_by(tipo='panorama').count(), 1)
