import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from flask import g

from app import create_app, db
from app.models import (
    Alerta, Aprendiz, EtapaProductiva, Ficha, Instructor, NovedadAprendiz, SeguimientoProductiva,
)
from app.services import comite_productiva as cp
from app.services import novedades as nv
from app.services.debido_proceso import restar_dias_habiles


def _app():
    return create_app({
        'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False,
    })


def _novedad(tipo='aplazamiento', estado='autorizada', inicio=date(2026, 9, 1),
             fin=date(2026, 11, 20), solicitud=None, id=1):
    return SimpleNamespace(tipo=tipo, estado=estado, fecha_inicio=inicio, fecha_fin=fin,
                           fecha_solicitud=solicitud or inicio, id=id)


class FechasTest(unittest.TestCase):
    def test_restar_dias_habiles_salta_festivos_y_fines_de_semana(self):
        # Martes 17/11/2026 - 1 hábil: el lunes 16 es festivo, entonces viernes 13.
        self.assertEqual(restar_dias_habiles(date(2026, 11, 17), 1), date(2026, 11, 13))
        self.assertEqual(restar_dias_habiles(datetime(2026, 11, 9, 8), 0), date(2026, 11, 9))
        with self.assertRaises(ValueError):
            restar_dias_habiles(date(2026, 11, 9), -1)

    def test_fechas_de_reintegro(self):
        fechas = nv.fechas_reintegro(_novedad(fin=date(2026, 11, 20)))
        # Viernes 20: 3 hábiles antes = martes 17 (16 festivo); 5 hábiles antes = jueves 12.
        self.assertEqual(fechas['limite'], date(2026, 11, 17))
        self.assertEqual(fechas['aviso'], date(2026, 11, 12))

    def test_fin_maximo_del_aplazamiento(self):
        self.assertEqual(nv.fecha_fin_maxima_aplazamiento(date(2026, 1, 31)), date(2026, 4, 30))
        self.assertEqual(nv.fecha_fin_maxima_aplazamiento(date(2026, 1, 1), True), date(2026, 7, 1))


class SeleccionAplazamientoTest(unittest.TestCase):
    def test_ultimo_aplazamiento_solo_autorizados_con_fecha(self):
        lista = [
            _novedad(fin=date(2026, 5, 1), id=1),
            _novedad(fin=date(2026, 8, 1), id=2),
            _novedad(estado='negada', fin=date(2026, 12, 1), id=3),
            _novedad(tipo='traslado', fin=date(2026, 12, 1), id=4),
            _novedad(fin=None, id=5),
        ]
        self.assertEqual(nv.ultimo_aplazamiento(lista).id, 2)
        self.assertIsNone(nv.ultimo_aplazamiento([]))

    def test_reintegro_no_negado_posterior(self):
        apl = _novedad(inicio=date(2026, 9, 1))
        self.assertFalse(nv.tiene_reintegro([apl], apl))
        antes = _novedad('reintegro', 'solicitada', solicitud=date(2026, 8, 1))
        negado = _novedad('reintegro', 'negada', solicitud=date(2026, 10, 1))
        valido = _novedad('reintegro', 'solicitada', solicitud=date(2026, 10, 1))
        self.assertFalse(nv.tiene_reintegro([apl, antes, negado], apl))
        self.assertTrue(nv.tiene_reintegro([apl, valido], apl))

    def test_aplazamiento_vigente(self):
        apl = _novedad(fin=date(2026, 11, 20))
        self.assertIs(nv.aplazamiento_vigente([apl], date(2026, 11, 20)), apl)
        self.assertIsNone(nv.aplazamiento_vigente([apl], date(2026, 11, 21)))


