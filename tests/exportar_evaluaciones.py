"""Genera la página real con datos sintéticos aislados para pruebas de navegador."""

from datetime import date, datetime
from pathlib import Path

import openpyxl

from app import db
from app.models import Aprendiz, JuicioEvaluativo
from tests.apoyo_planeacion import crear_planeacion_xlsx
from tests.test_planeacion_ux import PlaneacionUXTestCase


def exportar(destino):
    caso = PlaneacionUXTestCase()
    caso.setUp()
    try:
        caso.ficha.fecha_inicio = date(2025, 7, 25)
        caso.ficha.fecha_fin = date(2027, 10, 24)
        ruta = crear_planeacion_xlsx(caso.archivos.name)
        libro = openpyxl.load_workbook(ruta)
        hoja = libro.active
        hoja['A20'] = 'ANÁLISIS'
        hoja['C20'] = 'Inducción'
        hoja['A21'] = 'PLANEACIÓN'
        hoja['B21'] = 'AP03. Socializar'
        hoja['C21'] = 'Inducción'
        hoja['D21'] = '601402 - Socializar el proyecto formativo.'
        hoja['I21'] = 20
        hoja['Q21'] = 'Trimestre 2'
        libro.save(ruta)
        grupo = [Aprendiz(ficha_id=caso.ficha.id, documento=str(100001 + i),
            nombre=nombre, apellidos='de prueba', estado='EN FORMACION')
            for i, nombre in enumerate(['Ángela', 'Beatriz', 'Carlos'])]
        db.session.add_all(grupo)
        db.session.flush()
        for persona, rap, juicio, evaluador in [
            (grupo[0], '601390', 'APROBADO', 'Instructor Uno'),
            (grupo[0], '601401', 'APROBADO', 'Instructor Dos'),
            (grupo[1], '601390', 'NO APROBADO', 'Instructor Tres'),
            (grupo[2], '601390', 'POR EVALUAR', 'Instructor previsto'),
        ]:
            db.session.add(JuicioEvaluativo(ficha_id=caso.ficha.id, aprendiz_id=persona.id,
                resultado_aprendizaje=rap + ' - Resultado de prueba', juicio=juicio,
                funcionario_registro=evaluador,
                fecha_juicio=datetime(2026, 9, 15) if juicio != 'POR EVALUAR' else None))
        db.session.commit()
        with ruta.open('rb') as archivo:
            respuesta = caso.cliente.post(f'/instructor/fichas/{caso.ficha.id}/planeacion/cargar',
                data={'archivo_planeacion': (archivo, ruta.name)}, content_type='multipart/form-data')
        assert respuesta.status_code == 302
        # La captura de consulta no necesita conservar la notificación de carga.
        with caso.cliente.session_transaction() as sesion:
            sesion.pop('_flashes', None)
        html = caso.pagina()
        assert 'data-evaluacion-target="tramo-0"' in html
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(html, encoding='utf-8')
    finally:
        caso.tearDown()


if __name__ == '__main__':
    exportar(Path(__file__).resolve().parents[1] / 'test-results' / 'evaluaciones-navegador.html')
