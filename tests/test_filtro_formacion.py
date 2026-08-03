import unittest
from datetime import date

from app import create_app, db
from app.models import (
    Alerta,
    Aprendiz,
    ConfiguracionRanking,
    Ficha,
    Instructor,
    RegistroAsistencia,
    SesionAsistencia,
)
from app.models.aseo import ContadorAseo
from app.services.alertas import actualizar_alertas_ficha
from app.services.aseo import aprendices_activos, asegurar_contadores
from app.services.ranking import calcular_ranking


class FiltroEnFormacionTestCase(unittest.TestCase):
    """Solo los aprendices en formación entran a lista, aseo y ranking."""

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

        self.instructor = Instructor(
            nombre='Instructor Prueba',
            correo='pruebas@sena.edu.co',
            rol='admin',
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='2888888',
            nombre_programa='Análisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
        )
        db.session.add(self.ficha)
        db.session.flush()

        self.activo = Aprendiz(
            documento='2001',
            nombre='Ana',
            apellidos='Ávila',
            estado='EN_FORMACION',
            ficha_id=self.ficha.id,
        )
        self.retirado = Aprendiz(
            documento='2002',
            nombre='Bruno',
            apellidos='Bello',
            estado='RETIRO_VOLUNTARIO',
            ficha_id=self.ficha.id,
        )
        self.cancelado = Aprendiz(
            documento='2003',
            nombre='Carla',
            apellidos='Cano',
            estado='CANCELADO',
            ficha_id=self.ficha.id,
        )
        self.condicionado = Aprendiz(
            documento='2004',
            nombre='Dino',
            apellidos='Duarte',
            estado='CONDICIONADO',
            ficha_id=self.ficha.id,
        )
        db.session.add_all([self.activo, self.retirado, self.cancelado, self.condicionado])
        db.session.add(ConfiguracionRanking(ficha_id=self.ficha.id))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _cliente_autenticado(self):
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True
        return cliente

    def test_llamado_a_lista_incluye_en_formacion_y_condicionados(self):
        respuesta = self._cliente_autenticado().get(
            f'/instructor/fichas/{self.ficha.id}/asistencia'
        )
        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.get_data(as_text=True)
        self.assertIn(f'asistencia_{self.activo.id}', cuerpo)
        self.assertIn(f'asistencia_{self.condicionado.id}', cuerpo)
        self.assertNotIn(f'asistencia_{self.retirado.id}', cuerpo)
        self.assertNotIn(f'asistencia_{self.cancelado.id}', cuerpo)

    def test_llamado_a_lista_muestra_el_estado_de_cada_aprendiz(self):
        respuesta = self._cliente_autenticado().get(
            f'/instructor/fichas/{self.ficha.id}/asistencia'
        )
        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.get_data(as_text=True)
        self.assertIn('estado-mini">En formación', cuerpo)
        self.assertIn('estado-mini">Condicionado', cuerpo)

    def test_turnos_de_aseo_ignoran_a_quienes_no_estan_en_formacion(self):
        activos = aprendices_activos(self.ficha.id)
        self.assertEqual([ap.id for ap in activos], [self.activo.id])

        asegurar_contadores(self.ficha.id)
        db.session.commit()
        contadores = ContadorAseo.query.filter_by(ficha_id=self.ficha.id).all()
        self.assertEqual([c.aprendiz_id for c in contadores], [self.activo.id])

    def test_ranking_solo_incluye_aprendices_en_formacion(self):
        filas, _ = calcular_ranking(self.ficha.id)
        self.assertEqual([fila['aprendiz'].id for fila in filas], [self.activo.id])

    def test_alertas_no_se_generan_para_quienes_salieron_de_formacion(self):
        sesion = SesionAsistencia(ficha_id=self.ficha.id, fecha=date.today())
        db.session.add(sesion)
        db.session.flush()
        for aprendiz in (self.activo, self.retirado, self.cancelado):
            db.session.add(RegistroAsistencia(
                sesion_id=sesion.id,
                aprendiz_id=aprendiz.id,
                estado='FALTA',
            ))
        db.session.commit()

        actualizar_alertas_ficha(self.ficha.id)
        db.session.commit()
        con_alerta = {
            alerta.aprendiz_id
            for alerta in Alerta.query.filter_by(ficha_id=self.ficha.id).all()
            if alerta.aprendiz_id
        }
        self.assertNotIn(self.retirado.id, con_alerta)
        self.assertNotIn(self.cancelado.id, con_alerta)

    def test_paginas_y_reportes_solo_listan_a_quienes_estan_en_formacion(self):
        cliente = self._cliente_autenticado()
        rutas = (
            f'/instructor/fichas/{self.ficha.id}/alertas',
            f'/instructor/fichas/{self.ficha.id}/insignias',
            f'/instructor/fichas/{self.ficha.id}/ranking',
        )
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                respuesta = cliente.get(ruta)
                self.assertEqual(respuesta.status_code, 200)
                cuerpo = respuesta.get_data(as_text=True)
                self.assertIn(self.activo.apellidos, cuerpo)
                self.assertNotIn(self.retirado.apellidos, cuerpo)
                self.assertNotIn(self.cancelado.apellidos, cuerpo)

    def test_resumen_api_cuenta_solo_aprendices_en_formacion(self):
        respuesta = self._cliente_autenticado().get(
            f'/api/fichas/{self.ficha.id}/resumen'
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.get_json()['total_aprendices'], 1)

    def test_gestion_de_aprendices_sigue_mostrando_todos_los_estados(self):
        respuesta = self._cliente_autenticado().get(
            f'/instructor/fichas/{self.ficha.id}/aprendices'
        )
        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.get_data(as_text=True)
        for aprendiz in (self.activo, self.retirado, self.cancelado, self.condicionado):
            self.assertIn(aprendiz.apellidos, cuerpo)

    def test_aprendices_condicionados_aparecen_con_su_estado(self):
        respuesta = self._cliente_autenticado().get(
            f'/instructor/fichas/{self.ficha.id}/aprendices'
        )
        cuerpo = respuesta.get_data(as_text=True)
        self.assertIn(self.condicionado.apellidos, cuerpo)
        self.assertIn('Condicionado', cuerpo)

    def test_filtro_por_estado_muestra_solo_ese_estado(self):
        respuesta = self._cliente_autenticado().get(
            f'/instructor/fichas/{self.ficha.id}/aprendices?estado=CONDICIONADO'
        )
        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.get_data(as_text=True)
        self.assertIn(self.condicionado.apellidos, cuerpo)
        for otro in (self.activo, self.retirado, self.cancelado):
            self.assertNotIn(otro.apellidos, cuerpo)

    def test_filtro_ofrece_todos_los_estados_con_conteos(self):
        respuesta = self._cliente_autenticado().get(
            f'/instructor/fichas/{self.ficha.id}/aprendices'
        )
        cuerpo = respuesta.get_data(as_text=True)
        self.assertIn('Todos los estados <span class="chip-count">4</span>', cuerpo)
        self.assertIn('En formación <span class="chip-count">1</span>', cuerpo)
        self.assertIn('Condicionado <span class="chip-count">1</span>', cuerpo)
        self.assertIn('Retiro voluntario <span class="chip-count">1</span>', cuerpo)
        self.assertIn('Cancelado <span class="chip-count">1</span>', cuerpo)


if __name__ == '__main__':
    unittest.main()
