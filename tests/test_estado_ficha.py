"""Contrato del estado de la ficha: fechas, fase esperada, avance y próximo hito."""

import unittest
from datetime import date

from datetime import datetime, timezone

from app.services.estado_ficha import construir_estado_ficha, fecha_local


HOY = date(2026, 6, 15)


def calendario(**cambios):
    base = {
        'configurado': True,
        'inicio': date(2026, 1, 1),
        'fin_lectiva': date(2026, 12, 31),
        'inicio_productiva': date(2027, 1, 1),
        'fin': date(2027, 6, 30),
        'dias_restantes_lectiva': 199,
        'porcentaje_lectiva': 45.5,
        'bloque_actual': {'etiqueta': 'T2', 'etapa': 'lectiva', 'fin': date(2026, 6, 30)},
    }
    base.update(cambios)
    return base


def fase(nombre, inicio, fin, orden=0):
    return {'nombre': nombre, 'icono': '⚙️', 'orden': orden, 'inicio': inicio, 'fin': fin}


def seguimiento(**cambios):
    base = {
        'estado': 'atrasado',
        'fase_esperada': fase('EJECUCIÓN', date(2026, 5, 1), date(2026, 9, 30), 2),
        'fase_real': fase('PLANEACIÓN', date(2026, 3, 1), date(2026, 4, 30), 1),
        'resultados': {
            'total': 40, 'evaluados': 14, 'aprobados': 10, 'pendientes': 30,
            'porcentaje_evaluados': 35, 'porcentaje_aprobados': 25,
        },
    }
    base.update(cambios)
    return base


class FechasClaveTestCase(unittest.TestCase):
    def test_lista_las_cuatro_fechas_con_dias_y_estado(self):
        estado = construir_estado_ficha(calendario(), seguimiento(), HOY)
        fechas = {item['clave']: item for item in estado['fechas']}
        self.assertEqual(list(fechas), ['inicio', 'fin_lectiva', 'inicio_productiva', 'fin'])
        self.assertEqual(fechas['inicio']['estado'], 'pasada')
        self.assertEqual(fechas['inicio']['dias'], -165)
        self.assertEqual(fechas['fin_lectiva']['estado'], 'futura')
        self.assertEqual(fechas['fin_lectiva']['dias'], 199)
        self.assertEqual(fechas['fin']['dias'], 380)
        self.assertEqual(estado['dias_para_fin_ficha'], 380)
        self.assertEqual(estado['dias_para_productiva'], 200)

    def test_una_fecha_que_coincide_con_hoy_se_marca_como_hoy(self):
        estado = construir_estado_ficha(calendario(fin_lectiva=HOY), seguimiento(), HOY)
        fin_lectiva = next(item for item in estado['fechas'] if item['clave'] == 'fin_lectiva')
        self.assertEqual(fin_lectiva['estado'], 'hoy')
        self.assertEqual(fin_lectiva['dias'], 0)

    def test_una_fecha_faltante_no_se_inventa(self):
        estado = construir_estado_ficha(calendario(inicio_productiva=None), seguimiento(), HOY)
        productiva = next(item for item in estado['fechas'] if item['clave'] == 'inicio_productiva')
        self.assertIsNone(productiva['fecha'])
        self.assertIsNone(productiva['dias'])
        self.assertEqual(productiva['estado'], 'sin_fecha')
        self.assertIsNone(estado['dias_para_productiva'])

    def test_calendario_no_configurado_no_entrega_datos(self):
        estado = construir_estado_ficha({'configurado': False}, seguimiento(), HOY)
        self.assertFalse(estado['disponible'])
        self.assertEqual(estado['fechas'], [])
        self.assertIsNone(estado['proximo_hito'])
        self.assertIsNone(estado['semanas_lectivas_restantes'])
        self.assertIsNone(estado['rap_por_semana'])
        self.assertIsNone(estado['avance'])

    def test_calendario_ausente_equivale_a_no_configurado(self):
        estado = construir_estado_ficha(None, None, HOY)
        self.assertFalse(estado['disponible'])
        self.assertIsNone(estado['fase_esperada'])


