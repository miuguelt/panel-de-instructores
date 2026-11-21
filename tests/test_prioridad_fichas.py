"""Mis fichas: las fichas que requieren acción aparecen primero."""

import unittest
from types import SimpleNamespace

from app.services.prioridad_fichas import (
    ordenar_por_riesgo,
    ordenar_por_urgencia,
    pendientes_de_hoy,
    puntaje_urgencia,
    resumen_global,
)


def ficha(fid, codigo):
    return SimpleNamespace(id=fid, codigo=codigo)


LECTIVA = {'configurado': True, 'fase': 'lectiva', 'dias_cierre_ficha': 300}


class PuntajeTest(unittest.TestCase):
    def test_sin_pendientes_es_cero(self):
        self.assertEqual(puntaje_urgencia(LECTIVA, {}, {}), 0)

    def test_suma_alertas_entregas_vencidas_planes_y_desfase(self):
        extra = {'alertas_activas': 2, 'por_calificar': 4, 'pendientes': 1, 'planes_pendientes': 1}
        self.assertEqual(puntaje_urgencia(LECTIVA, extra, {'desfase_fases': 1}), 6 + 4 + 2 + 1 + 2)

    def test_por_calificar_tiene_tope(self):
        self.assertEqual(puntaje_urgencia(LECTIVA, {'por_calificar': 80}, None), 10)

    def test_cierre_inminente_suma(self):
        crono = dict(LECTIVA, dias_cierre_ficha=5)
        self.assertEqual(puntaje_urgencia(crono, {}, {}), 5)
        crono['dias_cierre_ficha'] = 40
        self.assertEqual(puntaje_urgencia(crono, {}, {}), 2)

    def test_desfase_negativo_no_resta(self):
        self.assertEqual(puntaje_urgencia(LECTIVA, {}, {'desfase_fases': -2}), 0)


class OrdenTest(unittest.TestCase):
    def test_urgentes_primero_y_finalizadas_al_final(self):
        fichas = [ficha(1, 'A'), ficha(2, 'B'), ficha(3, 'C'), ficha(4, 'D')]
        cronos = {1: LECTIVA, 2: LECTIVA, 3: {'configurado': True, 'fase': 'finalizada'},
                  4: {'configurado': True, 'fase': 'por_iniciar', 'dias_para_iniciar_lectiva': 90}}
        extra = {1: {}, 2: {'alertas_activas': 1}, 3: {'alertas_activas': 9}, 4: {}}
        orden = ordenar_por_urgencia(fichas, cronos, extra, {})
        self.assertEqual([f.codigo for f in orden], ['B', 'A', 'D', 'C'])

    def test_empate_respeta_fase_y_codigo(self):
        fichas = [ficha(1, 'Z'), ficha(2, 'A'), ficha(3, 'M')]
        cronos = {1: LECTIVA, 2: {'configurado': False, 'fase': 'sin_fechas'}, 3: LECTIVA}
        orden = ordenar_por_urgencia(fichas, cronos, {}, None)
        self.assertEqual([f.codigo for f in orden], ['M', 'Z', 'A'])


class PendientesTest(unittest.TestCase):
    def test_solo_pendientes_con_valor_en_orden_de_prioridad(self):
        extra = {'por_calificar': 3, 'alertas_activas': 0, 'pendientes': 2, 'planes_pendientes': 1}
        items = pendientes_de_hoy(extra)
        self.assertEqual([i['clave'] for i in items], ['por_calificar', 'pendientes', 'planes_pendientes'])
        self.assertEqual(items[0]['texto'], '3 entregas por calificar')
        self.assertEqual(items[1]['texto'], '2 entregas vencidas sin recibir')
        self.assertEqual(items[2]['texto'], '1 plan de mejoramiento abierto')
        self.assertEqual(items[0]['estado'], 'warning')

    def test_singular_y_alertas(self):
        items = pendientes_de_hoy({'alertas_activas': 1, 'por_calificar': 1})
        self.assertEqual(items[0]['texto'], '1 alerta activa')
        self.assertEqual(items[0]['estado'], 'danger')
        self.assertEqual(items[1]['texto'], '1 entrega por calificar')

    def test_vacio(self):
        self.assertEqual(pendientes_de_hoy({}), [])
        self.assertEqual(pendientes_de_hoy(None), [])


class ResumenGlobalTest(unittest.TestCase):
    def test_totales_de_fichas_activas(self):
        fichas = [ficha(1, 'A'), ficha(2, 'B'), ficha(3, 'C')]
        cronos = {1: dict(LECTIVA, dias_cierre_ficha=10), 2: LECTIVA, 3: {'configurado': True, 'fase': 'finalizada'}}
        extra = {1: {'por_calificar': 2, 'alertas_activas': 1}, 2: {'por_calificar': 3}, 3: {'por_calificar': 50}}
        self.assertEqual(resumen_global(fichas, cronos, extra), {
            'activas': 2, 'por_calificar': 5, 'alertas': 1, 'cierres_proximos': 1, 'con_pendientes': 2,
        })

    def test_sin_fichas(self):
        self.assertEqual(resumen_global([], {}, {})['activas'], 0)


class RiesgoTest(unittest.TestCase):
    def test_rojos_primero_luego_amarillos_y_por_faltas_y_apellido(self):
        datos = [
            {'nivel': 'verde', 'no_justificadas': 0, 'tareas_pendientes': 0, 'aprendiz': SimpleNamespace(apellidos='Arias')},
            {'nivel': 'rojo', 'no_justificadas': 4, 'tareas_pendientes': 3, 'aprendiz': SimpleNamespace(apellidos='Zapata')},
            {'nivel': 'amarillo', 'no_justificadas': 3, 'tareas_pendientes': 0, 'aprendiz': SimpleNamespace(apellidos='Mora')},
            {'nivel': 'rojo', 'no_justificadas': 7, 'tareas_pendientes': 0, 'aprendiz': SimpleNamespace(apellidos='Bello')},
            {'nivel': 'rojo', 'no_justificadas': 4, 'tareas_pendientes': 3, 'aprendiz': SimpleNamespace(apellidos='Cano')},
            {'nivel': 'otro', 'no_justificadas': 0, 'tareas_pendientes': 0, 'aprendiz': SimpleNamespace(apellidos='Ortiz')},
        ]
        orden = [d['aprendiz'].apellidos for d in ordenar_por_riesgo(datos)]
        self.assertEqual(orden, ['Bello', 'Cano', 'Zapata', 'Mora', 'Arias', 'Ortiz'])


if __name__ == '__main__':
    unittest.main()
