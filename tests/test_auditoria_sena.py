"""Correcciones de la auditoría SENA de noviembre de 2026.

Cada prueba fija una corrección del informe `docs/auditoria/AUDITORIA_SENA_2026-11.md`.
Los casos son de práctica y no contienen registros reales.
"""

import secrets
import unittest
from datetime import date, datetime, timedelta

from flask import g

from app import create_app, db
from app.models import (
    Alerta, Aprendiz, Ficha, Instructor, Notificacion, RegistroAsistencia, SesionAsistencia,
)
from app.models.alertas import ConfiguracionAlertasComite, LlamadoAtencion, PlanMejoramiento
from app.models.novedades import NovedadAprendiz
from app.models.observador import NotaObservador
from app.services import debido_proceso as dp
from app.services import novedades as nv
from app.services.alertas import (
    actualizar_alertas_ficha, crear_plan_mejoramiento, fecha_colombia,
    plazo_justificacion_efectivo,
)
from app.services.asistencia import construir_calendario_mes
from app.services.permisos import aprendiz_puede_escribir


class BaseAuditoria(unittest.TestCase):
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
        self.instructor = Instructor(nombre='Instructora', correo='auditoria@sena.edu.co', rol='admin')
        self.instructor.set_password(secrets.token_urlsafe(16))
        db.session.add(self.instructor)
        db.session.flush()
        hoy = date.today()
        self.ficha = Ficha(codigo='AUD1', nombre_programa='ADSO', instructor_id=self.instructor.id,
                           fecha_inicio=hoy - timedelta(days=200), fecha_fin=hoy + timedelta(days=400))
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendiz = Aprendiz(documento='5001', nombre='Ana', apellidos='Prueba',
                                 ficha_id=self.ficha.id, estado='EN_FORMACION')
        self.otro = Aprendiz(documento='5002', nombre='Luis', apellidos='Prueba',
                             ficha_id=self.ficha.id, estado='EN_FORMACION')
        db.session.add_all([self.aprendiz, self.otro])
        db.session.commit()
        self.cliente = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _registro(self, aprendiz, dias_atras, estado):
        fecha = date.today() - timedelta(days=dias_atras)
        sesion = SesionAsistencia.query.filter_by(ficha_id=self.ficha.id, fecha=fecha).first()
        if not sesion:
            sesion = SesionAsistencia(ficha_id=self.ficha.id, fecha=fecha)
            db.session.add(sesion)
            db.session.flush()
        db.session.add(RegistroAsistencia(sesion_id=sesion.id, aprendiz_id=aprendiz.id, estado=estado))
        db.session.commit()

    def _como_instructor(self):
        g.pop('_login_user', None)
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True

    def _como_aprendiz(self, aprendiz):
        with self.cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = aprendiz.documento
            sesion['aprendiz_ficha_id'] = self.ficha.id

    def _llamado(self, **campos):
        datos = dict(tipo='academico', descripcion='No entregó la evidencia.', fase='analisis')
        datos.update(campos)
        return dp.registrar_llamado(self.aprendiz, self.ficha, datos.pop('tipo'), datos.pop('descripcion'),
                                    instructor_id=self.instructor.id, **datos)


