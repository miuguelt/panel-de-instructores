import unittest
from datetime import date, datetime, timedelta

from flask import g

from app import create_app, db
from app.models import (
    Alerta, Aprendiz, ConfiguracionAlertasComite, Ficha, Instructor, LlamadoAtencion,
    Notificacion, PlanMejoramiento, RegistroAsistencia, SesionAsistencia,
)
from app.services import debido_proceso as dp


def _app():
    return create_app({
        'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False,
    })


class DiasHabilesTest(unittest.TestCase):
    def test_salta_fin_de_semana(self):
        # Viernes 6 de noviembre de 2026 + 1 hábil = lunes 9.
        self.assertEqual(dp.sumar_dias_habiles(date(2026, 11, 6), 1), date(2026, 11, 9))

    def test_salta_festivos_de_colombia(self):
        # 16 de noviembre de 2026 es festivo (Independencia de Cartagena, trasladado).
        self.assertEqual(dp.sumar_dias_habiles(date(2026, 11, 13), 1), date(2026, 11, 17))

    def test_cero_dias_y_datetime(self):
        self.assertEqual(dp.sumar_dias_habiles(datetime(2026, 11, 9, 10), 0), date(2026, 11, 9))

    def test_dias_negativos_lanza_error(self):
        with self.assertRaises(ValueError):
            dp.sumar_dias_habiles(date(2026, 11, 9), -1)

    def test_plazo_de_justificacion_es_cinco_habiles(self):
        # Lunes 9 + 5 hábiles = lunes 16 es festivo, entonces martes 17.
        self.assertEqual(dp.fecha_limite_justificacion(date(2026, 11, 9)), date(2026, 11, 17))

    def test_plazos_del_comite(self):
        plazos = dp.plazos_comite(date(2026, 11, 9))
        self.assertEqual(plazos['citacion_limite'], date(2026, 11, 12))
        self.assertEqual(plazos['sesion_limite'], date(2026, 11, 24))


