import unittest
from datetime import date, datetime, timedelta

from app import create_app, db
from app.models import (
    Alerta,
    Aprendiz,
    ConfiguracionRanking,
    Corte,
    Entrega,
    Ficha,
    Insignia,
    InsigniaOtorgada,
    Instructor,
    JuicioEvaluativo,
    NotaObservador,
    ProrrogaTarea,
    PuntajeHistorico,
    RegistroAsistencia,
    SesionAsistencia,
    Tarea,
    TurnoAseo,
)
from app.services.ranking import actualizar_participacion_ficha, calcular_ranking


class RankingTestCase(unittest.TestCase):
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
            codigo='2999999',
            nombre_programa='Análisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
        )
        db.session.add(self.ficha)
        db.session.flush()
        self.ana = Aprendiz(
            documento='1001',
            nombre='Ana',
            apellidos='Ávila',
            ficha_id=self.ficha.id,
        )
        self.bruno = Aprendiz(
            documento='1002',
            nombre='Bruno',
            apellidos='Bello',
            ficha_id=self.ficha.id,
        )
        db.session.add_all([self.ana, self.bruno])
        db.session.add(ConfiguracionRanking(ficha_id=self.ficha.id))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _sesion(self, dias_atras, estados):
        sesion = SesionAsistencia(
            ficha_id=self.ficha.id,
            fecha=date.today() - timedelta(days=dias_atras),
        )
        db.session.add(sesion)
        db.session.flush()
        for aprendiz, estado in estados:
            db.session.add(RegistroAsistencia(
                sesion_id=sesion.id,
                aprendiz_id=aprendiz.id,
                estado=estado,
            ))

    def test_falla_justificada_no_baja_porcentaje_ni_penaliza(self):
        self._sesion(2, [(self.ana, 'ASISTE'), (self.bruno, 'ASISTE')])
        self._sesion(1, [(self.ana, 'FALTA_JUSTIFICADA'), (self.bruno, 'ASISTE')])
        self._sesion(0, [(self.ana, 'FALTA'), (self.bruno, 'ASISTE')])
        db.session.commit()

        filas, _ = calcular_ranking(self.ficha.id)
        por_id = {fila['aprendiz'].id: fila for fila in filas}

        self.assertEqual(por_id[self.ana.id]['porcentaje_asistencia'], 50.0)
        self.assertEqual(por_id[self.ana.id]['penalizacion'], 1.0)
        self.assertEqual(por_id[self.bruno.id]['porcentaje_asistencia'], 100.0)
        self.assertEqual(por_id[self.bruno.id]['penalizacion'], 0.0)

    def test_sin_actividad_el_puntaje_inicia_en_cero(self):
        filas, _ = calcular_ranking(self.ficha.id)
        self.assertTrue(all(fila['puntaje_total'] == 0 for fila in filas))

    def test_entregas_tempranas_otorgan_logros_permanentes(self):
        for numero in range(5):
            tarea = Tarea(
                ficha_id=self.ficha.id,
                instructor_id=self.instructor.id,
                titulo=f'Actividad {numero + 1}',
                fecha_limite=datetime.utcnow() + timedelta(days=numero + 2),
            )
            db.session.add(tarea)
            db.session.flush()
            db.session.add(Entrega(
                tarea_id=tarea.id,
                aprendiz_id=self.ana.id,
                fecha_entrega=datetime.utcnow(),
            ))
        db.session.commit()

        actualizar_participacion_ficha(self.ficha.id)
        nombres = {
            otorgamiento.insignia.nombre
            for otorgamiento in InsigniaOtorgada.query.filter_by(
                aprendiz_id=self.ana.id
            ).all()
        }
        self.assertIn('Primero en Entregar', nombres)
        self.assertIn('Nunca Tarde', nombres)
        self.assertEqual(PuntajeHistorico.query.count(), 2)

        # Recalcular no quita ni duplica los logros.
        actualizar_participacion_ficha(self.ficha.id)
        self.assertEqual(
            InsigniaOtorgada.query.filter_by(aprendiz_id=self.ana.id).count(),
            len(nombres),
        )

    def test_paginas_y_exportaciones_responden(self):
        actualizar_participacion_ficha(self.ficha.id)
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True

        rutas = (
            f'/instructor/fichas/{self.ficha.id}/ranking',
            f'/instructor/fichas/{self.ficha.id}/insignias',
            f'/instructor/fichas/{self.ficha.id}/ranking/exportar?formato=excel',
            f'/instructor/fichas/{self.ficha.id}/ranking/exportar?formato=pdf',
            f'/instructor/fichas/{self.ficha.id}/insignias/exportar?formato=excel',
            f'/instructor/fichas/{self.ficha.id}/insignias/exportar?formato=pdf',
            f'/aprendiz/{self.ficha.id}/panel?documento={self.ana.documento}',
        )
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(cliente.get(ruta, follow_redirects=True).status_code, 200)

        self.assertEqual(Insignia.query.filter_by(ficha_id=self.ficha.id).count(), 9)

    def test_ranking_expone_estructura_mobile_first_accesible(self):
        actualizar_participacion_ficha(self.ficha.id)
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True

        respuesta = cliente.get(
            f'/instructor/fichas/{self.ficha.id}/ranking',
            follow_redirects=True,
        )
        contenido = respuesta.get_data(as_text=True)

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('css/ranking.css', contenido)
        self.assertIn(
            'class="ranking-overview-card ranking-overview-period"',
            contenido,
        )
        self.assertIn('class="ranking-podium-grid" tabindex="0"', contenido)
        self.assertIn('id="ranking-loading"', contenido)
        self.assertIn('id="ranking-error"', contenido)
        self.assertLess(
            contenido.index('class="ranking-detail-heading"'),
            contenido.index('class="ranking-mobile"'),
        )
        self.assertNotIn('style="max-width: 480px;"', contenido)

    def test_prorroga_tarea_se_respeta_en_ranking(self):
        # Tarea vencida ayer
        tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo='Actividad Especial',
            fecha_limite=datetime.utcnow() - timedelta(days=1),
        )
        db.session.add(tarea)
        db.session.flush()

        # Ana recibe prórroga hasta mañana y entrega hoy
        db.session.add(ProrrogaTarea(
            tarea_id=tarea.id,
            aprendiz_id=self.ana.id,
            instructor_id=self.instructor.id,
            nueva_fecha_limite=datetime.utcnow() + timedelta(days=1),
        ))
        db.session.add(Entrega(
            tarea_id=tarea.id,
            aprendiz_id=self.ana.id,
            fecha_entrega=datetime.utcnow(),
            estado_revision='aprobada',
        ))
        # Bruno entrega tarde sin prórroga
        db.session.add(Entrega(
            tarea_id=tarea.id,
            aprendiz_id=self.bruno.id,
            fecha_entrega=datetime.utcnow(),
            estado_revision='aprobada',
        ))
        db.session.commit()

        filas, _ = calcular_ranking(self.ficha.id)
        por_id = {f['aprendiz'].id: f for f in filas}

        # Ana entregó a tiempo gracias a su prórroga
        self.assertEqual(por_id[self.ana.id]['entregadas_a_tiempo'], 1)
        self.assertEqual(por_id[self.ana.id]['porcentaje_evidencias'], 100.0)
        # Bruno entregó con retraso pero aprobada -> recibe crédito parcial del 75%
        self.assertEqual(por_id[self.bruno.id]['entregadas_a_tiempo'], 0)
        self.assertEqual(por_id[self.bruno.id]['porcentaje_evidencias'], 75.0)

    def test_tardanzas_se_ponderan_justamente(self):
        # 1 sesión asistida puntual, 1 sesión con tardanza
        self._sesion(1, [(self.ana, 'ASISTE'), (self.bruno, 'ASISTE')])
        self._sesion(0, [(self.ana, 'TARDANZA'), (self.bruno, 'ASISTE')])
        db.session.commit()

        filas, _ = calcular_ranking(self.ficha.id)
        por_id = {f['aprendiz'].id: f for f in filas}

        # Bruno: 2 puntuales = 100%
        self.assertEqual(por_id[self.bruno.id]['porcentaje_asistencia'], 100.0)
        # Ana: (1.0 + 0.8) / 2 = 90.0%
        self.assertEqual(por_id[self.ana.id]['porcentaje_asistencia'], 90.0)
        self.assertEqual(por_id[self.ana.id]['tardanzas'], 1)

    def test_rebalanceo_dinamico_corte_sin_tareas(self):
        corte_vacio = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            nombre='Corte Inicial Vacío',
            fecha_inicio=datetime.utcnow(),
        )
        db.session.add(corte_vacio)
        db.session.flush()

        # Juicios evaluativos en la ficha
        db.session.add(JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=self.ana.id,
            competencia='Competencia 1',
            juicio='APROBADO',
            huella='H1',
        ))
        db.session.add(JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=self.bruno.id,
            competencia='Competencia 1',
            juicio='POR EVALUAR',
            huella='H2',
        ))
        db.session.commit()

        filas, cfg = calcular_ranking(self.ficha.id, corte_id=corte_vacio.id)
        por_id = {f['aprendiz'].id: f for f in filas}

        self.assertTrue(getattr(cfg, 'fase_inicial', False))
        # En fase inicial sin tareas ni sesiones, los juicios evaluativos son el 100% de la base académica
        self.assertEqual(por_id[self.ana.id]['porcentaje_aprobados'], 100.0)
        self.assertEqual(por_id[self.ana.id]['puntaje_total'], 100.0)
        self.assertEqual(por_id[self.bruno.id]['porcentaje_aprobados'], 0.0)
        self.assertEqual(por_id[self.bruno.id]['puntaje_total'], 0.0)

    def test_merito_formativo_aseo_y_observador(self):
        # Ana cumple un turno de aseo y tiene una nota positiva en el observador
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=date.today(),
            aprendiz_1_id=self.ana.id,
            aprendiz_2_id=self.bruno.id,
            estado='cumplido',
            completado_1=True,
            completado_2=False,
        )
        db.session.add(turno)
        db.session.add(NotaObservador(
            ficha_id=self.ficha.id,
            aprendiz_id=self.ana.id,
            instructor_id=self.instructor.id,
            tipo='positiva',
            categoria='compromiso',
            descripcion='Excelente trabajo en equipo y liderazgo.',
            fecha=date.today(),
        ))
        db.session.commit()

        filas, _ = calcular_ranking(self.ficha.id)
        por_id = {f['aprendiz'].id: f for f in filas}

        # Aseo cumplido (1.5) + Reconocimiento (2.0) = 3.5 puntos de mérito
        self.assertGreater(por_id[self.ana.id]['merito_formativo'], 3.0)
        self.assertEqual(por_id[self.ana.id]['turnos_aseo_cumplidos'], 1)
        self.assertEqual(por_id[self.ana.id]['reconocimientos'], 1)

    def test_corte_id_se_preserva_en_htmx(self):
        corte = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            nombre='Corte 2026',
            fecha_inicio=datetime.utcnow(),
        )
        db.session.add(corte)
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True

        res = cliente.get(f'/instructor/fichas/{self.ficha.id}/ranking?corte_id={corte.id}')
        html = res.get_data(as_text=True)

        self.assertEqual(res.status_code, 200)
        # Verifica que las URLs de htmx incluyan corte_id
        self.assertIn(f'corte_id={corte.id}', html)


if __name__ == '__main__':
    unittest.main()
