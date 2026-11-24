"""«Mis fichas»: primero lo accionable, cada dato una sola vez y sin datos inventados."""

import re
import unittest
from datetime import date
from types import SimpleNamespace

from flask import render_template, url_for

from app import create_app


def cronograma_lectiva(**cambios):
    base = {
        'configurado': True, 'porcentaje': 64.9, 'fase': 'lectiva', 'fase_label': 'Etapa lectiva',
        'inicio_lectiva': date(2025, 7, 25), 'fin_lectiva': date(2027, 4, 23),
        'inicio_productiva': date(2027, 4, 24), 'fin_productiva': date(2027, 10, 24),
        'dias_transcurridos': 414, 'dias_totales': 638, 'dias_restantes': 407,
        'dias_restantes_lectiva': 224, 'meses_productiva': 6, 'dias_cierre_ficha': 407,
        'dias_para_iniciar_lectiva': None, 'ficha_cerrada': False,
    }
    base.update(cambios)
    return base


FASES = {
    'disponible': True, 'planeacion_sincronizada': True, 'desfase_fases': 2,
    'fase_esperada': {'nombre': 'EJECUCIÓN', 'icono': '⚙️', 'orden': 3},
    'fase_real': {'nombre': 'ANÁLISIS', 'icono': '🔍', 'orden': 1},
    'fases': [], 'resumen_raps': {'porcentaje_aprobados': 38, 'aprobados': 29, 'total': 76},
    'mensaje_veredicto': 'Retraso de 2 fases.',
}

EXTRA = {
    'total_aprendices': 23, 'sesiones': 6, 'pct_asistencia': 93.5, 'pct_entregas': 40,
    'tareas_totales': 8, 'entregas_totales': 12, 'pendientes': 3, 'por_calificar': 5,
    'planes_pendientes': 2, 'aprendices_certificados': 0, 'alertas_activas': 1,
    'top_competencias': [], 'notas_positivas': 3, 'notas_negativas': 1, 'notas_total': 4,
}


class DashboardRenderTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()

    def tearDown(self):
        self.contexto.pop()

    def render(self, cronograma=None, fases=None, extra=None, resumen_hoy=None, fid=1):
        ficha = SimpleNamespace(id=fid, codigo='3235642', codigo_programa='228118',
                                nombre_programa='ANALISIS Y DESARROLLO DE SOFTWARE.',
                                fecha_inicio=date(2025, 7, 25), fecha_fin=date(2027, 10, 24),
                                duracion_productiva_meses=6)
        with self.app.test_request_context('/instructor/'):
            html = render_template(
                'instructor/dashboard.html', fichas=[ficha],
                cronogramas={fid: cronograma or cronograma_lectiva()},
                fases_fichas={fid: FASES if fases is None else fases},
                estadisticas_fichas={fid: {'activos': 23, 'total': 27,
                                           'estados': {'EN_FORMACION': 23, 'CANCELADO': 4}}},
                estadisticas_extra={fid: EXTRA if extra is None else extra},
                resumen_hoy=resumen_hoy, progreso_tyt=lambda f, n: None,
            )
            urls = {
                'vision': url_for('instructor.vision_general', ficha_id=fid),
                'tareas': url_for('instructor.tareas', ficha_id=fid),
                'alertas': url_for('instructor.alertas', ficha_id=fid),
                'planes': url_for('seguimiento.gestionar_planes', ficha_id=fid),
            }
        return html, urls

    @staticmethod
    def tarjeta(html):
        bloque = re.search(r'<article class="card card-ficha[^"]*"[^>]*>(.*?)</article>', html, re.S)
        assert bloque, 'No se encontró la tarjeta de la ficha'
        return bloque.group(1)

    def test_pendientes_de_hoy_van_antes_que_el_detalle(self):
        html, urls = self.render()
        card = self.tarjeta(html)
        pendientes = card.index('class="ficha-today"')
        self.assertLess(card.index('class="ficha-card-header"'), pendientes)
        self.assertLess(pendientes, card.index('<details class="ficha-card-more"'))
        for texto in ('1 alerta activa', '5 entregas por calificar', '3 entregas vencidas sin recibir',
                      '2 planes de mejoramiento abiertos'):
            self.assertIn(texto, card)
        self.assertIn(f'href="{urls["alertas"]}"', card)
        self.assertIn(f'href="{urls["planes"]}"', card)

    def test_sin_pendientes_muestra_confirmacion(self):
        extra = dict(EXTRA, pendientes=0, por_calificar=0, planes_pendientes=0, alertas_activas=0)
        card = self.tarjeta(self.render(extra=extra)[0])
        self.assertIn('Sin pendientes hoy', card)

    def test_barra_de_raps_compara_con_el_tiempo_y_la_meta(self):
        card = self.tarjeta(self.render()[0])
        self.assertIn('aria-label="RAPs aprobados"', card)
        self.assertIn('aria-valuenow="38"', card)
        self.assertIn('Tiempo transcurrido 64.9%', card)
        self.assertIn('Meta 70%', card)
        self.assertIn('RAPs 26.9 pts por debajo del tiempo', card)
        self.assertIn('29 de 76 RAPs', card)
        self.assertIn('Retraso de 2 fases', card)

    def test_la_cuenta_regresiva_aparece_una_sola_vez(self):
        crono = cronograma_lectiva(fase='por_iniciar', fase_label='Por iniciar', porcentaje=0,
                                   dias_para_iniciar_lectiva=5, dias_cierre_ficha=454)
        html, _ = self.render(cronograma=crono)
        card = self.tarjeta(html)
        self.assertEqual(card.count('Inicia en 5 días'), 1)
        self.assertNotIn('Cierra en 454', card)
        for retirado in ('ficha-countdown-strip', 'ficha-countdown-alerts', 'badge-countdown-urgent'):
            self.assertNotIn(retirado, html)

    def test_cierre_inminente_en_rojo(self):
        card = self.tarjeta(self.render(cronograma=cronograma_lectiva(dias_cierre_ficha=9))[0])
        self.assertIn('viz-pill--danger', card)
        self.assertIn('Cierra en 9 días', card)

    def test_fechas_clave_una_vez_y_bajo_demanda(self):
        card = self.tarjeta(self.render()[0])
        detalle = card[card.index('<details class="ficha-card-more"'):]
        for fecha in ('25/07/2025', '23/04/2027', '24/04/2027', '24/10/2027'):
            self.assertEqual(card.count(fecha), 1, fecha)
            self.assertIn(fecha, detalle)
        self.assertIn('6 meses', detalle)

    def test_indicadores_visuales_del_grupo(self):
        card = self.tarjeta(self.render()[0])
        self.assertIn('aria-label="Asistencia: 93.5%"', card)
        # El estado de los aprendices vive en Aprendices; aquí solo «N aprendices activos».
        self.assertNotIn('Estado de los aprendices', card)
        self.assertEqual(card.count('aprendices activos'), 1)
        self.assertIn('Observador: Notas positivas 3, Notas negativas 1', card)

    def test_la_tarjeta_no_repite_fases_ni_competencias(self):
        extra = dict(EXTRA, top_competencias=[('Inglés técnico', {'aprobados': 2, 'total': 10})])
        card = self.tarjeta(self.render(extra=extra)[0])
        self.assertEqual(card.count('Retraso de 2 fases'), 1)
        self.assertNotIn('ficha-fases-tracker', card)
        self.assertNotIn('Competencias con menor aprobación', card)
        self.assertNotIn('Aprendices con todos los RAPs aprobados', card)
        self.assertIn('Ver fases y competencias en la Visión general', card)

    def test_tarjeta_y_lista_compacta_ofrecen_los_mismos_accesos(self):
        html, _ = self.render()
        tarjeta = re.search(r'id="ficha-acciones-1"[\s\S]*?</div>', html).group(0)
        compacta = re.search(r'id="compact-acciones-1"[\s\S]*?</div>', html).group(0)
        etiquetas = lambda bloque: re.findall(r'<span>([^<]+)</span>', bloque)
        self.assertEqual(etiquetas(tarjeta), etiquetas(compacta))
        self.assertIn('Aprendices', etiquetas(compacta))

    def test_sin_datos_no_inventa_porcentajes_ni_fases(self):
        extra = dict(EXTRA, pct_asistencia=None, pct_entregas=None, sesiones=0, tareas_totales=0)
        html, urls = self.render(extra=extra, fases={'disponible': False})
        card = self.tarjeta(html)
        self.assertIn('Asistencia: sin datos', card)
        self.assertNotIn('Ejecución', html)
        self.assertNotIn('100%', html)
        compacta = html[html.index('dashboard-compact-table'):]
        self.assertIn('Sin datos', compacta)
        self.assertIn(f'href="{urls["vision"]}"', compacta)

    def test_resumen_global_de_hoy(self):
        resumen = {'activas': 3, 'por_calificar': 12, 'alertas': 4, 'cierres_proximos': 1, 'con_pendientes': 2}
        html, _ = self.render(resumen_hoy=resumen)
        hoy = re.search(r'<section class="dashboard-today"(.*?)</section>', html, re.S).group(1)
        self.assertIn('>12<', hoy)
        self.assertIn('Entregas por calificar', hoy)
        self.assertIn('>4<', hoy)
        self.assertIn('2 de 3 fichas con pendientes', hoy)
        # Las fichas activas ya se cuentan en el título: no se repiten como indicador.
        self.assertNotIn('Fichas activas', hoy)

    def test_un_solo_enlace_principal_a_la_ficha(self):
        html, urls = self.render()
        card = self.tarjeta(html)
        self.assertIn('Abrir ficha', card)
        self.assertNotIn('ficha-operational-panel', card)
        self.assertNotIn('ficha-action-grid', card)

    def test_ficha_finalizada_va_a_archivadas(self):
        crono = cronograma_lectiva(fase='finalizada', fase_label='Finalizada', ficha_cerrada=True)
        html, _ = self.render(cronograma=crono)
        archivadas = html[html.index('class="fichas-archivadas"'):html.index('dashboard-compact-view')]
        self.assertIn('Ficha 3235642', archivadas)
        self.assertNotIn('class="ficha-today"', archivadas)
        # La lista compacta muestra solo las activas, igual que las tarjetas.
        compacta = html[html.index('dashboard-compact-table'):html.index('</table>')]
        self.assertNotIn('compact-ficha-row', compacta)


if __name__ == '__main__':
    unittest.main()
