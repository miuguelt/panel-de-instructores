"""El semáforo de riesgo es uno solo para Alertas, Asistencia y Visión general."""

import unittest

from app.routes import instructor as rutas_instructor
from app.services import resumen_ficha


class SemaforoUnicoTest(unittest.TestCase):
    def test_las_rutas_usan_el_calculo_del_servicio(self):
        self.assertIs(rutas_instructor.calcular_semaforo, resumen_ficha.calcular_semaforo)

    def test_no_quedan_copias_privadas_en_el_paquete_de_rutas(self):
        for nombre in ('_faltas_por_aprendiz', '_ultima_entrega_por_aprendiz'):
            self.assertIs(getattr(rutas_instructor, nombre, None), getattr(resumen_ficha, nombre))


if __name__ == '__main__':
    unittest.main()
