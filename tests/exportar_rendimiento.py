"""Exporta el directorio real con datos sintéticos para probar la carga en Chromium."""

from pathlib import Path

from tests.test_rendimiento import BaseRendimiento


def exportar(destino):
    caso = BaseRendimiento()
    caso.APRENDICES, caso.SESIONES, caso.TAREAS = 4, 0, 2
    caso.setUp()
    try:
        respuesta = caso.cliente.get(f'/instructor/fichas/{caso.ficha.id}/aprendices')
        assert respuesta.status_code == 200
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(respuesta.get_data(as_text=True), encoding='utf-8')
    finally:
        caso.tearDown()


if __name__ == '__main__':
    exportar(Path(__file__).resolve().parents[1] / 'test-results' / 'aprendices-navegador.html')