class AlertasTest(BaseAuditoria):
    def test_fecha_colombia_usa_utc_menos_cinco(self):
        self.assertEqual(fecha_colombia(datetime(2026, 11, 10, 2, 30)), date(2026, 11, 9))
        self.assertEqual(fecha_colombia(datetime(2026, 11, 10, 6, 0)), date(2026, 11, 10))
        self.assertEqual(fecha_colombia(date(2026, 1, 1)), date(2026, 1, 1))

    def test_plazo_de_justificacion_nunca_baja_de_cinco_dias(self):
        config = ConfiguracionAlertasComite(ficha_id=self.ficha.id, dias_plazo_justificacion=2)
        self.assertEqual(plazo_justificacion_efectivo(config), 5)
        config.dias_plazo_justificacion = 8
        self.assertEqual(plazo_justificacion_efectivo(config), 8)

    def test_formulario_no_permite_reducir_el_plazo(self):
        self._como_instructor()
        self.cliente.post(f'/instructor/fichas/{self.ficha.id}/alertas/config-comite', data={
            'umbral_fallas_consecutivas': 3, 'umbral_fallas_acumuladas': 5,
            'umbral_tareas_incumplidas': 3, 'dias_plazo_justificacion': 1,
            'porcentaje_minimo_asistencia': 75, 'auto_escalar_dias': 15,
            'umbral_notas_negativas': 3, 'periodo_dias_notas': 30,
        })
        config = ConfiguracionAlertasComite.query.filter_by(ficha_id=self.ficha.id).one()
        self.assertEqual(config.dias_plazo_justificacion, 5)

    def test_faltas_recientes_no_abren_causal_hasta_vencer_el_plazo(self):
        for dias in (2, 1, 0):
            self._registro(self.aprendiz, dias, 'FALTA')
        actualizar_alertas_ficha(self.ficha.id)
        self.assertEqual(Alerta.query.filter_by(tipo='comite_desercion').count(), 0)

    def test_cinco_faltas_en_noventa_dias_ya_no_usan_ventana(self):
        # Antes existía la regla R2 con ventana de 90 días; ahora se mira todo el proceso (R3).
        faltas = (60, 50, 40, 30, 20)
        for dias in range(15, 100):
            self._registro(self.aprendiz, dias, 'FALTA' if dias in faltas else 'ASISTE')
        actualizar_alertas_ficha(self.ficha.id)
        alerta = Alerta.query.filter_by(tipo='comite_desercion').one()
        self.assertEqual(alerta.detalle_json['motivo'], 'acumuladas_proceso')

    def test_recomendacion_del_aprendiz_no_cuenta_excusas_como_faltas(self):
        from app.services.recomendaciones import obtener_recomendaciones_aprendiz
        for dias in range(1, 11):
            self._registro(self.aprendiz, dias, 'ASISTE')
        for dias in (11, 12, 13):
            self._registro(self.aprendiz, dias, 'EXCUSA_MEDICA')
        recomendaciones = obtener_recomendaciones_aprendiz(self.ficha.id, self.aprendiz.id)
        self.assertFalse(any('asistencia_riesgo' in r.id for r in recomendaciones))

    def test_tooltip_del_calendario_muestra_la_causal(self):
        mapa = {'2026-03-05': {'estado': 'FALTA_JUSTIFICADA', 'etiqueta': 'Falta justificada',
                               'clase': 'justificada', 'causal_justificacion': 'Cita médica'}}
        calendario = construir_calendario_mes(mapa, 2026, 3)
        celdas = [c for c in calendario['celdas'] if c.get('iso') == '2026-03-05']
        self.assertTrue(celdas)
        self.assertIn('Cita médica', celdas[0]['titulo'])
        self.assertIn('05/03/2026', celdas[0]['titulo'])

    def test_resolver_caso_escalado_exige_acta(self):
        alerta = Alerta(ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id, tipo='comite_desercion',
                        nivel='roja', titulo='Caso', mensaje='Caso', estado='escalada_comite',
                        fecha_escalada=datetime.utcnow())
        db.session.add(alerta)
        db.session.commit()
        self._como_instructor()
        url = f'/instructor/fichas/{self.ficha.id}/alertas/{alerta.id}/resolver'
        self.cliente.post(url, data={})
        db.session.refresh(alerta)
        self.assertEqual(alerta.estado, 'escalada_comite')
        self.cliente.post(url, data={'acta_comite': 'ACTA-12'})
        db.session.refresh(alerta)
        self.assertEqual(alerta.estado, 'resuelta')
        self.assertIn('ACTA-12', alerta.observaciones)


