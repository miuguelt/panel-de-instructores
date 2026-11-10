import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from flask import g

from app import create_app, db
from app.models import Alerta, Aprendiz, Ficha, Instructor, RegistroAsistencia, SesionAsistencia
from app.routes.comite import filas_csv
from app.services import comite_productiva as cp
from app.services.alertas import actualizar_alertas_ficha, ejecutar_revision_automatica

HOY = date(2026, 11, 9)


def _ficha(fecha_fin=date(2026, 10, 30), codigo='2900001', id=1):
    return SimpleNamespace(id=id, codigo=codigo, fecha_fin=fecha_fin)


def _aprendiz(estado='EN_FORMACION', id=10, documento='100'):
    return Aprendiz(id=id, documento=documento, nombre='Ana', apellidos='Ríos', estado=estado)


class ReglaPuraTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}})
        self.contexto = self.app.app_context()
        self.contexto.push()

    def tearDown(self):
        self.contexto.pop()

    def test_limite_es_la_fecha_fin_del_grupo(self):
        self.assertEqual(cp.fecha_limite_productiva(_ficha()), date(2026, 10, 30))
        self.assertIsNone(cp.fecha_limite_productiva(SimpleNamespace()))

    def test_ficha_terminada_respeta_los_limites_de_fecha(self):
        fin = date(2026, 10, 30)
        self.assertFalse(cp.ficha_terminada(_ficha(fin), fin - timedelta(days=1)))
        self.assertFalse(cp.ficha_terminada(_ficha(fin), fin))
        self.assertTrue(cp.ficha_terminada(_ficha(fin), fin + timedelta(days=1)))
        self.assertFalse(cp.ficha_terminada(_ficha(None), HOY))

    def test_el_dia_del_cierre_aun_no_recomienda(self):
        fin = date(2026, 10, 30)
        self.assertIsNone(cp.evaluar_aprendiz_productiva(_aprendiz(), _ficha(fin), fin))
        r = cp.evaluar_aprendiz_productiva(_aprendiz(), _ficha(fin), fin + timedelta(days=1))
        self.assertEqual(r['dias_vencida'], 1)
        self.assertEqual(r['accion'], cp.ACCION_COMITE)

    def test_acepta_datetime_como_hoy(self):
        r = cp.evaluar_aprendiz_productiva(_aprendiz(), _ficha(), datetime(2026, 11, 9, 8, 0))
        self.assertEqual(r['dias_vencida'], 10)

    def test_estados_sin_culminar_se_recomiendan(self):
        for estado in ('EN', 'En formación', 'INDUCCION', 'Condicionado', 'APLAZADO', 'En aplazamiento'):
            with self.subTest(estado=estado):
                r = cp.evaluar_aprendiz_productiva(_aprendiz(estado), _ficha(), HOY)
                self.assertIsNotNone(r)
                self.assertEqual(r['nivel'], 'roja')

    def test_estados_cerrados_no_se_recomiendan(self):
        for estado in ('POR_CERTIFICAR', 'CERTIFICADO', 'RETIRO_VOLUNTARIO', 'CANCELADO', 'TRASLADADO', None):
            with self.subTest(estado=estado):
                self.assertIsNone(cp.evaluar_aprendiz_productiva(_aprendiz(estado), _ficha(), HOY))

    def test_recomendacion_cita_articulo_30_num_2_pagina_31(self):
        r = cp.evaluar_aprendiz_productiva(_aprendiz(), _ficha(), HOY)
        principal = r['fundamentos'][0]
        self.assertEqual(principal['clave'], 'productiva_vencida')
        self.assertEqual(principal['pagina'], 31)
        self.assertIn('#page=31', principal['url'])
        self.assertIn('Art. 30', r['motivo'])
        self.assertIn('30/10/2026', r['motivo'])
        claves = [f['clave'] for f in r['fundamentos']]
        self.assertIn('procedimiento_desercion_productiva', claves)
        self.assertIn('debido_proceso', claves)
        self.assertFalse(r['aplazado'])
        self.assertEqual(len(r['advertencias']), 1)

    def test_aplazado_agrega_fundamentos_y_advertencia_de_aplazamiento(self):
        r = cp.evaluar_aprendiz_productiva(_aprendiz('APLAZADO'), _ficha(), HOY)
        claves = [f['clave'] for f in r['fundamentos']]
        self.assertIn('aplazamiento', claves)
        self.assertIn('aplazamiento_vencido', claves)
        self.assertTrue(r['aplazado'])
        self.assertIn('Art. 18', r['advertencias'][0])

    def test_un_anio_despues_procede_cancelacion_administrativa(self):
        fin = date(2025, 11, 1)
        antes = cp.evaluar_aprendiz_productiva(_aprendiz(), _ficha(fin), fin + timedelta(days=364))
        self.assertEqual(antes['accion'], cp.ACCION_COMITE)
        r = cp.evaluar_aprendiz_productiva(_aprendiz(), _ficha(fin), fin + timedelta(days=365))
        self.assertEqual(r['accion'], cp.ACCION_CANCELACION)
        self.assertEqual(r['fundamentos'][1]['clave'], 'cancelacion_un_anio')
        self.assertEqual(r['fundamentos'][1]['pagina'], 39)
        self.assertIn('Art. 47', r['motivo'])

    def test_analizar_ficha_filtra_y_ordena(self):
        aprendices = [
            _aprendiz('EN_FORMACION', 1, '1'), _aprendiz('CERTIFICADO', 2, '2'),
            _aprendiz('APLAZADO', 3, '3'),
        ]
        aprendices[0].nombre = 'Zoe'
        resultado = cp.analizar_ficha(_ficha(), aprendices, HOY)
        self.assertEqual([r['documento'] for r in resultado], ['3', '1'])
        self.assertEqual(cp.analizar_ficha(_ficha(date(2027, 1, 1)), aprendices, HOY), [])


class IntegracionComiteTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        self.instructor = Instructor(nombre='Instructor', correo='c@sena.edu.co', rol='admin')
        self.instructor.set_password('clave-segura')
        self.ajeno = Instructor(nombre='Otro', correo='o@sena.edu.co', rol='colaborador')
        self.ajeno.set_password('clave-segura')
        db.session.add_all([self.instructor, self.ajeno])
        db.session.flush()
        hoy = date.today()
        self.terminada = Ficha(codigo='T1', nombre_programa='ADSO', instructor_id=self.instructor.id,
                               fecha_inicio=hoy - timedelta(days=800), fecha_fin=hoy - timedelta(days=20))
        self.activa = Ficha(codigo='A1', nombre_programa='ADSO', instructor_id=self.instructor.id,
                            fecha_inicio=hoy - timedelta(days=100), fecha_fin=hoy + timedelta(days=300))
        db.session.add_all([self.terminada, self.activa])
        db.session.flush()
        self.pendiente = Aprendiz(documento='1', nombre='Ana', apellidos='Ríos',
                                  ficha_id=self.terminada.id, estado='EN_FORMACION')
        self.aplazado = Aprendiz(documento='2', nombre='Beto', apellidos='Gil',
                                 ficha_id=self.terminada.id, estado='APLAZADO')
        self.certificado = Aprendiz(documento='3', nombre='Caro', apellidos='Paz',
                                    ficha_id=self.terminada.id, estado='CERTIFICADO')
        self.activo = Aprendiz(documento='4', nombre='Dani', apellidos='Sol',
                               ficha_id=self.activa.id, estado='EN_FORMACION')
        db.session.add_all([self.pendiente, self.aplazado, self.certificado, self.activo])
        db.session.commit()
        self.cliente = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _alertas(self, ficha):
        return Alerta.query.filter_by(ficha_id=ficha.id, tipo=cp.TIPO_ALERTA).all()

    def _autenticar(self, instructor):
        g.pop('_login_user', None)
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(instructor.id)
            sesion['_fresh'] = True

    def test_actualizar_alertas_crea_alerta_con_fundamento(self):
        actualizar_alertas_ficha(self.terminada.id)
        alertas = {a.aprendiz_id: a for a in self._alertas(self.terminada)}
        self.assertEqual(set(alertas), {self.pendiente.id, self.aplazado.id})
        detalle = alertas[self.pendiente.id].detalle_json
        self.assertEqual(alertas[self.pendiente.id].nivel, 'roja')
        self.assertEqual(detalle['dias_vencida'], 20)
        self.assertEqual(detalle['fundamento']['pagina'], 31)
        self.assertIn('Artículo 30', detalle['reglamento'])
        self.assertIn('aplazamiento', [f['clave'] for f in alertas[self.aplazado.id].detalle_json['fundamentos']])

    def test_ficha_activa_no_genera_alerta_productiva(self):
        actualizar_alertas_ficha(self.activa.id)
        self.assertEqual(self._alertas(self.activa), [])

    def test_reevaluar_no_duplica_y_resuelve_al_certificar(self):
        actualizar_alertas_ficha(self.terminada.id)
        actualizar_alertas_ficha(self.terminada.id)
        self.assertEqual(len(self._alertas(self.terminada)), 2)
        self.pendiente.estado = 'CERTIFICADO'
        db.session.commit()
        actualizar_alertas_ficha(self.terminada.id)
        estados = {a.aprendiz_id: a.estado for a in self._alertas(self.terminada)}
        self.assertEqual(estados[self.pendiente.id], 'resuelta')
        self.assertEqual(estados[self.aplazado.id], 'activa')

    def test_revision_automatica_incluye_terminadas_recientes_y_omite_antiguas(self):
        antigua = Ficha(codigo='V1', nombre_programa='ADSO', instructor_id=self.instructor.id,
                        fecha_inicio=date.today() - timedelta(days=1500),
                        fecha_fin=date.today() - timedelta(days=500))
        db.session.add(antigua)
        db.session.flush()
        db.session.add(Aprendiz(documento='9', nombre='Eva', apellidos='Luz',
                                ficha_id=antigua.id, estado='EN_FORMACION'))
        db.session.commit()
        evaluadas = ejecutar_revision_automatica()
        self.assertEqual(evaluadas, 2)
        self.assertEqual(len(self._alertas(self.terminada)), 2)
        self.assertEqual(self._alertas(antigua), [])

    def test_analizar_fichas_terminadas_resume_por_ficha(self):
        resultado = cp.analizar_fichas_terminadas([self.terminada, self.activa])
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]['total_aprendices'], 3)
        self.assertEqual(resultado[0]['dias_desde_cierre'], 20)
        self.assertEqual(len(resultado[0]['recomendaciones']), 2)

    def test_filas_csv_incluyen_fundamento_y_pagina(self):
        filas = filas_csv(cp.analizar_fichas_terminadas([self.terminada]))
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0][0], 'T1')
        self.assertIn('Artículo 30', filas[0][8])
        self.assertEqual(filas[0][9], 31)

    def test_vista_muestra_aprendices_y_enlace_al_pdf(self):
        self._autenticar(self.instructor)
        html = self.cliente.get('/instructor/comite/fichas-terminadas').get_data(as_text=True)
        self.assertIn('Ficha T1', html)
        self.assertIn('Ana Ríos', html)
        self.assertIn('Beto Gil', html)
        self.assertNotIn('Caro Paz', html)
        self.assertIn('Abrir el PDF en la página 31', html)
        self.assertIn('Remitir a comité de evaluación y seguimiento', html)

    def test_exportacion_csv(self):
        self._autenticar(self.instructor)
        respuesta = self.cliente.get('/instructor/comite/fichas-terminadas?formato=csv')
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('attachment', respuesta.headers['Content-Disposition'])
        texto = respuesta.get_data(as_text=True)
        self.assertTrue(texto.startswith('﻿Ficha;'))
        self.assertIn('Ana Ríos', texto)

    def test_instructor_ajeno_no_ve_fichas_de_otros(self):
        self._autenticar(self.ajeno)
        html = self.cliente.get('/instructor/comite/fichas-terminadas').get_data(as_text=True)
        self.assertNotIn('Ana Ríos', html)
        self.assertIn('No hay fichas terminadas por fecha', html)

    def test_vista_requiere_sesion(self):
        self.assertEqual(self.cliente.get('/instructor/comite/fichas-terminadas').status_code, 302)


class FundamentoEnAlertasExistentesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}})
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        instructor = Instructor(nombre='I', correo='f@sena.edu.co', rol='admin')
        instructor.set_password('x')
        db.session.add(instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='F', nombre_programa='ADSO', instructor_id=instructor.id)
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendiz = Aprendiz(documento='1', nombre='Ana', apellidos='R', ficha_id=self.ficha.id)
        db.session.add(self.aprendiz)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _registros(self, dias, estado):
        for d in dias:
            sesion = SesionAsistencia(ficha_id=self.ficha.id, fecha=date.today() - timedelta(days=d))
            db.session.add(sesion)
            db.session.flush()
            db.session.add(RegistroAsistencia(sesion_id=sesion.id, aprendiz_id=self.aprendiz.id, estado=estado))
        db.session.commit()

    def _faltas(self, dias):
        self._registros(dias, 'FALTA')

    def _comite(self):
        return Alerta.query.filter_by(aprendiz_id=self.aprendiz.id, tipo='comite_desercion').all()

    def test_faltas_dentro_del_plazo_para_justificar_no_abren_comite(self):
        # Art. 28, par. 3: hay 5 días hábiles para excusarlas; aún no son injustificadas.
        self._faltas((2, 1, 0))
        actualizar_alertas_ficha(self.ficha.id)
        self.assertEqual(self._comite(), [])

    def test_tres_consecutivas_citan_articulo_30_pagina_30(self):
        self._faltas((23, 22, 21))
        actualizar_alertas_ficha(self.ficha.id)
        alertas = self._comite()
        self.assertEqual(len(alertas), 1)
        detalle = alertas[0].detalle_json
        # La causal reglamentaria prevalece sobre el umbral preventivo de porcentaje.
        self.assertEqual(detalle['motivo'], 'consecutivas_injustificadas')
        self.assertEqual(detalle['fundamento']['pagina'], 30)
        self.assertIn('Acuerdo 009 de 2024', detalle['reglamento'])
        self.assertIn('pág. 30', alertas[0].mensaje)

    def test_porcentaje_bajo_sin_causal_declara_que_no_tiene_respaldo(self):
        self._faltas((20, 14))
        self._registros((19, 18, 16, 15), 'ASISTE')
        actualizar_alertas_ficha(self.ficha.id)
        # El umbral preventivo no es causal de comité: es un aviso amarillo aparte.
        self.assertEqual(self._comite(), [])
        alerta = Alerta.query.filter_by(ficha_id=self.ficha.id, tipo='asistencia').one()
        self.assertEqual(alerta.nivel, 'amarilla')
        self.assertEqual(alerta.detalle_json['motivo'], 'porcentaje_asistencia')
        self.assertFalse(alerta.detalle_json['fundamento']['verificado'])
        self.assertIn('no fija un porcentaje', alerta.mensaje)

    def test_cinco_no_continuas_en_el_proceso_van_a_comite(self):
        # Ventana amplia: las faltas no caen en el trimestre, solo cuentan en el proceso.
        self._faltas((400, 300, 250, 200, 150))
        self._registros((350, 280, 220, 180) + tuple(range(1, 30)), 'ASISTE')
        actualizar_alertas_ficha(self.ficha.id)
        alertas = self._comite()
        self.assertEqual(len(alertas), 1)
        acumulada = alertas[0]
        self.assertEqual(acumulada.detalle_json['motivo'], 'acumuladas_proceso')
        self.assertEqual(acumulada.nivel, 'roja')
        self.assertEqual(acumulada.detalle_json['fundamento']['clave'], 'acumuladas_proceso')


if __name__ == '__main__':
    unittest.main()
