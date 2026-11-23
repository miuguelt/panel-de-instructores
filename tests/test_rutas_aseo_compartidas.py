"""Pasos que comparten las rutas de aseo del instructor, del delegado y del aprendiz."""

import unittest
from datetime import date, timedelta

from flask import url_for

from app import db
from app.models import Aprendiz, Ficha, TurnoAseo
from app.models.aseo import ConfiguracionAseo, ContadorAseo
from tests import test_aprendiz_administrador as base


class RutasAseoCompartidasTest(unittest.TestCase):
    # Toma la preparación de esa suite sin heredar (ni volver a ejecutar) sus pruebas.
    setUp = base.AprendizAdministradorTestCase.setUp
    tearDown = base.AprendizAdministradorTestCase.tearDown
    _sesion_aprendiz = base.AprendizAdministradorTestCase._sesion_aprendiz
    _sesion_instructor = base.AprendizAdministradorTestCase._sesion_instructor

    def _mensajes(self):
        with self.cliente.session_transaction() as estado:
            return [texto for _, texto in estado.pop('_flashes', [])]

    def _turno(self, dias=3):
        ana, bruno, _ = self.aprendices
        turno = TurnoAseo(ficha_id=self.ficha.id, fecha=date.today() + timedelta(days=dias),
                          aprendiz_1_id=ana.id, aprendiz_2_id=bruno.id)
        db.session.add(turno)
        db.session.commit()
        return turno

    def _instructor(self, ruta, **datos):
        self._sesion_instructor()
        return self.cliente.post(f'/instructor/fichas/{self.ficha.id}/turnos-aseo{ruta}', data=datos)

    def test_instructor_no_puede_asignar_aprendices_de_otra_ficha(self):
        otra = Ficha(codigo='3000000', codigo_ficha='3000000', nombre_programa='Otra',
                     instructor_id=self.instructor.id, fecha_inicio=date.today())
        db.session.add(otra)
        db.session.flush()
        ajeno = Aprendiz(documento='777', nombre='Ajeno', apellidos='Prueba', ficha_id=otra.id, estado='EN_FORMACION')
        db.session.add(ajeno)
        db.session.commit()
        turno = self._turno()

        respuesta = self._instructor(f'/{turno.id}/editar', aprendiz_1_id=ajeno.id,
                                     aprendiz_2_id=self.aprendices[2].id)

        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('Selecciona dos aprendices válidos.', self._mensajes())
        db.session.refresh(turno)
        self.assertEqual((turno.aprendiz_1_id, turno.aprendiz_2_id), (self.aprendices[0].id, self.aprendices[1].id))

    def test_instructor_edita_con_aprendices_de_la_ficha(self):
        turno = self._turno()
        self._instructor(f'/{turno.id}/editar', aprendiz_1_id=self.aprendices[2].id,
                         aprendiz_2_id=self.aprendices[1].id, observacion='Cambio pedido')
        db.session.refresh(turno)
        self.assertEqual({turno.aprendiz_1_id, turno.aprendiz_2_id}, {self.aprendices[2].id, self.aprendices[1].id})

    def test_turno_de_otra_ficha_no_se_encuentra(self):
        respuesta = self._instructor('/999999/cumplir')
        with self.app.test_request_context():
            self.assertEqual(respuesta.headers['Location'], url_for('instructor.dashboard'))
        self.assertIn('Turno no encontrado.', self._mensajes())

    def test_configuracion_valida_y_numero_invalido(self):
        self._instructor('/config', aviso_horas='999', excluir_ausentes='true')
        config = ConfiguracionAseo.query.filter_by(ficha_id=self.ficha.id).one()
        self.assertEqual((config.aviso_horas, config.excluir_ausentes), (720, True))

        self._instructor('/config', aviso_horas='muchas')
        self.assertIn('Las horas de aviso deben ser un número entero.', self._mensajes())
        db.session.refresh(config)
        self.assertEqual(config.aviso_horas, 720)

    def test_exclusion_temporal_fecha_invalida_y_regreso_a_la_cola(self):
        ana = self.aprendices[0]
        ruta = f'/exclusion/{ana.id}'
        contador = lambda: ContadorAseo.query.filter_by(ficha_id=self.ficha.id, aprendiz_id=ana.id).one()  # noqa: E731

        self._instructor(ruta, excluido_hasta='2026-12-31', motivo='Incapacidad')
        db.session.expire_all()
        self.assertEqual((contador().excluido_hasta, contador().motivo_exclusion), (date(2026, 12, 31), 'Incapacidad'))

        self._mensajes()
        self._instructor(ruta, excluido_hasta='31/12/2026')
        self.assertIn('La fecha de exclusión no es válida.', self._mensajes())
        db.session.expire_all()
        self.assertEqual(contador().excluido_hasta, date(2026, 12, 31))

        self._instructor(ruta)
        db.session.expire_all()
        self.assertIsNone(contador().excluido_hasta)
        self.assertIn('Ana Prueba volvió a la cola justa.', self._mensajes())

    def test_delegado_vuelve_a_transparencia_y_fecha_invalida_a_la_gestion(self):
        self.aprendices[0].rol_administrativo = True
        db.session.commit()
        self._sesion_aprendiz()
        inicio = date.today() + timedelta(days=1)
        ok = self.cliente.post(f'/aprendiz/{self.ficha.id}/turnos-aseo/generar', data={
            'fecha_inicio': inicio.isoformat(), 'fecha_fin': inicio.isoformat(), 'origen': 'transparencia'})
        self.assertIn(f'/aprendiz/{self.ficha.id}/turnos-aseo?mes={inicio:%Y-%m}', ok.headers['Location'])

        error = self.cliente.post(f'/aprendiz/{self.ficha.id}/turnos-aseo/generar',
                                  data={'fecha_inicio': 'ayer', 'fecha_fin': inicio.isoformat()})
        self.assertTrue(error.headers['Location'].endswith(f'/aprendiz/{self.ficha.id}/turnos-aseo/gestionar'))
        self.assertIn('La fecha inicial no es válida.', self._mensajes())

    def test_las_tres_paginas_muestran_el_mismo_calendario(self):
        self._turno(dias=0)
        self._sesion_instructor()
        instructor = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/turnos-aseo?orden=nombre')
        self.aprendices[0].rol_administrativo = True
        db.session.commit()
        self._sesion_aprendiz()
        gestion = self.cliente.get(f'/aprendiz/{self.ficha.id}/turnos-aseo/gestionar?mes=1900-13')
        transparencia = self.cliente.get(f'/aprendiz/{self.ficha.id}/turnos-aseo?orden=proxima')
        for respuesta in (instructor, gestion, transparencia):
            self.assertEqual(respuesta.status_code, 200)
            self.assertIn('Ana Prueba', respuesta.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