class DebidoProcesoTest(BaseAuditoria):
    def test_plan_de_mas_de_veinte_dias_no_se_crea(self):
        with self.assertRaises(ValueError):
            crear_plan_mejoramiento(self.aprendiz.id, self.ficha.id, self.instructor.id, 'Actividad',
                                    fecha_limite=datetime.utcnow() + timedelta(days=21))
        self.assertEqual(PlanMejoramiento.query.count(), 0)

    def test_plan_guarda_fase_y_advierte_por_fase(self):
        plan = crear_plan_mejoramiento(self.aprendiz.id, self.ficha.id, self.instructor.id, 'Actividad',
                                       fecha_limite=datetime.utcnow() + timedelta(days=10), fase='analisis')
        self.assertEqual(plan.fase, 'analisis')
        self.assertTrue(any('fase de análisis' in a for a in plan.advertencias))
        errores, _ = dp.validar_plan(self.aprendiz.id, self.ficha, datetime.utcnow(),
                                     datetime.utcnow() + timedelta(days=5), fase='otra')
        self.assertTrue(errores)

    def test_llamados_de_otra_fase_no_cuentan_para_el_plan(self):
        self._llamado(fase='planeacion')
        self._llamado(fase='planeacion', orientaciones='Revisa la guía.')
        _, advertencias = dp.validar_plan(self.aprendiz.id, self.ficha, datetime.utcnow(),
                                          datetime.utcnow() + timedelta(days=5), fase='analisis')
        self.assertTrue(any('0 llamado' in a for a in advertencias))
        _, advertencias = dp.validar_plan(self.aprendiz.id, self.ficha, datetime.utcnow(),
                                          datetime.utcnow() + timedelta(days=5), fase='planeacion')
        self.assertFalse(any('llamado(s) académico' in a for a in advertencias))

    def test_llamado_no_admite_fecha_futura(self):
        with self.assertRaises(dp.ReglaDebidoProceso):
            self._llamado(fecha=date.today() + timedelta(days=1))

    def test_llamado_anulado_no_cuenta_para_el_tope(self):
        primero = self._llamado()
        segundo = self._llamado(orientaciones='Revisa la guía.')
        with self.assertRaises(dp.ReglaDebidoProceso):
            self._llamado(orientaciones='Otra vez.')
        with self.assertRaises(dp.ReglaDebidoProceso):
            dp.anular_llamado(primero, '  ')
        dp.anular_llamado(primero, 'Se registró en la ficha equivocada.', self.instructor.id)
        self.assertFalse(primero.vigente)
        with self.assertRaises(dp.ReglaDebidoProceso):
            dp.anular_llamado(primero, 'Repetido.')
        tercero = self._llamado(orientaciones='Nuevo compromiso.')
        self.assertEqual(tercero.numero, 2)
        self.assertTrue(segundo.vigente)
        self.assertTrue(Notificacion.query.filter_by(clave=f'llamado-anulado:{primero.id}').first())

    def test_aprendiz_presenta_descargos_desde_su_panel(self):
        llamado = self._llamado()
        self._como_aprendiz(self.aprendiz)
        url = f'/aprendiz/{self.ficha.id}/llamados/{llamado.id}/descargos'
        self.cliente.post(url, data={'descargos': ''})
        db.session.refresh(llamado)
        self.assertIsNone(llamado.descargos)
        self.cliente.post(url, data={'descargos': 'La entregué por correo el lunes.'})
        db.session.refresh(llamado)
        self.assertEqual(llamado.descargos, 'La entregué por correo el lunes.')
        self.assertIsNotNone(llamado.descargos_en)
        panel = self.cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertIn('La entregué por correo el lunes.'.encode(), panel.data)

    def test_otro_aprendiz_no_puede_presentar_descargos_ajenos(self):
        llamado = self._llamado()
        self._como_aprendiz(self.otro)
        self.cliente.post(f'/aprendiz/{self.ficha.id}/llamados/{llamado.id}/descargos',
                          data={'descargos': 'Suplantación.'})
        db.session.refresh(llamado)
        self.assertIsNone(llamado.descargos)

    def test_descargos_sobre_llamado_anulado_se_rechazan(self):
        llamado = self._llamado()
        dp.anular_llamado(llamado, 'Error de registro.')
        with self.assertRaises(dp.ReglaDebidoProceso):
            dp.registrar_descargos(llamado, 'Mi versión.')

    def test_instructor_anula_llamado_desde_el_caso(self):
        llamado = self._llamado()
        self._como_instructor()
        self.cliente.post(f'/instructor/fichas/{self.ficha.id}/llamados/{llamado.id}/anular',
                          data={'motivo': 'Registrado por error.'})
        db.session.refresh(llamado)
        self.assertIsNotNone(llamado.anulado_en)
        self.assertEqual(llamado.anulado_por, self.instructor.id)

    def test_expediente_toma_fecha_de_remision(self):
        alerta = Alerta(ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id, tipo='comite_desercion',
                        nivel='roja', titulo='Caso', mensaje='Caso', estado='escalada_comite',
                        fecha_escalada=datetime(2026, 11, 3, 15, 0))
        expediente = dp.armar_expediente(self.ficha, self.aprendiz, [alerta])
        self.assertEqual(expediente['plazos']['fecha_informe'], date(2026, 11, 3))


