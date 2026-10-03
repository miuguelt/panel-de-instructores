"""Regresiones de carga: datos reales, consultas acotadas y alertas por módulo."""

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from flask import template_rendered
from sqlalchemy import event

from app import db
from app.models import Aprendiz, Entrega, Tarea
from app.models.juicio import JuicioEvaluativo
from app.services import recomendaciones
from tests.test_rendimiento import BaseRendimiento


class CargaPaginasTestCase(BaseRendimiento):
    APRENDICES = 4
    SESIONES = 0
    TAREAS = 20

    def test_librerias_locales_integras_y_cacheadas(self):
        raiz = Path(self.app.static_folder) / 'vendor'
        manifiesto = json.loads((raiz / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(set(manifiesto), {'htmx', 'qrcodejs', 'lucide'})
        for nombre, asset in manifiesto.items():
            contenido = (raiz / nombre / asset['file']).read_bytes()
            self.assertEqual(hashlib.sha256(contenido).hexdigest(), asset['sha256'])
            self.assertGreater(len((raiz / nombre / 'LICENSE').read_text()), 100)
            respuesta = self.cliente.get(f'/static/vendor/{nombre}/{asset["file"]}')
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(respuesta.data, contenido)
            self.assertIn('immutable', respuesta.headers['Cache-Control'])

    def test_directorio_agrega_juicios_sin_materializar_filas(self):
        aprendiz = Aprendiz.query.order_by(Aprendiz.id).first()
        aprendiz_id = aprendiz.id
        JuicioEvaluativo.query.filter_by(aprendiz_id=aprendiz_id).delete()
        for indice, juicio in enumerate(['aprobado', 'AUN NO APROBADO', None, 'POR EVALUAR']):
            db.session.add(JuicioEvaluativo(
                ficha_id=self.ficha.id, aprendiz_id=aprendiz_id,
                competencia='Competencia de prueba', resultado_aprendizaje=f'RAP {indice}',
                juicio=juicio, huella=f'directorio-{indice}',
            ))
        db.session.commit()
        contextos, cargados = [], []

        def capturar(sender, template, context, **extra):
            contextos.append(context)

        def registrar(objeto, contexto):
            cargados.append(objeto.id)

        template_rendered.connect(capturar, self.app)
        event.listen(JuicioEvaluativo, 'load', registrar)
        try:
            respuesta = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/aprendices')
        finally:
            template_rendered.disconnect(capturar, self.app)
            event.remove(JuicioEvaluativo, 'load', registrar)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(contextos[-1]['juicios_stats'][aprendiz_id],
                         {'total': 4, 'aprobados': 1, 'pct': 25})
        self.assertEqual(contextos[-1]['total_juicios_ficha'], 10)
        self.assertEqual(contextos[-1]['total_aprobados_ficha'], 4)
        self.assertEqual(cargados, [], 'El directorio solo necesita agregados por aprendiz.')

    def test_tareas_no_recalcula_planeacion_y_consultas_no_crecen_por_tarjeta(self):
        Tarea.query.update({'fecha_limite': datetime.utcnow() + timedelta(hours=24)})
        db.session.commit()
        url = f'/instructor/fichas/{self.ficha.id}/tareas'
        with patch.object(recomendaciones, 'obtener_seguimiento_fases_dashboard',
                          wraps=recomendaciones.obtener_seguimiento_fases_dashboard) as fases:
            respuesta, consultas = self.contar_consultas(url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(b'Tarea 19', respuesta.data)
        fases.assert_not_called()
        grupos = [sql for sql in consultas if 'FROM grupos' in sql]
        entregas = [sql for sql in consultas if 'FROM entregas' in sql]
        self.assertLessEqual(len(grupos), 2, '\n'.join(grupos))
        self.assertLessEqual(len(entregas), 2, '\n'.join(entregas))

    def test_alertas_de_tareas_conservan_resultados_y_evitan_modulos_ajenos(self):
        ahora = datetime.utcnow()
        entrega = Entrega.query.first()
        entrega.calificada = False
        entrega.estado_revision = 'pendiente'
        entrega.fecha_entrega = ahora - timedelta(days=4)
        db.session.commit()
        completas = recomendaciones.obtener_recomendaciones_ficha(self.ficha.id, ahora=ahora)
        with patch.object(recomendaciones, 'obtener_seguimiento_fases_dashboard',
                          wraps=recomendaciones.obtener_seguimiento_fases_dashboard) as fases:
            enfocadas = recomendaciones.obtener_recomendaciones_ficha(
                self.ficha.id, ahora=ahora, categorias={recomendaciones.CAT_TAREAS})
        self.assertEqual(enfocadas, [r for r in completas if r.categoria == recomendaciones.CAT_TAREAS])
        self.assertTrue(enfocadas)
        self.assertIn('1 de 1 con demora', enfocadas[0].metrica_destacada)
        fases.assert_not_called()
        self.assertEqual(recomendaciones.obtener_recomendaciones_ficha(
            self.ficha.id, categorias=set()), [])
        self.assertEqual(recomendaciones.obtener_recomendaciones_ficha(
            999999, categorias={recomendaciones.CAT_TAREAS}), [])

    def test_juicios_solo_calcula_recomendaciones_del_modulo(self):
        with patch.object(recomendaciones, 'obtener_seguimiento_fases_dashboard',
                          wraps=recomendaciones.obtener_seguimiento_fases_dashboard) as fases:
            respuesta = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/juicios')
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(b'Competencia 0', respuesta.data)
        fases.assert_not_called()