class DebidoProcesoBaseTest(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        self.instructor = Instructor(nombre='Instructor', correo='d@sena.edu.co', rol='admin')
        self.instructor.set_password('clave-segura')
        self.ajeno = Instructor(nombre='Ajeno', correo='a@sena.edu.co', rol='colaborador')
        self.ajeno.set_password('clave-segura')
        db.session.add_all([self.instructor, self.ajeno])
        db.session.flush()
        hoy = date.today()
        self.ficha = Ficha(codigo='DP1', nombre_programa='ADSO', instructor_id=self.instructor.id,
                           fecha_inicio=hoy - timedelta(days=100), fecha_fin=hoy + timedelta(days=500),
                           duracion_productiva_meses=6)
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendiz = Aprendiz(documento='1', nombre='Ana', apellidos='Ríos', ficha_id=self.ficha.id)
        db.session.add(self.aprendiz)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _llamado(self, tipo='academico', fase='analisis', orientaciones='Repasar la guía.'):
        return dp.registrar_llamado(self.aprendiz, self.ficha, tipo, 'No entregó evidencias.',
                                    instructor_id=self.instructor.id, orientaciones=orientaciones,
                                    fase=fase)


class LlamadosTest(DebidoProcesoBaseTest):
    def test_etapa_segun_periodo(self):
        self.assertEqual(dp.etapa_en(self.ficha, date.today()), 'lectiva')
        self.assertEqual(dp.etapa_en(self.ficha, self.ficha.fecha_fin - timedelta(days=10)), 'productiva')
        self.assertEqual(dp.etapa_en(self.ficha, self.ficha.fecha_fin + timedelta(days=10)), 'productiva')

    def test_numera_y_notifica(self):
        primero = self._llamado(orientaciones=None)
        segundo = self._llamado()
        self.assertEqual((primero.numero, segundo.numero), (1, 2))
        self.assertEqual(primero.etapa, 'lectiva')
        self.assertEqual(
            Notificacion.query.filter_by(destinatario_tipo='aprendiz', destinatario_id=self.aprendiz.id).count(), 2)

    def test_tercer_llamado_academico_en_la_misma_fase_se_bloquea(self):
        self._llamado()
        self._llamado()
        with self.assertRaisesRegex(dp.ReglaDebidoProceso, 'plan de mejoramiento'):
            self._llamado()
        # En otra fase el conteo vuelve a empezar.
        self.assertEqual(self._llamado(fase='ejecucion').numero, 1)

    def test_disciplinarios_cuentan_en_todo_el_programa(self):
        self._llamado('disciplinario', fase=None)
        self._llamado('disciplinario', fase=None)
        with self.assertRaisesRegex(dp.ReglaDebidoProceso, 'el programa'):
            self._llamado('disciplinario', fase=None)

    def test_segundo_llamado_exige_orientaciones(self):
        self._llamado()
        with self.assertRaisesRegex(dp.ReglaDebidoProceso, 'orientaciones'):
            self._llamado(orientaciones='   ')

    def test_validaciones_de_entrada(self):
        casos = (
            ({'tipo': 'verbal'}, 'académico o disciplinario'),
            ({'descripcion': '  '}, 'Describe los hechos'),
            ({'fase': 'otra'}, 'fase del proyecto'),
            ({'fase': None}, 'Indica la fase'),
        )
        for cambios, mensaje in casos:
            datos = {'tipo': 'academico', 'descripcion': 'Hechos', 'fase': 'analisis'}
            datos.update(cambios)
            with self.subTest(cambios=cambios), self.assertRaisesRegex(dp.ReglaDebidoProceso, mensaje):
                dp.registrar_llamado(self.aprendiz, self.ficha, datos['tipo'], datos['descripcion'],
                                     fase=datos['fase'])


class ValidarPlanTest(DebidoProcesoBaseTest):
    def test_limites_de_duracion(self):
        hoy = date.today()
        self.assertEqual(dp.validar_plan(self.aprendiz.id, self.ficha, hoy, hoy + timedelta(days=20))[0], [])
        errores = dp.validar_plan(self.aprendiz.id, self.ficha, hoy, hoy + timedelta(days=21))[0]
        self.assertIn('máximo es 20 días', errores[0])
        self.assertIn('anterior', dp.validar_plan(self.aprendiz.id, self.ficha, hoy, hoy - timedelta(days=1))[0][0])
        self.assertIn('Indica la fecha', dp.validar_plan(self.aprendiz.id, self.ficha, hoy, None)[0][0])

    def test_advierte_si_faltan_llamados_y_deja_de_advertir_con_dos(self):
        hoy = date.today()
        advertencias = dp.validar_plan(self.aprendiz.id, self.ficha, hoy, hoy + timedelta(days=10))[1]
        self.assertIn('0 llamado', advertencias[0])
        self._llamado()
        self._llamado()
        self.assertEqual(dp.validar_plan(self.aprendiz.id, self.ficha, hoy, hoy + timedelta(days=10))[1], [])

    def test_advierte_al_alcanzar_el_tope_de_planes(self):
        self._llamado()
        self._llamado()
        for _ in range(2):
            db.session.add(PlanMejoramiento(aprendiz_id=self.aprendiz.id, ficha_id=self.ficha.id,
                                            actividades='x', fecha_creacion=datetime.utcnow()))
        db.session.commit()
        hoy = date.today()
        advertencias = dp.validar_plan(self.aprendiz.id, self.ficha, hoy, hoy + timedelta(days=10))[1]
        self.assertIn('El tope es 2 por fase o módulo', advertencias[0])

    def test_tope_en_etapa_productiva_es_uno(self):
        en_productiva = self.ficha.fecha_fin - timedelta(days=30)
        db.session.add(PlanMejoramiento(aprendiz_id=self.aprendiz.id, ficha_id=self.ficha.id,
                                        actividades='x', fecha_creacion=datetime.combine(en_productiva, datetime.min.time())))
        db.session.commit()
        advertencias = dp.validar_plan(self.aprendiz.id, self.ficha, en_productiva, en_productiva + timedelta(days=5))[1]
        self.assertTrue(any('El tope es 1 en la etapa productiva' in a for a in advertencias))


class ExpedienteTest(DebidoProcesoBaseTest):
    def _alerta(self, tipo, detalle):
        alerta = Alerta(ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id, tipo=tipo, nivel='roja',
                        titulo='t', mensaje='m', detalle_json=detalle)
        db.session.add(alerta)
        db.session.commit()
        return alerta

    def test_une_fundamentos_sin_duplicar_y_agrega_procedimiento(self):
        from app.services.normativa_sena import obtener_fundamento
        f = obtener_fundamento('consecutivas_injustificadas')
        alertas = [
            self._alerta('comite_desercion', {'fundamentos': [f]}),
            self._alerta('asistencia', {'fundamento': f}),
            self._alerta('academica', {}),
        ]
        self._llamado()
        exp = dp.armar_expediente(self.ficha, self.aprendiz, alertas, date(2026, 11, 9))
        claves = [x['clave'] for x in exp['fundamentos']]
        self.assertEqual(claves.count('consecutivas_injustificadas'), 1)
        self.assertIn('citacion_comite', claves)
        self.assertEqual(exp['tipo_falta'], 'Deserción (Art. 30) y académica')
        self.assertEqual(len(exp['llamados']), 1)
        self.assertEqual(exp['plazos']['sesion_limite'], date(2026, 11, 24))
        self.assertEqual(len(exp['contenido_citacion']), 7)

    def test_tipo_de_falta(self):
        obs = self._alerta('observador', {})
        self.assertEqual(dp.armar_expediente(self.ficha, self.aprendiz, [obs])['tipo_falta'], 'Disciplinaria')
        aca = self._alerta('academica', {})
        self.assertEqual(dp.armar_expediente(self.ficha, self.aprendiz, [obs, aca])['tipo_falta'],
                         'Académica y disciplinaria')
        self.assertEqual(dp.armar_expediente(self.ficha, self.aprendiz, [])['tipo_falta'], 'Académica')
        for tipo in ('comite_desercion', 'productiva_vencida', 'reintegro_vencido'):
            with self.subTest(tipo=tipo):
                alerta = self._alerta(tipo, {})
                self.assertEqual(
                    dp.armar_expediente(self.ficha, self.aprendiz, [alerta])['tipo_falta'],
                    'Deserción (Art. 30)')


class RutasDebidoProcesoTest(DebidoProcesoBaseTest):
    def setUp(self):
        super().setUp()
        self.cliente = self.app.test_client()

    def _autenticar(self, instructor):
        g.pop('_login_user', None)
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(instructor.id)
            sesion['_fresh'] = True

    def _url_llamado(self, aprendiz_id=None):
        return f'/instructor/fichas/{self.ficha.id}/aprendices/{aprendiz_id or self.aprendiz.id}/llamados'

    def test_registrar_llamado_por_formulario(self):
        self._autenticar(self.instructor)
        datos = {'tipo': 'academico', 'fase': 'analisis', 'descripcion': 'Sin evidencias'}
        self.assertEqual(self.cliente.post(self._url_llamado(), data=datos).status_code, 302)
        self.assertEqual(LlamadoAtencion.query.count(), 1)
        self.cliente.post(self._url_llamado(), data=datos)  # segundo sin orientaciones: rechazado
        self.assertEqual(LlamadoAtencion.query.count(), 1)

    def test_llamado_protege_ficha_y_aprendiz(self):
        self._autenticar(self.ajeno)
        self.assertEqual(self.cliente.post(self._url_llamado(), data={}).status_code, 404)
        self._autenticar(self.instructor)
        self.assertEqual(self.cliente.post(self._url_llamado(9999), data={}).status_code, 404)

    def test_plan_mayor_a_20_dias_se_rechaza_y_valido_se_crea(self):
        self._autenticar(self.instructor)
        url = f'/instructor/fichas/{self.ficha.id}/planes-mejoramiento'
        largo = (date.today() + timedelta(days=30)).isoformat()
        self.cliente.post(url, data={'aprendiz_id': self.aprendiz.id, 'actividades': 'x', 'fecha_limite': largo})
        self.assertEqual(PlanMejoramiento.query.count(), 0)
        corto = (date.today() + timedelta(days=10)).isoformat()
        self.cliente.post(url, data={'aprendiz_id': self.aprendiz.id, 'actividades': 'x', 'fecha_limite': corto})
        self.assertEqual(PlanMejoramiento.query.count(), 1)

    def test_borrador_pdf_incluye_secciones_de_debido_proceso(self):
        from unittest.mock import patch
        from app.routes import seguimiento
        self._autenticar(self.instructor)
        self._llamado()
        db.session.add(PlanMejoramiento(aprendiz_id=self.aprendiz.id, ficha_id=self.ficha.id, actividades='Plan'))
        db.session.commit()
        capturado = {}
        original = seguimiento._secciones_debido_proceso

        def espiar(*args):
            capturado['elementos'] = original(*args)
            return capturado['elementos']

        with patch.object(seguimiento, '_secciones_debido_proceso', side_effect=espiar):
            respuesta = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/casos/{self.aprendiz.id}/reporte-comite')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.mimetype, 'application/pdf')
        textos = ' '.join(getattr(e, 'text', '') for e in capturado['elementos'])
        self.assertIn('Normas del reglamento', textos)
        self.assertIn('Contenido mínimo de la citación', textos)
        self.assertIn('10 días hábiles', textos)

    def test_borrador_pdf_sin_medidas_previas(self):
        self._autenticar(self.instructor)
        respuesta = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/casos/{self.aprendiz.id}/reporte-comite')
        self.assertEqual(respuesta.status_code, 200)

    def test_casos_muestra_formulario_de_llamados(self):
        self._autenticar(self.instructor)
        db.session.add(Alerta(ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id, tipo='academica',
                              nivel='roja', titulo='t', mensaje='m', estado='escalada_comite'))
        db.session.commit()
        html = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/casos-seguimiento').get_data(as_text=True)
        self.assertIn('Registrar llamado de atención escrito', html)
        self.assertIn('días hábiles; el reglamento fija 5', html)


class AvisoJustificacionTest(DebidoProcesoBaseTest):
    def test_aviso_indica_fecha_limite_habil_y_norma(self):
        from app.services.alertas import crear_recordatorios_aprendiz
        sesion = SesionAsistencia(ficha_id=self.ficha.id, fecha=date(2026, 11, 9))
        db.session.add(sesion)
        db.session.flush()
        db.session.add(RegistroAsistencia(sesion_id=sesion.id, aprendiz_id=self.aprendiz.id, estado='FALTA'))
        db.session.add(ConfiguracionAlertasComite(ficha_id=self.ficha.id))
        db.session.commit()
        self.assertEqual(ConfiguracionAlertasComite.query.first().dias_plazo_justificacion, 5)
        crear_recordatorios_aprendiz(self.ficha.id, self.aprendiz.id)
        aviso = Notificacion.query.filter_by(tipo='justificacion').one()
        self.assertIn('17/11/2026', aviso.mensaje)
        self.assertIn('Art. 28', aviso.mensaje)



class MigracionLlamadosTest(unittest.TestCase):
    def test_w47_crea_tabla_ajusta_plazo_y_revierte(self):
        import importlib.util
        import os
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import create_engine, inspect, text

        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ruta = os.path.join(raiz, 'migrations', 'versions', 'w47_llamados_atencion.py')
        spec = importlib.util.spec_from_file_location('w47', ruta)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)

        motor = create_engine('sqlite:///:memory:')
        conexion = motor.connect()
        try:
            for ddl in (
                'CREATE TABLE aprendices (id INTEGER PRIMARY KEY)',
                'CREATE TABLE fichas (id INTEGER PRIMARY KEY)',
                'CREATE TABLE alertas (id INTEGER PRIMARY KEY)',
                'CREATE TABLE instructores (id INTEGER PRIMARY KEY)',
                'CREATE TABLE configuracion_alertas_comite (id INTEGER PRIMARY KEY, '
                'ficha_id INTEGER, dias_plazo_justificacion INTEGER NOT NULL)',
            ):
                conexion.execute(text(ddl))
            conexion.execute(text(
                'INSERT INTO configuracion_alertas_comite VALUES (1, 1, 2), (2, 2, 7)'))
            conexion.commit()
            with Operations.context(MigrationContext.configure(conexion)):
                revision.upgrade()
            self.assertIn('llamados_atencion', inspect(conexion).get_table_names())
            plazos = conexion.execute(text(
                'SELECT dias_plazo_justificacion FROM configuracion_alertas_comite ORDER BY id')).fetchall()
            # El valor antiguo por defecto (2) pasa a 5; uno personalizado (7) se respeta.
            self.assertEqual(plazos, [(5,), (7,)])
            with Operations.context(MigrationContext.configure(conexion)):
                revision.downgrade()
            self.assertNotIn('llamados_atencion', inspect(conexion).get_table_names())
        finally:
            conexion.close()
            motor.dispose()


if __name__ == '__main__':
    unittest.main()
