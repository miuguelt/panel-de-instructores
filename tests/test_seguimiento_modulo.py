"""Módulo «Seguimiento»: casos, planes, novedades y observador con una sola cabecera.

Antes eran cinco pantallas sueltas que se enlazaban entre sí con botones
«Volver». Ahora comparten el título «Seguimiento» y cuatro pestañas en el mismo
orden; las direcciones no cambian.
"""

import re
import secrets
import unittest
from unittest.mock import patch

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor

PESTANAS = ['Casos', 'Planes de mejoramiento', 'Novedades', 'Observador']


class SeguimientoModuloTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
                               'RATELIMIT_ENABLED': False, 'SECRET_KEY': secrets.token_hex(16)})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        instructor = Instructor(nombre='Instructor', correo='seguimiento-modulo@example.com')
        instructor.set_password(secrets.token_urlsafe(16))
        db.session.add(instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='9191', nombre_programa='ADSO', instructor_id=instructor.id)
        db.session.add(self.ficha)
        db.session.flush()
        db.session.add(Aprendiz(documento='7', nombre='Ana', apellidos='Ruiz', ficha_id=self.ficha.id))
        db.session.commit()
        self.cliente = self.app.test_client()
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(instructor.id)
            sesion['_fresh'] = True
        fid = self.ficha.id
        self.paginas = {
            'Casos': f'/instructor/fichas/{fid}/casos-seguimiento',
            'Planes de mejoramiento': f'/instructor/fichas/{fid}/planes-mejoramiento',
            'Novedades': f'/instructor/fichas/{fid}/novedades-productiva',
            'Observador': f'/instructor/fichas/{fid}/observador',
        }

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def html(self, url):
        with patch('app.routes.seguimiento.actualizar_alertas_ficha', create=True):
            respuesta = self.cliente.get(url)
        self.assertEqual(respuesta.status_code, 200, url)
        return respuesta.get_data(as_text=True)

    def test_las_cuatro_pantallas_comparten_titulo_y_pestanas(self):
        for activa, url in self.paginas.items():
            with self.subTest(pestana=activa):
                html = self.html(url)
                h1 = re.search(r'<h1\b[^>]*>(.*?)</h1>', html, re.S).group(1)
                self.assertEqual(' '.join(re.sub(r'<[^>]+>', ' ', h1).split()), 'Seguimiento')
                nav = re.search(r'<nav class="seguimiento-pestanas"[\s\S]*?</nav>', html).group(0)
                etiquetas = [' '.join(re.sub(r'<[^>]+>', ' ', t).split())
                             for t in re.findall(r'<a [^>]*class="seguimiento-pestana[^"]*"[^>]*>([\s\S]*?)</a>', nav)]
                self.assertEqual(etiquetas, PESTANAS)
                actual = re.search(r'<a [^>]*aria-current="page"[^>]*>([\s\S]*?)</a>', nav).group(1)
                self.assertIn(activa, actual)
                self.assertNotIn('&larr; Volver', html)

    def test_casos_deja_los_parametros_despues_de_la_bandeja(self):
        html = self.html(self.paginas['Casos'])
        self.assertLess(html.index('followup-workspace'), html.index('Ajustar parámetros del seguimiento'))
        self.assertIn('Notas negativas en el observador', html)
        self.assertNotIn('>Llamados de atención<', html)
        self.assertNotIn('Gestionar planes', html)

    def test_tareas_y_por_aprendiz_son_pestanas_del_mismo_modulo(self):
        fid = self.ficha.id
        for url, activa in ((f'/instructor/fichas/{fid}/tareas', 'Por tarea'),
                            (f'/instructor/fichas/{fid}/evidencias-faltantes', 'Por aprendiz')):
            with self.subTest(url=url):
                html = self.html(url)
                h1 = re.search(r'<h1\b[^>]*>(.*?)</h1>', html, re.S).group(1)
                self.assertEqual(' '.join(re.sub(r'<[^>]+>', ' ', h1).split()), 'Tareas')
                actual = re.search(r'<a [^>]*aria-current="page"[^>]*>([\s\S]*?)</a>',
                                   re.search(r'<nav class="seguimiento-pestanas"[\s\S]*?</nav>', html).group(0)).group(1)
                self.assertIn(activa, actual)
                self.assertNotIn('&larr; Volver', html)


if __name__ == '__main__':
    unittest.main()