class FaseEsperadaTestCase(unittest.TestCase):
    def test_fase_en_curso_informa_fechas_y_dias_restantes(self):
        estado = construir_estado_ficha(calendario(), seguimiento(), HOY)
        esperada = estado['fase_esperada']
        self.assertEqual(esperada['nombre'], 'EJECUCIÓN')
        self.assertEqual(esperada['inicio'], date(2026, 5, 1))
        self.assertEqual(esperada['fin'], date(2026, 9, 30))
        self.assertEqual(esperada['momento'], 'en_curso')
        self.assertEqual(esperada['dias_restantes'], 107)
        self.assertIsNone(esperada['dias_para_inicio'])
        self.assertEqual(estado['fase_real']['nombre'], 'PLANEACIÓN')
        self.assertFalse(estado['fases_coinciden'])

    def test_fase_futura_cuenta_dias_para_iniciar(self):
        futura = fase('ANÁLISIS', date(2026, 7, 1), date(2026, 8, 31))
        estado = construir_estado_ficha(calendario(), seguimiento(fase_esperada=futura, fase_real=futura), HOY)
        self.assertEqual(estado['fase_esperada']['momento'], 'por_iniciar')
        self.assertEqual(estado['fase_esperada']['dias_para_inicio'], 16)
        self.assertTrue(estado['fases_coinciden'])

    def test_fase_ya_terminada_informa_dias_desde_el_cierre(self):
        pasada = fase('EVALUACIÓN', date(2026, 1, 1), date(2026, 6, 5), 3)
        estado = construir_estado_ficha(calendario(), seguimiento(fase_esperada=pasada), HOY)
        self.assertEqual(estado['fase_esperada']['momento'], 'terminada')
        self.assertEqual(estado['fase_esperada']['dias_desde_fin'], 10)
        self.assertIsNone(estado['fase_esperada']['dias_restantes'])

    def test_fase_sin_ventana_no_inventa_dias(self):
        sin_fechas = fase('EJECUCIÓN', None, None)
        estado = construir_estado_ficha(calendario(), seguimiento(fase_esperada=sin_fechas), HOY)
        self.assertEqual(estado['fase_esperada']['momento'], 'sin_fecha')
        self.assertIsNone(estado['fase_esperada']['dias_restantes'])
        self.assertIsNone(estado['fase_esperada']['dias_para_inicio'])

    def test_sin_fases_calculables(self):
        estado = construir_estado_ficha(calendario(), seguimiento(fase_esperada=None, fase_real=None), HOY)
        self.assertIsNone(estado['fase_esperada'])
        self.assertIsNone(estado['fase_real'])
        self.assertFalse(estado['fases_coinciden'])


class AvanceTestCase(unittest.TestCase):
    def test_compara_tiempo_evaluados_y_cerrados_en_la_misma_escala(self):
        avance = construir_estado_ficha(calendario(), seguimiento(), HOY)['avance']
        self.assertEqual(avance['tiempo'], 45.5)
        self.assertEqual(avance['evaluados'], 35)
        self.assertEqual(avance['cerrados'], 25)
        self.assertEqual(avance['brecha_puntos'], 20.5)
        self.assertEqual(avance['tono'], 'danger')

    def test_tono_sigue_el_estado_del_seguimiento(self):
        tonos = {
            'al_dia': 'success', 'adelantado': 'success', 'completado': 'success',
            'atrasado': 'danger', 'sin_datos': 'info',
        }
        for estado_fase, tono in tonos.items():
            with self.subTest(estado=estado_fase):
                avance = construir_estado_ficha(calendario(), seguimiento(estado=estado_fase), HOY)['avance']
                self.assertEqual(avance['tono'], tono)

    def test_sin_resultados_el_avance_no_tiene_porcentajes_de_rap(self):
        vacio = seguimiento(resultados={'total': 0, 'pendientes': 0})
        avance = construir_estado_ficha(calendario(), vacio, HOY)['avance']
        self.assertEqual(avance['tiempo'], 45.5)
        self.assertIsNone(avance['evaluados'])
        self.assertIsNone(avance['cerrados'])
        self.assertIsNone(avance['brecha_puntos'])

    def test_sin_seguimiento_conserva_solo_el_tiempo(self):
        estado = construir_estado_ficha(calendario(), None, HOY)
        self.assertEqual(estado['avance']['tiempo'], 45.5)
        self.assertIsNone(estado['avance']['cerrados'])
        self.assertEqual(estado['avance']['tono'], 'info')
        self.assertIsNone(estado['rap_por_semana'])


