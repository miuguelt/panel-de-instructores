"""Página de Alertas: la cifra de la barra se encuentra en la página y nada se repite.

- «Alertas abiertas» muestra el mismo número que el distintivo de la barra de la ficha.
- El semáforo agregado vive en la Visión general; aquí se filtra la lista por nivel.
- El cronograma y la tarjeta TyT viven en la Visión general y en Pruebas Saber TyT.
- Los parámetros del Acuerdo 009 aparecen una sola vez, plegados al final.
"""

import re
import secrets
import unittest
from unittest.mock import patch

from app import create_app, db
from app.models import Alerta, Aprendiz, Ficha, Instructor


class AlertasPaginaTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
                               'RATELIMIT_ENABLED': False, 'SECRET_KEY': secrets.token_hex(16)})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        instructor = Instructor(nombre='Instructor', correo='alertas-pagina@example.com')
        instructor.set_password(secrets.token_urlsafe(16))
        db.session.add(instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='5151', nombre_programa='ADSO', instructor_id=instructor.id)
        db.session.add(self.ficha)
        db.session.flush()
        self.ana = Aprendiz(documento='1', nombre='Ana', apellidos='Ruiz', ficha_id=self.ficha.id)
        self.luis = Aprendiz(documento='2', nombre='Luis', apellidos='Mora', ficha_id=self.ficha.id)
        db.session.add_all([self.ana, self.luis])
        db.session.flush()
        for titulo in ('Faltas seguidas', 'Tareas vencidas'):
            db.session.add(Alerta(ficha_id=self.ficha.id, aprendiz_id=self.ana.id, titulo=titulo, mensaje='m'))
        db.session.add(Alerta(ficha_id=self.ficha.id, aprendiz_id=None, titulo='Cierre cercano', mensaje='m'))
        db.session.add(Alerta(ficha_id=self.ficha.id, aprendiz_id=self.luis.id, titulo='Resuelta',
                              mensaje='m', estado='resuelta'))
        db.session.commit()
        self.cliente = self.app.test_client()
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(instructor.id)
            sesion['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def pagina(self):
        with patch('app.routes.instructor.alertas_materiales.actualizar_alertas_ficha'):
            respuesta = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/alertas')
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.get_data(as_text=True)

    @staticmethod
    def contenido(html):
        return html[html.index('<main'):]

    def test_alertas_abiertas_coincide_con_la_barra(self):
        html = self.pagina()
        barra = re.search(r'ficha-nav-alertas-count">(\d+)<', html).group(1)
        self.assertEqual(barra, '3')
        self.assertIn('3 alertas abiertas', self.contenido(html))

    def test_cada_aprendiz_muestra_sus_alertas_abiertas(self):
        html = self.contenido(self.pagina())
        tarjeta_ana = html[html.index('Ana Ruiz'):html.index('Luis Mora')] if html.index('Ana Ruiz') < html.index('Luis Mora') else html[html.index('Ana Ruiz'):]
        self.assertIn('2 alertas abiertas', tarjeta_ana)

    def test_filtros_por_nivel_con_el_vocabulario_del_semaforo(self):
        html = self.contenido(self.pagina())
        etiquetas = re.findall(r'data-filtro-nivel="(?:rojo|amarillo|verde|todos)"[^>]*>\s*([^<(]+?)\s*[(<]', html)
        self.assertEqual(etiquetas, ['Todos', 'Riesgo alto', 'En seguimiento', 'Al día'])
        self.assertEqual(len(re.findall(r'data-nivel="(rojo|amarillo|verde)"', html)), 2)

    def test_no_repite_lo_que_vive_en_otras_pantallas(self):
        html = self.contenido(self.pagina())
        self.assertNotIn('Semáforo del grupo', html)
        self.assertNotIn('cronograma-plegado', html)
        self.assertNotIn('legend-item', html)
        self.assertNotIn(' disabled>', html)
        self.assertNotIn('Tomar asistencia hoy', html)

    def test_una_sola_accion_principal_y_la_ficha_sobre_el_titulo(self):
        html = self.contenido(self.pagina())
        cabecera = html[html.index('page-header'):html.index('</h1>')]
        self.assertIn('Ficha 5151', cabecera)
        self.assertEqual(len(re.findall(r'class="btn btn-primary', html)), 2,
                         'Solo «Casos de seguimiento» y «Guardar configuración» (dentro de los ajustes).')

    def test_parametros_una_sola_vez_y_al_final(self):
        html = self.contenido(self.pagina())
        self.assertEqual(html.count('Inasistencias consecutivas'), 1)
        self.assertIn('Notas negativas en el observador', html)
        self.assertNotIn('Llamados de atención del observador', html)
        self.assertLess(html.index('data-filtro-nivel'), html.index('Ajustar parámetros'))


if __name__ == '__main__':
    unittest.main()
