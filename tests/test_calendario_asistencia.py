import unittest
from datetime import date

from app.services.asistencia import (
    construir_calendario_mes,
    mes_inicial_calendario,
)


def _evento(estado, clase, etiqueta, causal='', fecha_fmt=''):
    return {
        'estado': estado,
        'clase': clase,
        'etiqueta': etiqueta,
        'causal': causal,
        'fecha_fmt': fecha_fmt,
        'nota': '',
    }


class CalendarioAsistenciaTestCase(unittest.TestCase):
    """El calendario del modal se pinta en el servidor: cada celda debe salir
    con la clase del aprendiz dueño del mapa, sin depender de JavaScript."""

    def setUp(self):
        self.mapa = {
            '2026-07-10': _evento('TARDANZA', 'tardanza', 'Tardanza'),
            '2026-08-04': _evento('FALTA', 'falta-nj', 'Falta injustificada',
                                  fecha_fmt='Martes, 4 de Agosto de 2026'),
            '2026-08-05': _evento('ASISTE', 'asiste', 'Asistió'),
            '2026-08-11': _evento('EXCUSA_MEDICA', 'falta-j', 'Excusa médica',
                                  causal='Cita medica'),
        }

    def _por_dia(self, calendario):
        return {c['dia']: c['clase'] for c in calendario['celdas'] if not c['vacio']}

    def test_clases_por_dia(self):
        calendario = construir_calendario_mes(self.mapa, 2026, 8)
        clases = self._por_dia(calendario)
        self.assertEqual(clases[4], 'falta-nj')
        self.assertEqual(clases[5], 'asiste')
        self.assertEqual(clases[11], 'falta-j')
        self.assertEqual(clases[6], '')

    def test_estructura_del_mes(self):
        calendario = construir_calendario_mes(self.mapa, 2026, 8)
        vacias = [c for c in calendario['celdas'] if c['vacio']]
        dias = [c for c in calendario['celdas'] if not c['vacio']]
        # Agosto de 2026 empieza sábado: cinco huecos antes del día 1.
        self.assertEqual(len(vacias), 5)
        self.assertEqual(len(dias), 31)
        self.assertEqual(calendario['titulo'], 'Agosto 2026')
        self.assertEqual(dias[0]['iso'], '2026-08-01')

    def test_estado_desconocido_no_pinta_celda(self):
        mapa = {'2026-08-04': _evento('OTRO_ESTADO', 'inventada', 'Otro')}
        clases = self._por_dia(construir_calendario_mes(mapa, 2026, 8))
        self.assertEqual(clases[4], '')

    def test_tooltip_incluye_causal_y_dia_sin_registro(self):
        calendario = construir_calendario_mes(self.mapa, 2026, 8)
        titulos = {c['dia']: c['titulo'] for c in calendario['celdas'] if not c['vacio']}
        self.assertIn('Cita medica', titulos[11])
        self.assertIn('Sin marcación registrada', titulos[6])

    def test_mes_inicial_prefiere_el_mes_actual_con_datos(self):
        self.assertEqual(mes_inicial_calendario(self.mapa, date(2026, 8, 11)), (2026, 8))

    def test_mes_inicial_cae_al_ultimo_mes_con_datos(self):
        self.assertEqual(mes_inicial_calendario(self.mapa, date(2026, 12, 1)), (2026, 8))

    def test_mes_inicial_sin_datos_usa_el_mes_actual(self):
        self.assertEqual(mes_inicial_calendario({}, date(2026, 12, 1)), (2026, 12))

    def test_mapas_de_aprendices_distintos_no_se_mezclan(self):
        otro = {'2026-08-06': _evento('ASISTE', 'asiste', 'Asistió')}
        clases_a = self._por_dia(construir_calendario_mes(self.mapa, 2026, 8))
        clases_b = self._por_dia(construir_calendario_mes(otro, 2026, 8))
        self.assertEqual(clases_b[6], 'asiste')
        self.assertEqual(clases_b[4], '')
        self.assertEqual(clases_a[4], 'falta-nj')


if __name__ == '__main__':
    unittest.main()
