"""Ayudantes puros de las páginas de aseo (orden, resumen, mensajes y fechas)."""

import unittest
from datetime import date
from types import SimpleNamespace

from app.services.aseo_vista import (
    casilla_marcada,
    completados_del_formulario,
    fecha_formulario,
    mensaje_generacion,
    mes_consulta,
    mover_mes,
    nombre_mes,
    ordenar_equidad,
    resumen_cargas,
)


def fila(nombre, apellidos, total, periodo=0, ultima=None, proxima=None):
    return {
        'aprendiz': SimpleNamespace(nombre=nombre, apellidos=apellidos),
        'contador': SimpleNamespace(ultima_vez_aseo=ultima),
        'veces_total': total,
        'veces_periodo': periodo,
        'proxima': proxima,
    }


class OrdenarEquidadTest(unittest.TestCase):
    def setUp(self):
        self.ana = fila('Ana', 'Zea', 2, periodo=1, ultima=date(2026, 3, 2), proxima=date(2026, 4, 9))
        self.luis = fila('luis', 'arias', 1, periodo=1, ultima=None, proxima=None)
        self.eva = fila('Eva', 'Mora', 1, periodo=0, ultima=date(2026, 3, 1), proxima=date(2026, 4, 1))

    def nombres(self, orden):
        return [f['aprendiz'].nombre for f in ordenar_equidad([self.ana, self.luis, self.eva], orden)]

    def test_por_veces_es_el_orden_por_defecto(self):
        self.assertEqual(self.nombres('veces'), ['luis', 'Eva', 'Ana'])
        self.assertEqual(self.nombres(None), ['luis', 'Eva', 'Ana'])
        self.assertEqual(self.nombres('desconocido'), ['luis', 'Eva', 'Ana'])

    def test_por_nombre_ignora_mayusculas(self):
        self.assertEqual(self.nombres('nombre'), ['luis', 'Eva', 'Ana'])

    def test_por_periodo(self):
        self.assertEqual(self.nombres('periodo'), ['Eva', 'luis', 'Ana'])

    def test_por_ultima_vez_sin_fecha_primero(self):
        self.assertEqual(self.nombres('ultima'), ['luis', 'Eva', 'Ana'])

    def test_por_proxima_sin_fecha_al_final(self):
        self.assertEqual(self.nombres('proxima'), ['Eva', 'Ana', 'luis'])

    def test_devuelve_la_misma_lista_ordenada(self):
        filas = [self.ana, self.eva]
        self.assertIs(ordenar_equidad(filas, 'veces'), filas)
        self.assertEqual(filas, [self.eva, self.ana])


class ResumenCargasTest(unittest.TestCase):
    def test_con_cargas(self):
        self.assertEqual(resumen_cargas([3, 1, 2]), {'delta': 2, 'minimo': 1, 'maximo': 3, 'promedio': 2})

    def test_sin_aprendices(self):
        self.assertEqual(resumen_cargas([]), {'delta': 0, 'minimo': 0, 'maximo': 0, 'promedio': 0})


class MensajeGeneracionTest(unittest.TestCase):
    RESUMEN = {'minimo': 2, 'maximo': 3, 'delta': 1}

    def test_con_todos_los_cambios(self):
        resultado = {'creados': [1, 2], 'recalculados': [3], 'eliminados': 4, 'cumplidos_conservados': 5,
                     'omitidos_manuales': 6, 'sesiones': 9, 'sin_candidatos': [7]}
        mensaje, categoria = mensaje_generacion(resultado, [8, 9], self.RESUMEN)
        self.assertEqual(categoria, 'success')
        self.assertEqual(mensaje, (
            'Cálculo de turnos completado (4 pendiente(s) eliminado(s), 2 nuevo(s), 1 pendiente(s) recalculado(s), '
            '2 equilibrado(s) fuera del rango, 5 cumplido(s) conservado(s), 6 manual(es) conservado(s)) '
            'para 9 sesión(es). Equidad resultante: cada aprendiz tiene entre 2 y 3 turnos en total '
            '(diferencia de 1). 1 sesión(es) no tenían dos aprendices elegibles.'))

    def test_sin_cambios(self):
        mensaje, categoria = mensaje_generacion({'creados': [], 'sesiones': 4, 'sin_candidatos': []}, [], self.RESUMEN)
        self.assertEqual(categoria, 'info')
        self.assertTrue(mensaje.startswith('No se requirieron cambios en las 4 sesiones evaluadas. Equidad'))
        self.assertNotIn('elegibles', mensaje)

    def test_solo_conservados_no_es_exito(self):
        resultado = {'creados': [], 'cumplidos_conservados': 2, 'sesiones': 3}
        mensaje, categoria = mensaje_generacion(resultado, [], self.RESUMEN)
        self.assertEqual(categoria, 'info')
        self.assertIn('(2 cumplido(s) conservado(s))', mensaje)

    def test_solo_eliminados_es_exito(self):
        _, categoria = mensaje_generacion({'creados': [], 'eliminados': 1, 'sesiones': 1}, [], self.RESUMEN)
        self.assertEqual(categoria, 'success')


class FormularioTest(unittest.TestCase):
    def test_casilla_marcada(self):
        for valor in ('on', 'true', '1'):
            self.assertTrue(casilla_marcada({'x': valor}, 'x'))
        self.assertFalse(casilla_marcada({'x': 'off'}, 'x'))
        self.assertFalse(casilla_marcada({}, 'x'))
        self.assertTrue(casilla_marcada({}, 'x', defecto='on'), 'sin campo usa el valor por defecto')

    def test_completados_solo_si_el_formulario_los_trae(self):
        self.assertEqual(completados_del_formulario({}), (None, None))
        self.assertEqual(completados_del_formulario({'completado_1': 'on'}), (True, False))
        self.assertEqual(completados_del_formulario({'completado_2': '1'}), (False, True))

    def test_fecha_formulario(self):
        self.assertEqual(fecha_formulario('2026-04-09', 'fecha'), date(2026, 4, 9))
        for valor in (None, '', '09/04/2026'):
            with self.assertRaisesRegex(ValueError, 'La fecha final no es válida.'):
                fecha_formulario(valor, 'fecha final')


class MesesTest(unittest.TestCase):
    HOY = date(2026, 5, 17)

    def test_mes_consulta(self):
        self.assertEqual(mes_consulta('2026-02', self.HOY), date(2026, 2, 1))
        self.assertEqual(mes_consulta('febrero', self.HOY), date(2026, 5, 1))
        self.assertEqual(mes_consulta(None, self.HOY), date(2026, 5, 1))
        self.assertEqual(mes_consulta(None).day, 1, 'sin fecha de referencia usa hoy')

    def test_mover_mes_cruza_el_anio(self):
        self.assertEqual(mover_mes(date(2026, 1, 1), -1), date(2025, 12, 1))
        self.assertEqual(mover_mes(date(2026, 12, 1), 1), date(2027, 1, 1))
        self.assertEqual(mover_mes(date(2026, 6, 1), 0), date(2026, 6, 1))

    def test_nombre_mes(self):
        self.assertEqual(nombre_mes(date(2026, 9, 1)), 'Septiembre 2026')


if __name__ == '__main__':
    unittest.main()