class NovedadesTest(BaseAuditoria):
    def _ampliacion(self, estado='autorizada', acta=None):
        hoy = date.today()
        return nv.registrar_novedad(self.aprendiz, self.ficha, 'aplazamiento', hoy, estado,
                                    hoy, hoy + timedelta(days=150), 'calamidad', ampliacion=True,
                                    acta_comite=acta)

    def test_ampliacion_sin_acta_queda_solicitada(self):
        self.assertEqual(self._ampliacion().estado, 'solicitada')
        self.assertEqual(self._ampliacion(acta='ACTA-3').estado, 'autorizada')

    def test_autorizar_ampliacion_exige_acta(self):
        novedad = self._ampliacion()
        with self.assertRaises(nv.ErrorNovedad):
            nv.cambiar_estado_novedad(novedad, 'autorizada', self.instructor.id)
        nv.cambiar_estado_novedad(novedad, 'autorizada', self.instructor.id, acta_comite='ACTA-9')
        self.assertEqual(novedad.estado, 'autorizada')
        self.assertEqual(novedad.acta_comite, 'ACTA-9')

    def test_dias_aplazados_se_cuentan_dentro_del_rango(self):
        novedad = NovedadAprendiz(tipo='aplazamiento', estado='autorizada',
                                  fecha_inicio=date(2026, 1, 10), fecha_fin=date(2026, 1, 19))
        self.assertEqual(nv.dias_aplazados_despues_de([novedad], date(2026, 1, 15), date(2026, 3, 1)), 5)
        self.assertEqual(nv.dias_aplazados_despues_de([], date(2026, 1, 1), date(2026, 2, 1)), 0)


class ProductivaTest(BaseAuditoria):
    def test_no_recomienda_cancelacion_con_aplazamiento_vigente(self):
        from app.services.comite_productiva import evaluar_aprendiz_productiva
        hoy = date.today()
        self.ficha.fecha_inicio = hoy - timedelta(days=1200)
        self.ficha.fecha_fin = hoy - timedelta(days=400)
        self.aprendiz.estado = 'APLAZADO'
        db.session.commit()
        sin_novedad = evaluar_aprendiz_productiva(self.aprendiz, self.ficha, hoy)
        self.assertEqual(sin_novedad['accion'], 'cancelacion_administrativa')
        vigente = NovedadAprendiz(tipo='aplazamiento', estado='autorizada', fecha_solicitud=hoy,
                                  fecha_inicio=hoy - timedelta(days=10), fecha_fin=hoy + timedelta(days=20))
        self.assertIsNone(evaluar_aprendiz_productiva(self.aprendiz, self.ficha, hoy, novedades=[vigente]))