class EvaluarReintegroTest(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.contexto = self.app.app_context()
        self.contexto.push()
        self.aprendiz = Aprendiz(id=1, documento='1', nombre='Ana', apellidos='Ríos', estado='APLAZADO')
        self.apl = _novedad(fin=date(2026, 11, 20))

    def tearDown(self):
        self.contexto.pop()

    def test_niveles_segun_la_fecha(self):
        self.assertIsNone(nv.evaluar_reintegro(self.aprendiz, [self.apl], date(2026, 11, 11)))
        amarilla = nv.evaluar_reintegro(self.aprendiz, [self.apl], date(2026, 11, 12))
        self.assertEqual(amarilla['nivel'], 'amarilla')
        self.assertEqual(amarilla['fundamentos'][0]['pagina'], 23)
        self.assertEqual(nv.evaluar_reintegro(self.aprendiz, [self.apl], date(2026, 11, 17))['nivel'], 'amarilla')
        roja = nv.evaluar_reintegro(self.aprendiz, [self.apl], datetime(2026, 11, 18, 9))
        self.assertEqual(roja['nivel'], 'roja')
        self.assertEqual(roja['fundamentos'][0]['clave'], 'aplazamiento_vencido')
        self.assertIn('17/11/2026', roja['motivo'])

    def test_no_aplica_sin_aplazamiento_con_reintegro_o_estado_cerrado(self):
        hoy = date(2026, 12, 1)
        self.assertIsNone(nv.evaluar_reintegro(self.aprendiz, [], hoy))
        reintegro = _novedad('reintegro', 'solicitada', solicitud=date(2026, 11, 10))
        self.assertIsNone(nv.evaluar_reintegro(self.aprendiz, [self.apl, reintegro], hoy))
        self.aprendiz.estado = 'CANCELADO'
        self.assertIsNone(nv.evaluar_reintegro(self.aprendiz, [self.apl], hoy))


class BaseDatosTest(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        self.instructor = Instructor(nombre='Instructor', correo='nv@sena.edu.co', rol='admin')
        self.instructor.set_password('clave-segura')
        self.ajeno = Instructor(nombre='Ajeno', correo='aj@sena.edu.co', rol='colaborador')
        self.ajeno.set_password('clave-segura')
        db.session.add_all([self.instructor, self.ajeno])
        db.session.flush()
        hoy = date.today()
        self.ficha = Ficha(codigo='NV1', nombre_programa='ADSO', instructor_id=self.instructor.id,
                           fecha_inicio=hoy - timedelta(days=800), fecha_fin=hoy - timedelta(days=20))
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendiz = Aprendiz(documento='1', nombre='Ana', apellidos='Ríos',
                                 ficha_id=self.ficha.id, estado='EN_FORMACION')
        db.session.add(self.aprendiz)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()


class RegistrarNovedadTest(BaseDatosTest):
    def test_aplazamiento_valido_y_limites(self):
        inicio = date(2026, 1, 10)
        n = nv.registrar_novedad(self.aprendiz, self.ficha, 'aplazamiento', inicio, 'autorizada',
                                 inicio, date(2026, 4, 10), 'incapacidad', observacion='  ')
        self.assertIsNone(n.observacion)
        self.assertEqual(n.etiqueta_tipo, 'Aplazamiento')
        self.assertEqual(n.etiqueta_estado, 'Autorizada')
        with self.assertRaisesRegex(nv.ErrorNovedad, 'supera 3 meses'):
            nv.registrar_novedad(self.aprendiz, self.ficha, 'aplazamiento', inicio, 'autorizada',
                                 inicio, date(2026, 4, 11), 'incapacidad')
        ampliado = nv.registrar_novedad(self.aprendiz, self.ficha, 'aplazamiento', inicio, 'autorizada',
                                        inicio, date(2026, 7, 10), 'calamidad', ampliacion=True)
        self.assertTrue(ampliado.ampliacion)
        with self.assertRaisesRegex(nv.ErrorNovedad, '6 meses'):
            nv.registrar_novedad(self.aprendiz, self.ficha, 'aplazamiento', inicio, 'autorizada',
                                 inicio, date(2026, 7, 11), 'calamidad', ampliacion=True)

    def test_validaciones(self):
        casos = (
            (dict(tipo='otra'), 'tipo de novedad'),
            (dict(estado='x'), 'estado de la novedad'),
            (dict(fecha_solicitud=None), 'fecha de solicitud'),
            (dict(fecha_inicio=date(2026, 2, 1), fecha_fin=date(2026, 1, 1)), 'anterior'),
            (dict(fecha_fin=None), 'requiere fecha'),
            (dict(causa='otra'), 'causa del aplazamiento'),
        )
        for cambios, mensaje in casos:
            datos = dict(tipo='aplazamiento', fecha_solicitud=date(2026, 1, 1), estado='solicitada',
                         fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 2, 1), causa='judicial')
            datos.update(cambios)
            with self.subTest(cambios=cambios), self.assertRaisesRegex(nv.ErrorNovedad, mensaje):
                nv.registrar_novedad(self.aprendiz, self.ficha, datos.pop('tipo'),
                                     datos.pop('fecha_solicitud'), **datos)

    def test_otras_novedades_descartan_causa_y_ampliacion(self):
        n = nv.registrar_novedad(self.aprendiz, self.ficha, 'traslado', date(2026, 1, 1),
                                 causa='incapacidad', ampliacion=True)
        self.assertIsNone(n.causa)
        self.assertFalse(n.ampliacion)

    def test_cambiar_estado(self):
        n = nv.registrar_novedad(self.aprendiz, self.ficha, 'retiro_voluntario', date(2026, 1, 1))
        self.assertEqual(nv.cambiar_estado_novedad(n, 'negada').estado, 'negada')
        with self.assertRaises(nv.ErrorNovedad):
            nv.cambiar_estado_novedad(n, 'x')


class EtapaProductivaTest(BaseDatosTest):
    def test_registro_unico_y_actualizacion(self):
        etapa = nv.registrar_etapa_productiva(self.aprendiz, self.ficha, 'pasantia', empresa=' ACME ',
                                              planeacion_avalada=True, fecha_aval=date(2026, 1, 5),
                                              instructor_seguimiento='Luz')
        self.assertEqual(etapa.empresa, 'ACME')
        self.assertEqual(etapa.etiqueta_alternativa, 'Pasantía')
        self.assertEqual(etapa.etiqueta_estado, 'Por iniciar')
        otra = nv.registrar_etapa_productiva(self.aprendiz, self.ficha, 'contrato_aprendizaje',
                                             estado='en_curso')
        self.assertEqual(otra.id, etapa.id)
        self.assertFalse(otra.planeacion_avalada)
        self.assertIsNone(otra.fecha_aval)
        self.assertEqual(EtapaProductiva.query.count(), 1)

    def test_validaciones_de_etapa(self):
        for args, mensaje in (
            (dict(alternativa='x'), 'alternativa'),
            (dict(estado='x'), 'estado de la etapa'),
            (dict(fecha_inicio=date(2026, 2, 1), fecha_fin_estimada=date(2026, 1, 1)), 'anterior'),
            (dict(planeacion_avalada=True), 'fecha en que se avaló'),
        ):
            datos = dict(alternativa='pasantia')
            datos.update(args)
            with self.subTest(args=args), self.assertRaisesRegex(nv.ErrorNovedad, mensaje):
                nv.registrar_etapa_productiva(self.aprendiz, self.ficha, datos.pop('alternativa'), **datos)

    def test_momentos_de_seguimiento(self):
        etapa = nv.registrar_etapa_productiva(self.aprendiz, self.ficha, 'pasantia')
        with self.assertRaisesRegex(nv.ErrorNovedad, 'primero la concertación'):
            nv.registrar_seguimiento(etapa, 'parcial', date(2026, 1, 1))
        s = nv.registrar_seguimiento(etapa, 'concertacion', date(2026, 1, 1), ' Inicio ')
        self.assertEqual(s.observacion, 'Inicio')
        self.assertEqual(s.etiqueta_momento, 'Concertación')
        with self.assertRaisesRegex(nv.ErrorNovedad, 'Ya se registró'):
            nv.registrar_seguimiento(etapa, 'concertacion', date(2026, 1, 2))
        nv.registrar_seguimiento(etapa, 'final', date(2026, 3, 1))
        for momento, fecha, mensaje in (('x', date(2026, 1, 1), 'momento'), ('parcial', None, 'fecha')):
            with self.subTest(momento=momento), self.assertRaisesRegex(nv.ErrorNovedad, mensaje):
                nv.registrar_seguimiento(etapa, momento, fecha)
        self.assertEqual(SeguimientoProductiva.query.count(), 2)

    def test_cargar_datos_y_resumen(self):
        nv.registrar_etapa_productiva(self.aprendiz, self.ficha, 'pasantia')
        nv.registrar_novedad(self.aprendiz, self.ficha, 'aplazamiento', date.today(), 'autorizada',
                             date.today(), date.today() + timedelta(days=30), 'judicial')
        etapas, novedades = nv.cargar_datos_ficha(self.ficha.id)
        resumen = nv.resumen_aprendiz(self.aprendiz, etapas.get(self.aprendiz.id),
                                      novedades[self.aprendiz.id])
        self.assertIsNotNone(resumen['aplazamiento'])
        self.assertFalse(resumen['reintegro_solicitado'])
        self.assertEqual(resumen['momentos'], set())
        vacio = nv.resumen_aprendiz(self.aprendiz, None, [], date.today())
        self.assertIsNone(vacio['fechas_reintegro'])


class ReglaProductivaConRegistrosTest(BaseDatosTest):
    def _evaluar(self):
        etapas, novedades = nv.cargar_datos_ficha(self.ficha.id)
        return cp.evaluar_aprendiz_productiva(self.aprendiz, self.ficha, date.today(),
                                              etapas.get(self.aprendiz.id),
                                              novedades.get(self.aprendiz.id, ()))

    def test_aval_antes_del_cierre_evita_la_remision(self):
        self.assertIsNotNone(self._evaluar())
        nv.registrar_etapa_productiva(self.aprendiz, self.ficha, 'pasantia', planeacion_avalada=True,
                                      fecha_aval=self.ficha.fecha_fin - timedelta(days=5))
        self.assertIsNone(self._evaluar())

    def test_aval_despues_del_cierre_mantiene_la_remision_con_advertencia(self):
        nv.registrar_etapa_productiva(self.aprendiz, self.ficha, 'pasantia', planeacion_avalada=True,
                                      fecha_aval=self.ficha.fecha_fin + timedelta(days=2))
        r = self._evaluar()
        self.assertIn('después del cierre', r['advertencias'][0])

    def test_aplazamiento_vigente_evita_la_remision(self):
        self.aprendiz.estado = 'APLAZADO'
        hoy = date.today()
        nv.registrar_novedad(self.aprendiz, self.ficha, 'aplazamiento', hoy - timedelta(days=30),
                             'autorizada', hoy - timedelta(days=30), hoy + timedelta(days=30), 'judicial')
        self.assertIsNone(self._evaluar())

    def test_cancelacion_al_anio_aplica_aunque_haya_aval(self):
        self.ficha.fecha_fin = date.today() - timedelta(days=400)
        db.session.commit()
        nv.registrar_etapa_productiva(self.aprendiz, self.ficha, 'pasantia', planeacion_avalada=True,
                                      fecha_aval=self.ficha.fecha_fin - timedelta(days=5))
        self.assertEqual(self._evaluar()['accion'], cp.ACCION_CANCELACION)

    def test_alertas_de_reintegro_se_crean_y_resuelven(self):
        from app.services.alertas import actualizar_alertas_ficha
        self.aprendiz.estado = 'APLAZADO'
        hoy = date.today()
        nv.registrar_novedad(self.aprendiz, self.ficha, 'aplazamiento', hoy - timedelta(days=60),
                             'autorizada', hoy - timedelta(days=60), hoy - timedelta(days=1), 'judicial')
        actualizar_alertas_ficha(self.ficha.id)
        alerta = Alerta.query.filter_by(tipo=nv.TIPO_ALERTA_REINTEGRO).one()
        self.assertEqual(alerta.nivel, 'roja')
        self.assertEqual(alerta.detalle_json['fundamento']['pagina'], 31)
        # Pedir el reintegro después del límite no borra la causal: queda como tardío.
        nv.registrar_novedad(self.aprendiz, self.ficha, 'reintegro', hoy)
        actualizar_alertas_ficha(self.ficha.id)
        alerta = Alerta.query.filter_by(tipo=nv.TIPO_ALERTA_REINTEGRO).one()
        self.assertEqual(alerta.estado, 'activa')
        self.assertIn('Reintegro tardío', alerta.titulo)

    def test_reintegro_a_tiempo_resuelve_la_alerta(self):
        from app.services.alertas import actualizar_alertas_ficha
        self.aprendiz.estado = 'APLAZADO'
        hoy = date.today()
        aplazamiento = nv.registrar_novedad(
            self.aprendiz, self.ficha, 'aplazamiento', hoy - timedelta(days=60),
            'autorizada', hoy - timedelta(days=60), hoy - timedelta(days=1), 'judicial')
        limite = nv.fechas_reintegro(aplazamiento)['limite']
        nv.registrar_novedad(self.aprendiz, self.ficha, 'reintegro', limite)
        actualizar_alertas_ficha(self.ficha.id)
        self.assertEqual(Alerta.query.filter_by(tipo=nv.TIPO_ALERTA_REINTEGRO).count(), 0)


class LlamadaDirectaTest(BaseDatosTest):
    def test_actualizar_alertas_productiva_carga_sus_datos(self):
        self.assertEqual(cp.actualizar_alertas_productiva(self.ficha, datetime.utcnow()), 1)
        self.assertEqual(Alerta.query.filter_by(tipo=cp.TIPO_ALERTA).count(), 1)

    def test_reporte_omite_novedades_que_no_son_aplazamiento(self):
        from app.services.reporte_coordinacion import _datos_ficha, filas_novedades
        nv.registrar_novedad(self.aprendiz, self.ficha, 'traslado', date.today())
        self.assertEqual(filas_novedades(self.ficha, _datos_ficha(self.ficha, date.today())), [])


class RutasNovedadesTest(BaseDatosTest):
    def setUp(self):
        super().setUp()
        self.cliente = self.app.test_client()
        g.pop('_login_user', None)
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True
        self.base = f'/instructor/fichas/{self.ficha.id}'

    def test_pagina_lista_aprendices_y_normas(self):
        html = self.cliente.get(f'{self.base}/novedades-productiva').get_data(as_text=True)
        self.assertIn('Ana Ríos', html)
        self.assertIn('Estado en el reporte: En formación', html)
        self.assertIn('Registrar una novedad', html)
        self.assertIn('Artículo 18, numeral 3', html)

    def test_flujo_completo_por_formularios(self):
        url_ap = f'{self.base}/aprendices/{self.aprendiz.id}'
        hoy = date.today()
        r = self.cliente.post(f'{url_ap}/novedades', data={
            'tipo': 'aplazamiento', 'estado': 'solicitada', 'fecha_solicitud': hoy.isoformat(),
            'fecha_inicio': hoy.isoformat(), 'fecha_fin': (hoy + timedelta(days=20)).isoformat(),
            'causa': 'calamidad'})
        self.assertIn(f'#aprendiz-{self.aprendiz.id}', r.headers['Location'])
        novedad = NovedadAprendiz.query.one()
        self.cliente.post(f'{url_ap}/novedades', data={'tipo': 'aplazamiento', 'fecha_solicitud': 'mal'})
        self.assertEqual(NovedadAprendiz.query.count(), 1)
        self.cliente.post(f'{self.base}/novedades/{novedad.id}/estado', data={'estado': 'negada'})
        self.assertEqual(db.session.get(NovedadAprendiz, novedad.id).estado, 'negada')
        self.cliente.post(f'{self.base}/novedades/{novedad.id}/estado', data={'estado': 'x'})
        self.assertEqual(db.session.get(NovedadAprendiz, novedad.id).estado, 'negada')
        # Una decisión tomada no se revierte desde el formulario.
        self.cliente.post(f'{self.base}/novedades/{novedad.id}/estado', data={'estado': 'autorizada'})
        decidida = db.session.get(NovedadAprendiz, novedad.id)
        self.assertEqual(decidida.estado, 'negada')
        self.assertEqual(decidida.estado_cambiado_por, self.instructor.id)
        self.assertIsNotNone(decidida.estado_cambiado_en)

        self.cliente.post(f'{url_ap}/etapa-productiva/seguimiento', data={'momento': 'concertacion'})
        self.assertEqual(SeguimientoProductiva.query.count(), 0)
        self.cliente.post(f'{url_ap}/etapa-productiva', data={'alternativa': 'x'})
        self.assertEqual(EtapaProductiva.query.count(), 0)
        self.cliente.post(f'{url_ap}/etapa-productiva', data={
            'alternativa': 'pasantia', 'planeacion_avalada': '1', 'fecha_aval': hoy.isoformat()})
        self.assertTrue(EtapaProductiva.query.one().planeacion_avalada)
        self.cliente.post(f'{url_ap}/etapa-productiva/seguimiento',
                          data={'momento': 'concertacion', 'fecha': hoy.isoformat()})
        self.cliente.post(f'{url_ap}/etapa-productiva/seguimiento',
                          data={'momento': 'concertacion', 'fecha': hoy.isoformat()})
        self.assertEqual(SeguimientoProductiva.query.count(), 1)
        html = self.cliente.get(f'{self.base}/novedades-productiva').get_data(as_text=True)
        self.assertIn('Planeación avalada', html)
        self.assertIn('Concertación', html)

    def test_permisos_y_recursos_ajenos(self):
        g.pop('_login_user', None)
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.ajeno.id)
        self.assertEqual(self.cliente.get(f'{self.base}/novedades-productiva').status_code, 404)
        g.pop('_login_user', None)
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
        self.assertEqual(self.cliente.post(f'{self.base}/aprendices/999/novedades').status_code, 404)
        self.assertEqual(self.cliente.post(f'{self.base}/novedades/999/estado').status_code, 404)


class MigracionNovedadesTest(unittest.TestCase):
    def test_x48_sube_y_baja(self):
        import importlib.util
        import os
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import create_engine, inspect, text

        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ruta = os.path.join(raiz, 'migrations', 'versions', 'x48_novedades_productiva.py')
        spec = importlib.util.spec_from_file_location('x48', ruta)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        motor = create_engine('sqlite:///:memory:')
        conexion = motor.connect()
        try:
            for tabla in ('aprendices', 'fichas', 'instructores'):
                conexion.execute(text(f'CREATE TABLE {tabla} (id INTEGER PRIMARY KEY)'))
            conexion.commit()
            nuevas = {'novedades_aprendiz', 'etapas_productivas', 'seguimientos_productiva'}
            with Operations.context(MigrationContext.configure(conexion)):
                revision.upgrade()
            self.assertTrue(nuevas <= set(inspect(conexion).get_table_names()))
            with Operations.context(MigrationContext.configure(conexion)):
                revision.downgrade()
            self.assertFalse(nuevas & set(inspect(conexion).get_table_names()))
        finally:
            conexion.close()
            motor.dispose()


if __name__ == '__main__':
    unittest.main()
