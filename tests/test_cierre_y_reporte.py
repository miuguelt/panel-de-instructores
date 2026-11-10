import io
import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from flask import g
from openpyxl import load_workbook

from app import create_app, db
from app.models import (
    Alerta, Aprendiz, Ficha, Instructor, JuicioEvaluativo, LlamadoAtencion, PlanMejoramiento,
)
from app.services import cierre_lectivo as cl
from app.services import novedades as nv
from app.services.reporte_coordinacion import (
    COLUMNAS_NOVEDADES, COLUMNAS_REMISIONES, COLUMNAS_RESUMEN, construir_reporte,
)


def _app():
    return create_app({
        'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False,
    })


def _ficha_con_fin_lectiva(fin_lectiva):
    """Ficha cuya etapa lectiva termina en `fin_lectiva` (productiva de 6 meses)."""
    fin = nv.sumar_meses(fin_lectiva + timedelta(days=1), 6)
    return SimpleNamespace(fecha_inicio=fin_lectiva - timedelta(days=600), fecha_fin=fin,
                           duracion_productiva_meses=6)


class PurasCierreTest(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.contexto = self.app.app_context()
        self.contexto.push()

    def tearDown(self):
        self.contexto.pop()

    def test_ventana_de_60_y_30_dias(self):
        hoy = date(2026, 11, 9)
        casos = ((61, None), (60, 'amarilla'), (31, 'amarilla'), (30, 'roja'), (0, 'roja'), (-1, None))
        for dias, nivel in casos:
            with self.subTest(dias=dias):
                ficha = _ficha_con_fin_lectiva(hoy + timedelta(days=dias))
                ventana = cl.ventana_cierre(ficha, hoy)
                self.assertEqual(ventana[0] if ventana else None, nivel)
                if ventana:
                    self.assertEqual(ventana[1], dias)
        sin_fechas = SimpleNamespace(fecha_inicio=None, fecha_fin=None, duracion_productiva_meses=6)
        self.assertIsNone(cl.ventana_cierre(sin_fechas, hoy))

    def test_resultados_pendientes_cuenta_rap_sin_aprobacion(self):
        filas = [
            (1, 'C1', 'RAP 1', 'APROBADO'),
            (1, 'C1', 'RAP 1', 'POR EVALUAR'),
            (1, 'C1', 'RAP 2', 'NO APROBADO'),
            (1, 'C2', 'RAP 3', None),
            (2, 'C1', 'RAP 1', 'APROBADO'),
        ]
        # La ficha tiene tres resultados. Al aprendiz 2 le faltan RAP 2 y RAP 3,
        # y el 3, sin ningún juicio, los tiene todos pendientes.
        self.assertEqual(cl.resultados_pendientes(filas, [1, 2, 3]), {1: 2, 2: 2, 3: 3})
        self.assertEqual(cl.resultados_pendientes([], [7]), {7: 0})

    def test_mensaje_de_cierre_solo_cita_productiva_si_falta_planeacion(self):
        ventana = ('roja', 20, date(2026, 11, 29))
        aprendiz = Aprendiz(nombre='Ana', apellidos='R', estado='EN_FORMACION')
        avalada = SimpleNamespace(planeacion_avalada=True)
        con_aval = cl.evaluar_aprendiz_cierre(aprendiz, ventana, 2, avalada)
        self.assertNotIn('Art. 30', con_aval['mensaje'])
        sin_aval = cl.evaluar_aprendiz_cierre(aprendiz, ventana, 2, None)
        self.assertIn('Art. 30, num. 2', sin_aval['mensaje'])

    def test_evaluar_aprendiz(self):
        ventana = ('roja', 20, date(2026, 11, 29))
        aprendiz = Aprendiz(nombre='Ana', apellidos='R', estado='EN_FORMACION')
        avalada = SimpleNamespace(planeacion_avalada=True)
        self.assertIsNone(cl.evaluar_aprendiz_cierre(aprendiz, None, 3, None))
        self.assertIsNone(cl.evaluar_aprendiz_cierre(aprendiz, ventana, 0, avalada))
        solo_rap = cl.evaluar_aprendiz_cierre(aprendiz, ventana, 2, avalada)
        self.assertIn('2 resultado(s)', solo_rap['mensaje'])
        self.assertNotIn('sin aval', solo_rap['mensaje'])
        ambos = cl.evaluar_aprendiz_cierre(aprendiz, ventana, 1, None)
        self.assertIn('sin aval registrado', ambos['mensaje'])
        self.assertEqual(ambos['nivel'], 'roja')
        self.assertTrue(ambos['detalle']['sin_planeacion_productiva'])
        aprendiz.estado = 'CERTIFICADO'
        self.assertIsNone(cl.evaluar_aprendiz_cierre(aprendiz, ventana, 1, None))


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        self.instructor = Instructor(nombre='Instructor', correo='cr@sena.edu.co', rol='admin')
        self.instructor.set_password('clave-segura')
        self.ajeno = Instructor(nombre='Ajeno', correo='aj2@sena.edu.co', rol='colaborador')
        self.ajeno.set_password('clave-segura')
        db.session.add_all([self.instructor, self.ajeno])
        db.session.flush()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _ficha(self, codigo, **fechas):
        ficha = Ficha(codigo=codigo, nombre_programa='ADSO', instructor_id=self.instructor.id, **fechas)
        db.session.add(ficha)
        db.session.flush()
        return ficha

    def _aprendiz(self, ficha, documento, estado='EN_FORMACION'):
        aprendiz = Aprendiz(documento=documento, nombre=f'N{documento}', apellidos='Prueba',
                            ficha_id=ficha.id, estado=estado)
        db.session.add(aprendiz)
        db.session.flush()
        return aprendiz


class AlertaCierreIntegracionTest(BaseTest):
    def test_crea_alerta_con_fundamento_y_la_resuelve_al_cumplir(self):
        from app.services.alertas import actualizar_alertas_ficha
        plantilla = _ficha_con_fin_lectiva(date.today() + timedelta(days=20))
        ficha = self._ficha('CL1', fecha_inicio=plantilla.fecha_inicio, fecha_fin=plantilla.fecha_fin)
        aprendiz = self._aprendiz(ficha, '1')
        db.session.add(JuicioEvaluativo(ficha_id=ficha.id, aprendiz_id=aprendiz.id, competencia='C1',
                                        resultado_aprendizaje='RAP 1', juicio='POR EVALUAR'))
        db.session.commit()
        actualizar_alertas_ficha(ficha.id)
        alerta = Alerta.query.filter_by(tipo=cl.TIPO_ALERTA).one()
        self.assertEqual(alerta.nivel, 'roja')
        self.assertEqual(alerta.detalle_json['resultados_pendientes'], 1)
        self.assertEqual(alerta.detalle_json['fundamento']['pagina'], 31)

        JuicioEvaluativo.query.update({'juicio': 'APROBADO'})
        nv.registrar_etapa_productiva(aprendiz, ficha, 'pasantia', planeacion_avalada=True,
                                      fecha_aval=date.today())
        actualizar_alertas_ficha(ficha.id)
        self.assertEqual(Alerta.query.filter_by(tipo=cl.TIPO_ALERTA).one().estado, 'resuelta')

    def test_fuera_de_la_ventana_no_consulta_juicios_ni_alerta(self):
        from unittest.mock import patch
        ficha = self._ficha('CL2', fecha_inicio=date.today() - timedelta(days=30),
                            fecha_fin=date.today() + timedelta(days=900))
        aprendiz = self._aprendiz(ficha, '2')
        db.session.commit()
        with patch.object(cl, 'cargar_pendientes') as cargar:
            self.assertEqual(cl.actualizar_alertas_cierre(ficha, date.today(), [aprendiz], {}), 0)
        cargar.assert_not_called()


class ReporteCoordinacionTest(BaseTest):
    def setUp(self):
        super().setUp()
        hoy = date.today()
        self.terminada = self._ficha('R1', fecha_inicio=hoy - timedelta(days=800),
                                     fecha_fin=hoy - timedelta(days=30))
        self.pendiente = self._aprendiz(self.terminada, '10')
        self.aplazado = self._aprendiz(self.terminada, '11', 'APLAZADO')
        self._aprendiz(self.terminada, '12', 'CERTIFICADO')
        self.antigua = self._ficha('R0', fecha_inicio=hoy - timedelta(days=1500),
                                   fecha_fin=hoy - timedelta(days=400))
        self._aprendiz(self.antigua, '20')
        db.session.commit()
        nv.registrar_novedad(self.aplazado, self.terminada, 'aplazamiento', hoy - timedelta(days=80),
                             'autorizada', hoy - timedelta(days=80), hoy - timedelta(days=2), 'judicial')
        db.session.add_all([
            LlamadoAtencion(aprendiz_id=self.pendiente.id, ficha_id=self.terminada.id, tipo='academico',
                            numero=1, fecha=hoy, descripcion='x'),
            PlanMejoramiento(aprendiz_id=self.pendiente.id, ficha_id=self.terminada.id, actividades='x'),
            Alerta(ficha_id=self.terminada.id, aprendiz_id=self.pendiente.id, tipo='academica',
                   nivel='roja', titulo='t', mensaje='m', estado='escalada_comite'),
        ])
        db.session.commit()

    def _libro(self, fichas):
        return load_workbook(io.BytesIO(construir_reporte(fichas)))

    def test_hojas_columnas_y_conteos(self):
        libro = self._libro([self.terminada, self.antigua])
        self.assertEqual(libro.sheetnames, ['Resumen por ficha', 'Remisiones', 'Aplazamientos'])
        resumen = list(libro['Resumen por ficha'].values)
        self.assertEqual(resumen[0], COLUMNAS_RESUMEN)
        r0, r1 = resumen[1], resumen[2]
        self.assertEqual((r0[0], r1[0]), ('R0', 'R1'))
        self.assertEqual(r0[12], 1)  # cancelación administrativa en la ficha antigua
        self.assertEqual(r1[3], 3)
        self.assertEqual(r1[5:9], (1, 1, 1, 1))
        # El aplazamiento venció: al aplazado también le aplica el Art. 30 num. 2.
        self.assertEqual(r1[11], 2)  # remisiones por etapa productiva
        self.assertEqual(r1[13], 1)  # remisión por reintegro
        self.assertIn('Certificado: 1', r1[4])

        remisiones = list(libro['Remisiones'].values)
        self.assertEqual(remisiones[0], COLUMNAS_REMISIONES)
        causales = {fila[4] for fila in remisiones[1:]}
        self.assertEqual(causales, {'Etapa productiva no culminada', 'Reintegro no gestionado'})
        self.assertTrue(all(isinstance(fila[8], int) for fila in remisiones[1:]))

        aplazamientos = list(libro['Aplazamientos'].values)
        self.assertEqual(aplazamientos[0], COLUMNAS_NOVEDADES)
        self.assertEqual(aplazamientos[1][1], '11')
        self.assertEqual(aplazamientos[1][8], 'No')

    def test_ficha_sin_fecha_y_sin_registros(self):
        vacia = self._ficha('R9')
        db.session.commit()
        libro = self._libro([vacia])
        self.assertEqual(list(libro['Resumen por ficha'].values)[1][2], 'Sin fecha')
        self.assertEqual(libro['Remisiones'].max_row, 1)

    def test_ruta_descarga_y_aislamiento_por_instructor(self):
        cliente = self.app.test_client()
        g.pop('_login_user', None)
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
        respuesta = cliente.get('/instructor/comite/reporte-coordinacion.xlsx')
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('attachment', respuesta.headers['Content-Disposition'])
        codigos = [f[0] for f in list(load_workbook(io.BytesIO(respuesta.data))['Resumen por ficha'].values)[1:]]
        self.assertEqual(codigos, ['R0', 'R1'])
        g.pop('_login_user', None)
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.ajeno.id)
        ajeno = cliente.get('/instructor/comite/reporte-coordinacion.xlsx')
        self.assertEqual(load_workbook(io.BytesIO(ajeno.data))['Resumen por ficha'].max_row, 1)


if __name__ == '__main__':
    unittest.main()