class RitmoNecesarioTestCase(unittest.TestCase):
    def test_rap_por_semana_reparte_los_rap_sin_evaluar_en_las_semanas_restantes(self):
        estado = construir_estado_ficha(calendario(dias_restantes_lectiva=70), seguimiento(), HOY)
        self.assertEqual(estado['semanas_lectivas_restantes'], 10.0)
        self.assertEqual(estado['rap_sin_evaluar'], 26)
        self.assertEqual(estado['rap_por_semana'], 2.6)

    def test_sin_rap_por_evaluar_no_hace_falta_ritmo(self):
        cerrado = seguimiento(resultados={'total': 40, 'evaluados': 40, 'porcentaje_evaluados': 100,
                                          'porcentaje_aprobados': 100})
        estado = construir_estado_ficha(calendario(), cerrado, HOY)
        self.assertEqual(estado['rap_sin_evaluar'], 0)
        self.assertEqual(estado['rap_por_semana'], 0)

    def test_ritmo_actual_se_expresa_por_semana(self):
        con_ritmo = seguimiento(proyeccion={'ritmo_mensual': 4.35})
        self.assertEqual(construir_estado_ficha(calendario(), con_ritmo, HOY)['rap_por_semana_actual'], 1.0)
        self.assertIsNone(construir_estado_ficha(calendario(), seguimiento(), HOY)['rap_por_semana_actual'])
        sin_calendario = construir_estado_ficha({'configurado': False}, con_ritmo, HOY)
        self.assertEqual(sin_calendario['rap_por_semana_actual'], 1.0)
        self.assertEqual(sin_calendario['rap_sin_evaluar'], 26)

    def test_sin_semanas_restantes_el_ritmo_no_es_calculable(self):
        estado = construir_estado_ficha(calendario(dias_restantes_lectiva=0), seguimiento(), HOY)
        self.assertEqual(estado['semanas_lectivas_restantes'], 0)
        self.assertIsNone(estado['rap_por_semana'])


class ProximoHitoTestCase(unittest.TestCase):
    def test_elige_la_fecha_futura_mas_cercana(self):
        hito = construir_estado_ficha(calendario(), seguimiento(), HOY)['proximo_hito']
        self.assertEqual(hito['etiqueta'], 'Fin del trimestre T2')
        self.assertEqual(hito['fecha'], date(2026, 6, 30))
        self.assertEqual(hito['dias'], 15)

    def test_ignora_fechas_pasadas_y_considera_el_fin_de_la_fase(self):
        cal = calendario(bloque_actual={'etiqueta': 'T2', 'etapa': 'lectiva', 'fin': date(2026, 6, 1)})
        temprana = fase('EJECUCIÓN', date(2026, 5, 1), date(2026, 6, 20))
        hito = construir_estado_ficha(cal, seguimiento(fase_esperada=temprana), HOY)['proximo_hito']
        self.assertEqual(hito['etiqueta'], 'Fin de la fase EJECUCIÓN')
        self.assertEqual(hito['dias'], 5)

    def test_en_empate_gana_el_primer_hito_en_orden_de_lectura(self):
        cal = calendario(bloque_actual={'etiqueta': 'T4', 'etapa': 'lectiva', 'fin': date(2026, 12, 31)})
        sin_fin = fase('EJECUCIÓN', date(2026, 5, 1), None)
        hito = construir_estado_ficha(cal, seguimiento(fase_esperada=sin_fin), HOY)['proximo_hito']
        self.assertEqual(hito['etiqueta'], 'Fin del trimestre T4')

    def test_en_etapa_productiva_no_cuenta_el_trimestre(self):
        cal = calendario(
            inicio=date(2025, 1, 1), fin_lectiva=date(2025, 12, 31), inicio_productiva=date(2026, 1, 1),
            fin=date(2026, 6, 30), dias_restantes_lectiva=0, porcentaje_lectiva=100,
            bloque_actual={'etiqueta': 'EP', 'etapa': 'productiva', 'fin': date(2026, 6, 30)},
        )
        estado = construir_estado_ficha(cal, seguimiento(fase_esperada=None), HOY)
        self.assertEqual(estado['proximo_hito']['etiqueta'], 'Fin de la ficha')
        self.assertEqual(estado['proximo_hito']['dias'], 15)

    def test_ficha_terminada_no_tiene_proximo_hito(self):
        cal = calendario(
            inicio=date(2024, 1, 1), fin_lectiva=date(2024, 12, 31), inicio_productiva=date(2025, 1, 1),
            fin=date(2025, 6, 30), dias_restantes_lectiva=0, bloque_actual=None,
        )
        self.assertIsNone(construir_estado_ficha(cal, seguimiento(fase_esperada=None), HOY)['proximo_hito'])


class FechaLocalTestCase(unittest.TestCase):
    def test_un_instante_utc_de_la_noche_es_el_dia_anterior_en_colombia(self):
        self.assertEqual(fecha_local(datetime(2026, 11, 20, 2, 30)), date(2026, 11, 19))

    def test_respeta_la_zona_declarada(self):
        self.assertEqual(fecha_local(datetime(2026, 11, 20, 2, 30, tzinfo=timezone.utc)), date(2026, 11, 19))

    def test_una_fecha_o_un_vacio_pasan_sin_cambios(self):
        self.assertEqual(fecha_local(date(2026, 1, 5)), date(2026, 1, 5))
        self.assertIsNone(fecha_local(None))


if __name__ == '__main__':
    unittest.main()
