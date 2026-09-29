"""Pruebas unitarias para el cálculo y renderizado de la curva de rendimiento del aprendiz."""

from datetime import date, datetime, timedelta
import unittest

from app import create_app, db
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha
from app.models.instructor import Instructor
from app.models.ranking import PuntajeHistorico
from app.services.curva_rendimiento import (
    construir_curva_svg_aprendiz,
    obtener_curva_rendimiento_aprendiz,
)


class CurvaRendimientoTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.instructor = Instructor(nombre='Instructor Curva', correo='curva@sena.edu.co', rol='instructor')
        self.instructor.set_password('segura123')
        db.session.add(self.instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='2900001',
            codigo_ficha='2900001',
            nombre_programa='ADSO',
            instructor_id=self.instructor.id,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 12, 31),
        )
        db.session.add(self.ficha)
        db.session.flush()

        self.aprendiz = Aprendiz(
            documento='10998877',
            nombre='Valentina',
            apellidos='Montoya',
            ficha_id=self.ficha.id,
            estado='EN_FORMACION',
        )
        db.session.add(self.aprendiz)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_construir_curva_svg_aprendiz_vacia(self):
        """Verifica que puntos vacíos devuelvan estructura SVG por defecto segura."""
        svg = construir_curva_svg_aprendiz([])
        self.assertEqual(svg['linea_puntaje'], '')
        self.assertEqual(svg['poligono_area'], '')
        self.assertEqual(svg['marcas_y'], [])
        self.assertIn('viewbox', svg)

    def test_construir_curva_svg_aprendiz_puntos_validos(self):
        """Calcula coordenadas válidas, polígono y marcas Y para una serie de puntos."""
        puntos = [
            {'fecha_str': '01/03/2026', 'puntaje': 60.0},
            {'fecha_str': '15/03/2026', 'puntaje': 75.0},
            {'fecha_str': '30/03/2026', 'puntaje': 90.0},
        ]
        svg = construir_curva_svg_aprendiz(puntos, meta_pct=70.0, ancho=600.0, alto=210.0)
        self.assertIn(',', svg['linea_puntaje'])
        self.assertIn(svg['linea_puntaje'], svg['poligono_area'])
        self.assertEqual(len(svg['marcas_y']), 5)
        self.assertTrue(puntos[-1]['es_ultimo'])
        self.assertFalse(puntos[0]['es_ultimo'])
        # La posición Y de 90% debe estar por encima (menor valor Y) que la de 60%
        self.assertLess(puntos[2]['y'], puntos[0]['y'])

    def test_curva_sin_datos_retorna_estructura_vacia(self):
        """Si no hay históricos ni fila_propia, retorna tiene_datos=False."""
        curva = obtener_curva_rendimiento_aprendiz(self.ficha.id, self.aprendiz.id)
        self.assertFalse(curva['tiene_datos'])
        self.assertEqual(curva['puntaje_actual'], 0.0)
        self.assertEqual(curva['nivel_desempeno'], 'Sin datos')

    def test_curva_con_solo_fila_propia_sintetiza_base(self):
        """Si solo hay cálculo actual en vivo, crea hito base y traza curva inicial."""
        fila_propia = {
            'puntaje_total': 82.5,
            'puntaje_asistencia': 80.0,
            'puntaje_evidencias': 85.0,
            'puntaje_juicios': 82.0,
            'posicion': 3,
        }
        curva = obtener_curva_rendimiento_aprendiz(
            self.ficha.id,
            self.aprendiz.id,
            fila_propia=fila_propia,
            hoy=date(2026, 4, 1),
        )
        self.assertTrue(curva['tiene_datos'])
        self.assertEqual(len(curva['puntos']), 2)
        self.assertEqual(curva['puntaje_actual'], 82.5)
        self.assertEqual(curva['posicion_actual'], 3)
        self.assertEqual(curva['nivel_desempeno'], 'Bueno')
        self.assertTrue(curva['supera_meta'])
        self.assertEqual(curva['distancia_meta'], 12.5)

    def test_curva_historica_tendencia_ascendente_y_excelente(self):
        """Múltiples cortes históricos con puntaje en aumento marcan tendencia ascendente y nivel Excelente."""
        h1 = PuntajeHistorico(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            fecha_corte=datetime(2026, 3, 1, 10, 0),
            puntaje_total=72.0,
            puntaje_asistencia=75.0,
            puntaje_evidencias=70.0,
            puntaje_juicios=70.0,
            posicion=5,
        )
        h2 = PuntajeHistorico(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            fecha_corte=datetime(2026, 3, 15, 10, 0),
            puntaje_total=80.0,
            puntaje_asistencia=82.0,
            puntaje_evidencias=78.0,
            puntaje_juicios=80.0,
            posicion=3,
        )
        h3 = PuntajeHistorico(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            fecha_corte=datetime(2026, 4, 1, 10, 0),
            puntaje_total=88.5,
            puntaje_asistencia=90.0,
            puntaje_evidencias=86.0,
            puntaje_juicios=88.0,
            posicion=1,
        )
        db.session.add_all([h1, h2, h3])
        db.session.commit()

        curva = obtener_curva_rendimiento_aprendiz(self.ficha.id, self.aprendiz.id)
        self.assertTrue(curva['tiene_datos'])
        self.assertEqual(curva['puntaje_actual'], 88.5)
        self.assertEqual(curva['posicion_actual'], 1)
        self.assertEqual(curva['tendencia'], 'ascendente')
        self.assertEqual(curva['tendencia_icono'], '↗️')
        self.assertEqual(curva['nivel_desempeno'], 'Excelente')
        self.assertEqual(curva['badge_class'], 'badge-success')
        self.assertEqual(curva['mejor_puntaje'], 88.5)
        self.assertEqual(curva['peor_puntaje'], 72.0)
        self.assertEqual(curva['diferencia_ultimo'], 8.5)

    def test_curva_historica_tendencia_descendente_y_riesgo(self):
        """Cortes en descenso registran tendencia descendente y nivel de alerta."""
        h1 = PuntajeHistorico(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            fecha_corte=datetime(2026, 3, 1, 10, 0),
            puntaje_total=75.0,
            posicion=2,
        )
        h2 = PuntajeHistorico(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            fecha_corte=datetime(2026, 3, 20, 10, 0),
            puntaje_total=58.0,
            posicion=6,
        )
        db.session.add_all([h1, h2])
        db.session.commit()

        curva = obtener_curva_rendimiento_aprendiz(self.ficha.id, self.aprendiz.id)
        self.assertEqual(curva['tendencia'], 'descendente')
        self.assertEqual(curva['tendencia_icono'], '↘️')
        self.assertEqual(curva['nivel_desempeno'], 'En Riesgo')
        self.assertEqual(curva['badge_class'], 'badge-warning')
        self.assertFalse(curva['supera_meta'])
        self.assertEqual(curva['distancia_meta'], -12.0)

    def test_curva_clasificacion_critico(self):
        """Puntaje inferior a 50 puntos clasifica como Crítico."""
        h1 = PuntajeHistorico(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            fecha_corte=datetime(2026, 3, 1, 10, 0),
            puntaje_total=42.0,
            posicion=12,
        )
        h2 = PuntajeHistorico(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz.id,
            fecha_corte=datetime(2026, 3, 15, 10, 0),
            puntaje_total=42.0,
            posicion=12,
        )
        db.session.add_all([h1, h2])
        db.session.commit()

        curva = obtener_curva_rendimiento_aprendiz(self.ficha.id, self.aprendiz.id)
        self.assertEqual(curva['nivel_desempeno'], 'Crítico')
        self.assertEqual(curva['badge_class'], 'badge-danger')
        self.assertEqual(curva['tendencia'], 'estable')


if __name__ == '__main__':
    unittest.main()
