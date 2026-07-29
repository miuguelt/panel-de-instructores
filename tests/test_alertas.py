import unittest
from datetime import date, datetime, timedelta

from app import create_app, db
from app.models import (
    Alerta,
    Aprendiz,
    ConfiguracionAlertasComite,
    Ficha,
    Instructor,
    NotaObservador,
    Notificacion,
    PlanMejoramiento,
    RegistroAsistencia,
    SesionAsistencia,
    Tarea,
)
from app.services.alertas import (
    actualizar_alertas_ficha,
    crear_plan_mejoramiento,
    cumplir_plan_mejoramiento,
    ejecutar_revision_automatica,
    auto_escalar_casos_pendientes,
    vencer_planes_pendientes,
    _porcentaje_asistencia,
)


class AlertasTestCase(unittest.TestCase):
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
        self.instructor = Instructor(nombre='Instructor', correo='i@sena.edu.co', rol='admin')
        self.instructor.set_password('clave')
        db.session.add(self.instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='F1', nombre_programa='ADSO', instructor_id=self.instructor.id)
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendiz = Aprendiz(documento='1', nombre='Ana', apellidos='Prueba', ficha_id=self.ficha.id)
        db.session.add(self.aprendiz)
        db.session.add(ConfiguracionAlertasComite(
            ficha_id=self.ficha.id,
            umbral_fallas_consecutivas=3,
            umbral_fallas_acumuladas=5,
            umbral_tareas_incumplidas=2,
        ))
        for dias in (2, 1, 0):
            sesion = SesionAsistencia(
                ficha_id=self.ficha.id,
                fecha=date.today() - timedelta(days=dias),
            )
            db.session.add(sesion)
            db.session.flush()
            db.session.add(RegistroAsistencia(
                sesion_id=sesion.id,
                aprendiz_id=self.aprendiz.id,
                estado='FALTA',
            ))
        for numero in range(2):
            db.session.add(Tarea(
                ficha_id=self.ficha.id,
                instructor_id=self.instructor.id,
                titulo=f'Tarea {numero}',
                fecha_limite=datetime.utcnow() - timedelta(days=1),
            ))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    # ── Tests existentes actualizados ──

    def test_alerta_y_notificacion_se_generan_sin_escalamiento_automatico(self):
        actualizar_alertas_ficha(self.ficha.id)
        alertas = Alerta.query.filter_by(ficha_id=self.ficha.id, estado='activa').all()
        tipos = {alerta.tipo for alerta in alertas}
        # 3 consecutivas + 0% asistencia = comite_desercion, 2 tareas incumplidas = academica
        self.assertIn('comite_desercion', tipos)
        self.assertIn('academica', tipos)
        self.assertTrue(all(alerta.estado == 'activa' for alerta in alertas))
        self.assertEqual(Notificacion.query.count(), 4)

        actualizar_alertas_ficha(self.ficha.id)
        self.assertEqual(Notificacion.query.count(), 4)

    def test_paneles_y_borrador_comite_responden(self):
        actualizar_alertas_ficha(self.ficha.id)
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True
        rutas = (
            f'/instructor/fichas/{self.ficha.id}/casos-seguimiento',
            '/instructor/notificaciones',
            f'/instructor/fichas/{self.ficha.id}/casos/{self.aprendiz.id}/reporte-comite',
            f'/aprendiz/{self.ficha.id}/panel?documento={self.aprendiz.documento}',
            f'/aprendiz/{self.ficha.id}/notificaciones?documento={self.aprendiz.documento}',
        )
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(cliente.get(ruta).status_code, 200)

        registro = RegistroAsistencia.query.join(SesionAsistencia).filter(
            RegistroAsistencia.aprendiz_id == self.aprendiz.id,
            SesionAsistencia.ficha_id == self.ficha.id,
        ).first()
        respuesta = cliente.post(
            f'/aprendiz/{self.ficha.id}/justificar/{registro.id}',
            data={'documento': self.aprendiz.documento, 'nota': 'Presento soporte para revisión.'},
            follow_redirects=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(registro.nota, 'Presento soporte para revisión.')

    # ── Formación integral: bitácora del observador ──

    def _nota_negativa(self, dias_atras, texto='Interrumpió la sesión.'):
        nota = NotaObservador(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            instructor_id=self.instructor.id,
            tipo='negativa',
            categoria='convivencia',
            descripcion=texto,
            fecha=date.today() - timedelta(days=dias_atras),
        )
        db.session.add(nota)
        db.session.commit()
        return nota

    def _alerta_observador(self):
        return Alerta.query.filter_by(
            ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id, tipo='observador',
        ).first()

    def test_llamados_de_atencion_abren_caso_al_llegar_al_umbral(self):
        config = ConfiguracionAlertasComite.query.filter_by(ficha_id=self.ficha.id).one()
        config.umbral_notas_negativas = 3
        config.periodo_dias_notas = 30
        db.session.commit()

        # Fuera de la ventana y de tipo positivo: no deben contar.
        self._nota_negativa(60, 'Llamado antiguo, fuera de la ventana.')
        db.session.add(NotaObservador(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            instructor_id=self.instructor.id,
            tipo='positiva',
            categoria='trabajo_equipo',
            descripcion='Apoyó a sus compañeros.',
            fecha=date.today(),
        ))
        self._nota_negativa(1)
        self._nota_negativa(2)
        actualizar_alertas_ficha(self.ficha.id)
        self.assertIsNone(self._alerta_observador())

        tercera = self._nota_negativa(3)
        actualizar_alertas_ficha(self.ficha.id)
        alerta = self._alerta_observador()
        self.assertIsNotNone(alerta)
        self.assertEqual(alerta.estado, 'activa')
        self.assertEqual(alerta.nivel, 'amarilla')
        self.assertEqual(alerta.detalle_json['notas_negativas'], 3)
        self.assertEqual(alerta.detalle_json['periodo_dias'], 30)

        # Al caer por debajo del umbral el caso se cierra solo.
        db.session.delete(tercera)
        db.session.commit()
        actualizar_alertas_ficha(self.ficha.id)
        db.session.refresh(alerta)
        self.assertEqual(alerta.estado, 'resuelta')
        self.assertIsNotNone(alerta.fecha_resuelta)

    def test_umbral_en_cero_desactiva_la_regla_del_observador(self):
        config = ConfiguracionAlertasComite.query.filter_by(ficha_id=self.ficha.id).one()
        config.umbral_notas_negativas = 0
        db.session.commit()
        for dias in (1, 2, 3, 4):
            self._nota_negativa(dias)

        actualizar_alertas_ficha(self.ficha.id)
        self.assertIsNone(self._alerta_observador())

    # ── Nuevos tests: Reglamento 009 ──

    def test_porcentaje_asistencia_se_calcula_correctamente(self):
        pct = _porcentaje_asistencia(self.aprendiz.id, self.ficha.id)
        # 3 sesiones, 3 faltas = 0% asistencia
        self.assertEqual(pct, 0.0)

    def test_regla_porcentaje_asistencia_genera_comite(self):
        actualizar_alertas_ficha(self.ficha.id)
        comite_alertas = Alerta.query.filter_by(
            ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id,
            tipo='comite_desercion',
        ).all()
        self.assertGreater(len(comite_alertas), 0)

    def test_auto_escalacion_tras_dias_sin_resolver(self):
        pasado = datetime.utcnow() - timedelta(days=20)
        alerta = Alerta(
            ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id,
            tipo='asistencia', nivel='amarilla', titulo='Test',
            mensaje='Test', fecha_generada=pasado,
        )
        db.session.add(alerta)
        db.session.commit()
        config = ConfiguracionAlertasComite.query.filter_by(ficha_id=self.ficha.id).first()
        config.auto_escalar_dias = 15
        db.session.commit()
        auto_escalar_casos_pendientes(self.ficha.id)
        db.session.refresh(alerta)
        self.assertEqual(alerta.estado, 'escalada_comite')
        self.assertTrue(alerta.auto_escalada)

    def test_plan_mejoramiento_crear_y_cumplir(self):
        plan = crear_plan_mejoramiento(
            self.aprendiz.id, self.ficha.id, self.instructor.id,
            'Presentar las evidencias pendientes.',
            fecha_limite=datetime.utcnow() + timedelta(days=15),
        )
        self.assertIsNotNone(plan.id)
        self.assertEqual(plan.estado, 'pendiente')
        plan_cumplido = cumplir_plan_mejoramiento(plan.id)
        self.assertEqual(plan_cumplido.estado, 'cumplido')

    def test_vencer_planes_expirados(self):
        plan = crear_plan_mejoramiento(
            self.aprendiz.id, self.ficha.id, self.instructor.id,
            'Entregar tareas.',
            fecha_limite=datetime.utcnow() - timedelta(days=1),
        )
        vencidos = vencer_planes_pendientes()
        self.assertEqual(vencidos, 1)
        db.session.refresh(plan)
        self.assertEqual(plan.estado, 'vencido')

    def test_ejecutar_revision_automatica_corres_sin_error(self):
        evaluadas = ejecutar_revision_automatica()
        self.assertGreaterEqual(evaluadas, 1)

    def test_comite_alertas_se_crean_por_reglamento(self):
        actualizar_alertas_ficha(self.ficha.id)
        alertas = Alerta.query.filter_by(
            ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id
        ).all()
        tipos = {a.tipo for a in alertas}
        # 3 consecutivas + 0% asistencia = comite_desercion, 2 tareas = academica
        self.assertIn('comite_desercion', tipos)
        self.assertIn('academica', tipos)


if __name__ == '__main__':
    unittest.main()
