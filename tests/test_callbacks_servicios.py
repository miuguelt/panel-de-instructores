"""Verificación del orden de fases adicionales mediante el recorrido real de la planeación."""

from datetime import date, datetime

import openpyxl

from app import db
from app.models import JuicioEvaluativo
from app.services.analisis_planeacion import construir_analisis
from app.services.calendario_formacion import construir_calendario
from app.services.linea_tiempo import construir_linea_tiempo
from app.services.planeacion import parsear_planeacion
from app.services.seguimiento_fases import construir_seguimiento_fases
from tests import test_archivos as soporte
from tests.apoyo_planeacion import crear_planeacion_xlsx


def test_fases_adicionales_se_ordenan_y_conservan_los_resultados_del_excel_y_la_bd():
    caso = soporte.ArchivosTestCase()
    caso.setUp()
    try:
        caso.ficha.fecha_inicio = date(2025, 7, 25)
        caso.ficha.fecha_fin = date(2027, 10, 24)
        ruta = crear_planeacion_xlsx(caso.uploads.name)
        libro = openpyxl.load_workbook(ruta)
        libro['PLANEACION']['A18'] = 'VALIDACIÓN'
        libro['PLANEACION']['A20'] = 'APRESTAMIENTO'
        libro.save(ruta)
        libro.close()
        contenido = parsear_planeacion(ruta)
        unidad_aprobada = contenido['unidades'][0]
        db.session.add(JuicioEvaluativo(
            ficha_id=caso.ficha.id, aprendiz_id=caso.aprendiz.id,
            competencia=unidad_aprobada['competencia'],
            resultado_aprendizaje=unidad_aprobada['rap'], juicio='APROBADO',
            fecha_juicio=datetime(2025, 9, 10, 8),
        ))
        db.session.commit()
        hoy = date(2026, 8, 18)
        analisis = construir_analisis(caso.ficha, contenido, hoy=hoy)
        calendario = construir_calendario(caso.ficha, hoy=hoy)
        linea = construir_linea_tiempo(analisis['items'], calendario,
                                      aprendices_meta=1, hoy=hoy)
        seguimiento = construir_seguimiento_fases(linea, calendario, hoy=hoy)

        fases_adicionales = [fase for fase in seguimiento['fases'] if fase['planificada']]
        assert [fase['nombre'] for fase in fases_adicionales] == ['APRESTAMIENTO', 'VALIDACIÓN']
        assert [fase['horas'] for fase in fases_adicionales] == [25.0, 22.0]
        assert [fase['resultados_total'] for fase in fases_adicionales] == [1, 1]
        assert [fase['resultados_aprobados'] for fase in fases_adicionales] == [0, 1]
        assert seguimiento['resultados']['total'] == 2
        assert seguimiento['resultados']['evaluados'] == 1
        assert seguimiento['resultados']['aprobados'] == 1
        assert all(not fase['planificada'] for fase in seguimiento['fases'][:4])
    finally:
        caso.tearDown()
