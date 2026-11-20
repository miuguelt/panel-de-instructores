"""Contexto del panorama que recibe la plantilla de planeación."""

import unittest
from datetime import date

from app.services.respuestas_planeacion import CLAVES_PANORAMA, contexto_panorama


class ContextoPanoramaTestCase(unittest.TestCase):
    def test_sin_panorama_entrega_vacios_seguros(self):
        contexto = contexto_panorama(None)
        self.assertEqual(set(contexto), set(CLAVES_PANORAMA))
        self.assertEqual(contexto['diagnostico'], [])
        self.assertEqual(contexto['fases_progreso'], [])
        self.assertEqual(contexto['catalogo_pedagogico'], {})
        self.assertEqual(contexto['seguimiento_evaluacion'], {})
        for clave in ('analisis', 'calendario', 'estado', 'veredicto', 'hoy'):
            self.assertIsNone(contexto[clave])

    def test_las_listas_vacias_no_se_comparten_entre_llamadas(self):
        primero = contexto_panorama(None)
        primero['diagnostico'].append('hallazgo')
        self.assertEqual(contexto_panorama(None)['diagnostico'], [])

    def test_con_panorama_copia_sus_valores_y_completa_los_faltantes(self):
        panorama = {'analisis': {'items': []}, 'estado': {'disponible': True}, 'hoy': date(2026, 6, 15),
                    'diagnostico': ['vacío'], 'clave_ajena': 1}
        contexto = contexto_panorama(panorama)
        self.assertEqual(contexto['analisis'], {'items': []})
        self.assertEqual(contexto['estado'], {'disponible': True})
        self.assertEqual(contexto['hoy'], date(2026, 6, 15))
        self.assertEqual(contexto['diagnostico'], ['vacío'])
        self.assertEqual(contexto['catalogo_pedagogico'], {})
        self.assertIsNone(contexto['radar'])
        self.assertNotIn('clave_ajena', contexto)


if __name__ == '__main__':
    unittest.main()