class AccesoYRankingTest(BaseAuditoria):
    def test_aprendiz_no_activo_queda_en_solo_lectura(self):
        self.assertTrue(aprendiz_puede_escribir(self.aprendiz))
        self.aprendiz.estado = 'CANCELADO'
        db.session.commit()
        self.assertFalse(aprendiz_puede_escribir(self.aprendiz))
        self.assertFalse(aprendiz_puede_escribir(None))
        llamado = LlamadoAtencion(aprendiz_id=self.aprendiz.id, ficha_id=self.ficha.id, tipo='academico',
                                  numero=1, fecha=date.today(), descripcion='Hechos')
        db.session.add(llamado)
        db.session.commit()
        self._como_aprendiz(self.aprendiz)
        respuesta = self.cliente.post(f'/aprendiz/{self.ficha.id}/llamados/{llamado.id}/descargos',
                                      data={'descargos': 'Mi versión.'})
        self.assertEqual(respuesta.status_code, 302)
        db.session.refresh(llamado)
        self.assertIsNone(llamado.descargos)
        panel = self.cliente.get(f'/aprendiz/{self.ficha.id}/panel')
        self.assertEqual(panel.status_code, 200)
        self.assertIn('Tu matrícula ya no está en formación'.encode(), panel.data)

    def test_condicionado_puede_escribir_y_aparece_en_ranking(self):
        from app.services.ranking import calcular_ranking
        self.otro.estado = 'CONDICIONADO'
        db.session.commit()
        self.assertTrue(aprendiz_puede_escribir(self.otro))
        filas, _ = calcular_ranking(self.ficha.id)
        self.assertIn(self.otro.id, {fila['aprendiz'].id for fila in filas})

    def test_llamados_y_alertas_no_restan_puntaje(self):
        from app.services.ranking import calcular_ranking
        base = {f['aprendiz'].id: f['puntaje_total'] for f in calcular_ranking(self.ficha.id)[0]}
        db.session.add(NotaObservador(ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id,
                                      instructor_id=self.instructor.id, tipo='negativa',
                                      categoria='convivencia', descripcion='Hecho', fecha=date.today()))
        db.session.add(Alerta(ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id, tipo='comite_desercion',
                              nivel='roja', titulo='Caso', mensaje='Caso'))
        db.session.commit()
        despues = {f['aprendiz'].id: f['puntaje_total'] for f in calcular_ranking(self.ficha.id)[0]}
        self.assertEqual(despues[self.aprendiz.id], base[self.aprendiz.id])

    def test_panel_no_expone_los_ultimos_puestos(self):
        from app.models.ranking import ConfiguracionRanking
        extra = [Aprendiz(documento=f'60{i}', nombre=f'Persona{i}', apellidos='Prueba',
                          ficha_id=self.ficha.id, estado='EN_FORMACION') for i in range(4)]
        db.session.add_all(extra)
        config = ConfiguracionRanking.query.filter_by(ficha_id=self.ficha.id).first()
        if config is None:
            config = ConfiguracionRanking(ficha_id=self.ficha.id)
            db.session.add(config)
        config.modo_visibilidad = 'publico'
        db.session.commit()
        self._como_aprendiz(self.aprendiz)
        from unittest.mock import patch
        capturado = {}
        import app.routes.aprendiz as rutas
        original = rutas.render_template

        def espiar(plantilla, **contexto):
            capturado.update(contexto)
            return original(plantilla, **contexto)

        with patch.object(rutas, 'render_template', side_effect=espiar):
            self.assertEqual(self.cliente.get(f'/aprendiz/{self.ficha.id}/panel').status_code, 200)
        self.assertLessEqual(len(capturado['ranking_visible']), 4)

    def test_panel_sobrevive_si_fallan_las_alertas(self):
        from unittest.mock import patch
        self._como_aprendiz(self.aprendiz)
        with patch('app.routes.aprendiz.actualizar_alertas_ficha', side_effect=RuntimeError('caída')):
            self.assertEqual(self.cliente.get(f'/aprendiz/{self.ficha.id}/panel').status_code, 200)

    def test_reporte_de_coordinacion_ignora_llamados_anulados(self):
        from app.services.reporte_coordinacion import _datos_ficha
        llamado = self._llamado()
        self.assertEqual(_datos_ficha(self.ficha, date.today())['llamados'], 1)
        dp.anular_llamado(llamado, 'Error.')
        self.assertEqual(_datos_ficha(self.ficha, date.today())['llamados'], 0)

    def test_exporte_de_ranking_no_incluye_cedula(self):
        self._como_instructor()
        respuesta = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/ranking/exportar?formato=excel')
        self.assertEqual(respuesta.status_code, 200)
        import io
        import openpyxl
        libro = openpyxl.load_workbook(io.BytesIO(respuesta.data))
        valores = [str(c.value) for fila in libro.active.iter_rows() for c in fila if c.value is not None]
        self.assertNotIn('Documento', valores)
        self.assertNotIn(self.aprendiz.documento, valores)


if __name__ == '__main__':
    unittest.main()
