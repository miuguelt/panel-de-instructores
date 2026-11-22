"""Menú de módulos de la ficha: principales visibles y el resto en «Más módulos»."""

import re
import tempfile
import unittest
from datetime import date, timedelta

from flask import g

from app import create_app, db
from app.models import (
    ConfiguracionAlertas,
    ConfiguracionAlertasComite,
    ConfiguracionAseo,
    ConfiguracionRanking,
    Ficha,
    Instructor,
)

PRINCIPALES = ('Visión general', 'Asistencia', 'Tareas', 'Aprendices', 'Juicios', 'Planeación', 'Aseo')
SECUNDARIOS = ('Observador', 'Casos de seguimiento', 'Novedades', 'Fila de atención', 'Seguimiento TyT',
               'Estadísticas', 'Materiales', 'Ranking', 'Grupos')


class MenuFichaTestCase(unittest.TestCase):
    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'UPLOAD_FOLDER': self.uploads.name,
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        instructor = Instructor(nombre='Instructora de prueba', correo='menu@sena.edu.co', rol='admin')
        instructor.set_password('clave-segura')
        db.session.add(instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='3000002', codigo_ficha='3000002', nombre_programa='Programa de prueba',
                           instructor_id=instructor.id, fecha_inicio=date.today() - timedelta(days=30),
                           fecha_fin=date.today() + timedelta(days=330))
        db.session.add(self.ficha)
        db.session.flush()
        db.session.add_all([ConfiguracionAlertas(ficha_id=self.ficha.id),
                            ConfiguracionAlertasComite(ficha_id=self.ficha.id),
                            ConfiguracionRanking(ficha_id=self.ficha.id),
                            ConfiguracionAseo(ficha_id=self.ficha.id)])
        db.session.commit()
        self.cliente = self.app.test_client()
        g.pop('_login_user', None)
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(instructor.id)
            sesion['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def _menu(self, ruta):
        respuesta = self.cliente.get(ruta)
        self.assertEqual(respuesta.status_code, 200, ruta)
        html = respuesta.get_data(as_text=True)
        nav = re.search(r'<nav class="ficha-nav"[\s\S]*?</nav>', html)
        self.assertIsNotNone(nav, f'{ruta} debe mostrar el menú de la ficha')
        mas = re.search(r'<div id="ficha-nav-mas"[^>]*popover[\s\S]*?</div>\s*</div>', html)
        self.assertIsNotNone(mas, f'{ruta} debe incluir el panel «Más módulos»')
        return nav.group(0), mas.group(0)

    @staticmethod
    def _textos(fragmento):
        return [re.sub(r'\s+', ' ', t).strip() for t in re.findall(r'<span class="ficha-nav-label">([^<]*)</span>', fragmento)]

    def test_modulos_principales_visibles_y_resto_en_mas(self):
        nav, mas = self._menu(f'/instructor/fichas/{self.ficha.id}/tareas')
        self.assertEqual(self._textos(nav.split('ficha-nav-more')[0]), list(PRINCIPALES))
        self.assertEqual(self._textos(mas), list(SECUNDARIOS))
        self.assertIn('popovertarget="ficha-nav-mas"', nav)
        self.assertIn('aria-current="page"', nav.split('ficha-nav-more')[0])

    def test_panel_mas_agrupa_los_modulos_con_titulo(self):
        _, mas = self._menu(f'/instructor/fichas/{self.ficha.id}/tareas')
        self.assertEqual(re.findall(r'<p class="ficha-nav-group-title"[^>]*>([^<]+)</p>', mas),
                         ['Seguimiento y convivencia', 'Recursos y participación'])

    def test_modulo_activo_dentro_de_mas_resalta_el_boton(self):
        nav, mas = self._menu(f'/instructor/fichas/{self.ficha.id}/ranking')
        boton = re.search(r'<button[^>]*ficha-nav-more[^>]*>[\s\S]*?</button>', nav).group(0)
        self.assertIn('is-active', boton)
        self.assertIn('Ranking', boton)
        self.assertRegex(mas, r'aria-current="page"[^>]*>[\s\S]*?Ranking')
        self.assertNotIn('aria-current="page"', nav.split('ficha-nav-more')[0])

    def test_boton_mas_sin_modulo_activo_dice_mas_modulos(self):
        nav, _ = self._menu(f'/instructor/fichas/{self.ficha.id}/asistencia')
        boton = re.search(r'<button[^>]*ficha-nav-more[^>]*>[\s\S]*?</button>', nav).group(0)
        self.assertNotIn('is-active', boton)
        self.assertIn('Más módulos', boton)

    def test_menu_visible_en_fila_tyt_y_novedades(self):
        for ruta, etiqueta in ((f'/instructor/fichas/{self.ficha.id}/fila-atencion', 'Fila de atención'),
                               (f'/instructor/fichas/{self.ficha.id}/seguimiento-tyt', 'Seguimiento TyT'),
                               (f'/instructor/fichas/{self.ficha.id}/novedades-productiva', 'Novedades')):
            nav, _ = self._menu(ruta)
            boton = re.search(r'<button[^>]*ficha-nav-more[^>]*>[\s\S]*?</button>', nav).group(0)
            self.assertIn(etiqueta, boton, ruta)

    def test_alertas_es_distintivo_junto_a_vision_general(self):
        from app.models.alertas import Alerta
        db.session.add(Alerta(ficha_id=self.ficha.id, titulo='Riesgo', mensaje='Inasistencia'))
        db.session.commit()
        nav, mas = self._menu(f'/instructor/fichas/{self.ficha.id}/tareas')
        enlace = re.search(r'<a [^>]*class="ficha-nav-alertas[^"]*"[^>]*>[\s\S]*?</a>', nav)
        self.assertIsNotNone(enlace)
        self.assertIn('aria-label="Alertas: 1 activas"', enlace.group(0))
        self.assertIn('ficha-nav-alertas-count">1<', enlace.group(0))
        self.assertLess(nav.index('Visión general'), nav.index('ficha-nav-alertas'))
        self.assertLess(nav.index('ficha-nav-alertas'), nav.index('>Asistencia<'))
        self.assertNotIn('Alertas', mas)

    def test_menu_de_usuario_agrupa_tema_notificaciones_y_salir(self):
        html = self.cliente.get('/instructor/').get_data(as_text=True)
        menu = re.search(r'<div id="nav-user-menu" popover[\s\S]*?</form>\s*</div>', html)
        self.assertIsNotNone(menu)
        self.assertIn('popovertarget="nav-user-menu"', html)
        for texto in ('Instructora de prueba', 'Notificaciones', 'Cambiar tema', 'Salir', 'name="csrf_token"', 'toggleTheme()'):
            self.assertIn(texto, menu.group(0))
        self.assertNotIn('class="theme-float"', html)
        self.assertIn('class="nav-icon-button"', html)

    def test_paginas_sin_ficha_no_muestran_el_menu(self):
        html = self.cliente.get('/instructor/').get_data(as_text=True)
        self.assertNotIn('class="ficha-nav"', html)

    def _pagina(self, ruta):
        respuesta = self.cliente.get(ruta)
        self.assertEqual(respuesta.status_code, 200, ruta)
        return respuesta.get_data(as_text=True)

    @staticmethod
    def _titulo_y_h1(html):
        titulo = re.search(r'<title>([^<]*)</title>', html).group(1).strip()
        h1 = re.search(r'<h1\b[^>]*>(.*?)</h1>', html, re.S).group(1)
        return titulo, ' '.join(re.sub(r'<[^>]+>', ' ', h1).split())

    def test_titulo_de_pestana_y_h1_coinciden_con_la_etiqueta_del_menu(self):
        fid = self.ficha.id
        paginas = {
            '/instructor/': 'Inicio',
            '/instructor/fichas': 'Fichas',
            '/instructor/comite/fichas-terminadas': 'Comité',
            f'/instructor/fichas/{fid}/asistencia': 'Asistencia',
            f'/instructor/fichas/{fid}/juicios': 'Juicios',
            f'/instructor/fichas/{fid}/planeacion': 'Planeación',
            f'/instructor/fichas/{fid}/alertas': 'Alertas',
        }
        for ruta, etiqueta in paginas.items():
            with self.subTest(ruta=ruta):
                titulo, h1 = self._titulo_y_h1(self._pagina(ruta))
                self.assertTrue(titulo.startswith(f'{etiqueta} - '), titulo)
                self.assertEqual(h1, etiqueta)

    def test_las_etiquetas_usadas_en_los_titulos_existen_en_los_menus(self):
        nav, _ = self._menu(f'/instructor/fichas/{self.ficha.id}/tareas')
        modulos = self._textos(nav.split('ficha-nav-more')[0])
        for etiqueta in ('Asistencia', 'Juicios', 'Planeación'):
            self.assertIn(etiqueta, modulos)
        self.assertIn('Alertas', nav)
        general = self._pagina('/instructor/')
        barra = re.search(r'<div class="nav-primary"[\s\S]*?</div>', general).group(0)
        for etiqueta in ('Inicio', 'Fichas', 'Comité'):
            self.assertIn(f'<span>{etiqueta}</span>', barra)

    def test_juicios_usa_la_cabecera_comun_y_no_la_barra_contextual(self):
        html = self._pagina(f'/instructor/fichas/{self.ficha.id}/juicios')
        cabecera = re.search(r'<header class="page-header[^"]*">[\s\S]*?</header>', html)
        self.assertIsNotNone(cabecera)
        self.assertIn('Cargar juicios', cabecera.group(0))
        self.assertIn('data-lucide="upload"', cabecera.group(0))
        self.assertNotIn('nav-context', html)

    def test_los_modulos_no_repiten_el_enlace_a_vision_general(self):
        fid = self.ficha.id
        for modulo in ('asistencia', 'tareas', 'juicios', 'planeacion', 'alertas', 'aprendices',
                       'estadisticas', 'materiales', 'observador', 'ranking', 'turnos-aseo',
                       'casos-seguimiento'):
            ruta = f'/instructor/fichas/{fid}/{modulo}'
            respuesta = self.cliente.get(ruta)
            if respuesta.status_code == 404:
                continue
            with self.subTest(ruta=ruta):
                self.assertEqual(respuesta.status_code, 200)
                html = respuesta.get_data(as_text=True)
                contenido = html.split('</nav>', 2)[-1] if 'class="ficha-nav"' in html else html
                self.assertNotIn('&larr; Visión general', contenido)
                self.assertNotIn('← Visión general', contenido)
                self.assertIn('class="ficha-nav"', html, 'la barra de la ficha reemplaza el enlace de volver')

    def test_alertas_no_repite_notificaciones_y_usa_el_vocabulario_de_riesgo(self):
        from flask import url_for
        html = self._pagina(f'/instructor/fichas/{self.ficha.id}/alertas')
        with self.app.test_request_context():
            notificaciones = url_for('seguimiento.notificaciones_instructor')
        contenido = html[html.index('<h1'):]
        self.assertNotIn(f'href="{notificaciones}"', contenido, 'Notificaciones ya está en la barra superior')
        self.assertNotIn('🔔', html)
        for texto in ('Riesgo alto', 'En seguimiento', 'Al día'):
            self.assertIn(texto, contenido)
        for viejo in ("'En alerta'", '> Riesgo<', '> Alerta<', 'Tomar Asistencia Hoy'):
            self.assertNotIn(viejo, contenido)
        self.assertIn('Tomar asistencia hoy', contenido)

    def test_aseo_sin_sesiones_muestra_el_estado_vacio_comun(self):
        html = self._pagina(f'/instructor/fichas/{self.ficha.id}/turnos-aseo')
        vacio = re.search(r'<div class="viz-empty">[\s\S]*?</div>', html)
        self.assertIsNotNone(vacio)
        self.assertIn('Todavía no hay sesiones de clase registradas', vacio.group(0))
        self.assertIn('data-lucide="calendar-x"', vacio.group(0))
        self.assertIn(f'/instructor/fichas/{self.ficha.id}/asistencia', vacio.group(0))
        self.assertIn('Tomar asistencia', vacio.group(0))

    def test_asistencia_no_usa_la_etiqueta_corte_de_trabajo(self):
        html = self._pagina(f'/instructor/fichas/{self.ficha.id}/asistencia')
        self.assertNotIn('Corte de trabajo', html)
        self.assertNotIn('<title>Llamado a lista', html)


if __name__ == '__main__':
    unittest.main()
