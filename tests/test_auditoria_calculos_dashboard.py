"""Auditoría y pruebas unitarias de cálculos de tiempo, RAPs y fases del dashboard.

Verifica la precisión matemática y consistencia pedagógica de:
1. Tiempo lectivo transcurrido, días cursados, días restantes y fases esperadas.
2. Estimación de RAPs por juicios, coherencia de redondeo entre tarjeta y desglose de fases.
3. Unidad métrica de RAPs evaluados en resumen_raps (unidades de RAP, no filas de BD).
4. Sincronización entre cronograma canónico y estadísticas extra del dashboard.
5. Casos de borde: fichas sin fechas, fechas invertidas, primer/último día, etapa productiva y 100% RAPs.
"""

import unittest
from datetime import date, datetime, timedelta, timezone

from app import create_app, db
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.instructor import Instructor
from app.models.juicio import JuicioEvaluativo
from app.services.fases_dashboard import (
    UMBRALES_ESTANDAR_FASES,
    _calcular_estimado_por_juicios,
    obtener_seguimiento_fases_dashboard,
)
from app.services.periodo_formacion import obtener_periodo_formacion


class AuditoriaCalculosDashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Instructor Auditor',
            correo='auditor@sena.edu.co',
        )
        self.instructor.set_password('clave-123')
        db.session.add(self.instructor)
        db.session.flush()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def test_verificacion_exacta_caso_captura_pantalla(self):
        """Verifica exactamente los valores reportados en la captura de pantalla:
        - Ficha con inicio 25/07/2025 y fin 24/10/2027 (duración productiva 6 meses).
        - Fecha de corte: 23/09/2026.
        - Tiempo: 426 de 638 días lectivos (66.8%).
        - Fase esperada por tiempo: Ejecución (66.8% está entre 50% y 85%).
        - RAPs: 23 de 75 RAPs cerrados (30.9%).
        - Fase real por RAPs: Planeación (30.9% está entre 25% y 50%).
        - Desfase: Retraso de 1 fase (Ejecución vs Planeación).
        """
        ficha = Ficha(
            id=101,
            codigo='3235642',
            nombre_programa='ANALISIS Y DESARROLLO DE SOFTWARE',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2025, 7, 25),
            fecha_fin=date(2027, 10, 24),
            duracion_productiva_meses=6,
        )
        db.session.add(ficha)
        db.session.commit()

        hoy = date(2026, 9, 23)

        # 1. Auditoría del cronograma de tiempo
        crono = obtener_periodo_formacion(ficha, hoy=hoy)

        self.assertTrue(crono['configurado'])
        self.assertEqual(crono['inicio_lectiva'], date(2025, 7, 25))
        self.assertEqual(crono['fin_lectiva'], date(2027, 4, 23))
        self.assertEqual(crono['inicio_productiva'], date(2027, 4, 24))
        self.assertEqual(crono['fin_productiva'], date(2027, 10, 24))

        self.assertEqual(crono['dias_totales'], 638)
        self.assertEqual(crono['dias_transcurridos'], 426)
        self.assertEqual(crono['porcentaje'], 66.8)
        self.assertEqual(crono['fase'], 'lectiva')
        self.assertEqual(crono['dias_restantes_lectiva'], 212)
        self.assertEqual(crono['dias_totales'], crono['dias_transcurridos'] + crono['dias_restantes_lectiva'])

        # 2. Configurar exactamente 23 aprendices activos y 75 RAPs (533 juicios aprobados de 1725)
        # 533 / 1725 * 100 = 30.89855... -> 30.9%
        aprendices = [
            Aprendiz(documento=f'CC_{i}', nombre=f'Aprendiz {i}', apellidos='Sena', ficha=ficha, estado='EN_FORMACION')
            for i in range(1, 24)
        ]
        db.session.add_all(aprendices)
        db.session.flush()

        juicios_a_crear = []
        aprobados_creados = 0
        total_meta_aprobados = 533

        for r in range(1, 76):
            rap_nombre = f'RAP_{r:02d}'
            for ap in aprendices:
                if aprobados_creados < total_meta_aprobados:
                    estado_j = 'APROBADO'
                    aprobados_creados += 1
                else:
                    estado_j = 'POR EVALUAR'

                juicios_a_crear.append(JuicioEvaluativo(
                    ficha_id=ficha.id,
                    aprendiz_id=ap.id,
                    competencia='Competencia Técnica',
                    resultado_aprendizaje=rap_nombre,
                    juicio=estado_j,
                    huella=f"huella_{ficha.id}_{ap.id}_{r}",
                ))

        db.session.bulk_save_objects(juicios_a_crear)
        db.session.commit()

        # 3. Auditoría del cálculo de fases
        fases_data = obtener_seguimiento_fases_dashboard(ficha, crono, hoy=hoy)

        self.assertTrue(fases_data['disponible'])
        self.assertEqual(fases_data['fase_esperada']['nombre'], 'EJECUCIÓN')
        self.assertEqual(fases_data['fase_real']['nombre'], 'PLANEACIÓN')
        self.assertEqual(fases_data['desfase_fases'], 1)
        self.assertIn('Retraso de 1 fase', fases_data['mensaje_veredicto'])

        # 4. Auditoría de la consistencia numérica de RAPs
        resumen_raps = fases_data['resumen_raps']
        self.assertEqual(resumen_raps['total'], 75)
        self.assertEqual(resumen_raps['aprobados'], 23)
        self.assertEqual(resumen_raps['porcentaje_aprobados'], 30.9)
        self.assertEqual(resumen_raps['pendientes'], 52)
        # Verificación clave: evaluados debe ser en unidades de RAPs (<= 75), nunca el conteo de filas de BD (533)
        self.assertLessEqual(resumen_raps['evaluados'], 75)

        # 5. Coherencia interna entre la tarjeta superior y el desglose de fases
        # La suma de resultados_aprobados de las 4 fases debe ser idéntica a resumen_raps['aprobados'] (23)
        fases = fases_data['fases']
        self.assertEqual(len(fases), 4)

        suma_aprobados_fases = sum(f['resultados_aprobados'] for f in fases)
        suma_totales_fases = sum(f['resultados_total'] for f in fases)

        self.assertEqual(suma_totales_fases, 75)
        self.assertEqual(suma_aprobados_fases, resumen_raps['aprobados'])
        self.assertEqual(suma_aprobados_fases, 23)

        # Análisis al 100% (19/19)
        self.assertEqual(fases[0]['nombre'], 'ANÁLISIS')
        self.assertEqual(fases[0]['resultados_total'], 19)
        self.assertEqual(fases[0]['resultados_aprobados'], 19)
        self.assertEqual(fases[0]['porcentaje_aprobados'], 100)

        # Planeación en curso (4/19)
        self.assertEqual(fases[1]['nombre'], 'PLANEACIÓN')
        self.assertEqual(fases[1]['resultados_total'], 19)
        self.assertEqual(fases[1]['resultados_aprobados'], 4)

        # Ejecución y Evaluación sin iniciar en RAPs (0/26 y 0/11)
        self.assertEqual(fases[2]['nombre'], 'EJECUCIÓN')
        self.assertEqual(fases[2]['resultados_total'], 26)
        self.assertEqual(fases[2]['resultados_aprobados'], 0)

        self.assertEqual(fases[3]['nombre'], 'EVALUACIÓN')
        self.assertEqual(fases[3]['resultados_total'], 11)
        self.assertEqual(fases[3]['resultados_aprobados'], 0)

    def test_umbrales_de_fases_y_transiciones(self):
        """Verifica que las 4 fases cubran exactamente todo el espectro [0, 100] sin traslapes ni huecos."""
        for i in range(len(UMBRALES_ESTANDAR_FASES) - 1):
            fase_actual = UMBRALES_ESTANDAR_FASES[i]
            siguiente_fase = UMBRALES_ESTANDAR_FASES[i + 1]
            self.assertEqual(fase_actual[3], siguiente_fase[2],
                             f"El límite superior de {fase_actual[0]} debe coincidir con el inferior de {siguiente_fase[0]}")

    def test_casos_borde_fechas_ficha(self):
        """Audita el comportamiento ante fechas límite o anómalas."""
        # 1. Fechas invertidas (fin antes de inicio)
        ficha_invertida = Ficha(
            id=102, codigo='INV', nombre_programa='Invertida', instructor_id=self.instructor.id,
            fecha_inicio=date(2026, 12, 31), fecha_fin=date(2026, 1, 1),
        )
        crono_inv = obtener_periodo_formacion(ficha_invertida)
        self.assertFalse(crono_inv['configurado'])
        self.assertEqual(crono_inv['fase'], 'sin_fechas')

        # 2. Sin fechas
        ficha_nula = Ficha(id=103, codigo='NUL', nombre_programa='Nula', instructor_id=self.instructor.id, fecha_inicio=None, fecha_fin=None)
        crono_nulo = obtener_periodo_formacion(ficha_nula)
        self.assertFalse(crono_nulo['configurado'])

        # 3. Primer día de etapa lectiva
        ficha_dia1 = Ficha(
            id=104, codigo='D1', nombre_programa='Dia 1', instructor_id=self.instructor.id,
            fecha_inicio=date(2026, 3, 1), fecha_fin=date(2027, 3, 1),
            duracion_productiva_meses=6,
        )
        crono_dia1 = obtener_periodo_formacion(ficha_dia1, hoy=date(2026, 3, 1))
        self.assertEqual(crono_dia1['dias_transcurridos'], 1)
        self.assertGreater(crono_dia1['porcentaje'], 0.0)
        self.assertEqual(crono_dia1['fase'], 'lectiva')

        # 4. Ficha en etapa productiva
        crono_prod = obtener_periodo_formacion(ficha_dia1, hoy=date(2026, 11, 1))
        self.assertEqual(crono_prod['fase'], 'productiva')
        self.assertEqual(crono_prod['porcentaje'], 100.0)
        self.assertEqual(crono_prod['dias_restantes_lectiva'], 0)

        # 5. Ficha ya finalizada
        crono_fin = obtener_periodo_formacion(ficha_dia1, hoy=date(2027, 4, 1))
        self.assertEqual(crono_fin['fase'], 'finalizada')
        self.assertEqual(crono_fin['dias_restantes'], 0)

    def test_estimacion_con_cero_juicios_no_genera_division_por_cero(self):
        """Una ficha con aprendices pero sin juicios importados debe degradar elegantemente a 0%."""
        ficha = Ficha(
            id=105, codigo='CERO', nombre_programa='Sin Juicios', instructor_id=self.instructor.id,
            fecha_inicio=date(2026, 1, 1), fecha_fin=date(2027, 12, 31),
        )
        db.session.add(ficha)
        db.session.commit()

        crono = obtener_periodo_formacion(ficha, hoy=date(2026, 6, 1))
        resultado = _calcular_estimado_por_juicios(ficha, crono, hoy=date(2026, 6, 1))

        self.assertTrue(resultado['disponible'])
        self.assertEqual(resultado['fase_real']['nombre'], 'ANÁLISIS')
        self.assertEqual(resultado['fase_real']['porcentaje_aprobados'], 0)
        self.assertEqual(resultado['fase_real']['resultados_aprobados'], 0)
        self.assertEqual(resultado['resumen_raps']['total'], 0)
        self.assertEqual(resultado['resumen_raps']['aprobados'], 0)
        self.assertEqual(resultado['resumen_raps']['porcentaje_aprobados'], 0.0)

    def test_meta_70_saber_tyt_y_estado_completado(self):
        """Verifica la detección correcta de la meta del 70% y el estado completado."""
        ficha = Ficha(
            id=106, codigo='META', nombre_programa='Meta 70', instructor_id=self.instructor.id,
            fecha_inicio=date(2025, 1, 1), fecha_fin=date(2026, 12, 31),
        )
        crono = {'configurado': True, 'porcentaje': 80.0, 'porcentaje_lectiva': 80.0}

        # Simular 100% de aprobación
        with unittest.mock.patch('app.services.fases_dashboard.db.session.query') as mock_query:
            mock_query.return_value.join.return_value.filter.return_value.all.return_value = [
                ('APROBADO', f'RAP_{i}') for i in range(10)
            ]
            resultado = _calcular_estimado_por_juicios(ficha, crono, hoy=date(2026, 6, 1))

            self.assertEqual(resultado['estado'], 'completado')
            self.assertEqual(resultado['fase_real']['porcentaje_aprobados'], 100)
            self.assertEqual(resultado['desfase_fases'], -1)
            self.assertIn('100% de los resultados aprobados', resultado['mensaje_veredicto'])


if __name__ == '__main__':
    unittest.main()
