"""Tiempos observables sin consultas adicionales ni lectura de descargas."""

import re
import gc
import unittest
import weakref

from flask import Flask, Response, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

from app import create_app, db
from app.http_timing import registrar_tiempos_http


class HttpTimingTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False, 'HTTP_SLOW_REQUEST_MS': 0,
        })

        @self.app.get('/timing/query')
        def consultar():
            uno = db.session.execute(text('SELECT 1')).scalar_one()
            dos = db.session.execute(text('SELECT 2')).scalar_one()
            return jsonify(resultado=uno + dos)

        @self.app.get('/timing/stream')
        def descargar():
            return Response(iter([b'parte uno', b'parte dos']), mimetype='application/octet-stream')

        self.cliente = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def test_cuenta_sql_real_y_registra_endpoint_sin_parametros(self):
        with self.assertLogs(self.app.logger, level='WARNING') as logs:
            respuesta = self.cliente.get('/timing/query?token=dato-privado')
        self.assertEqual(respuesta.json, {'resultado': 3})
        timing = respuesta.headers.get('Server-Timing', '')
        self.assertRegex(timing, r'app;dur=\d+\.\d+, sql;dur=\d+\.\d+, sql_queries;desc="2"')
        duraciones = [float(n) for n in re.findall(r'dur=([\d.]+)', timing)]
        self.assertGreaterEqual(duraciones[0], duraciones[1])
        self.assertIn('sql_queries=2', logs.output[0])
        self.assertIn('route=/timing/query', logs.output[0])
        self.assertNotIn('dato-privado', '\n'.join(logs.output))
        self.assertNotIn('SELECT', '\n'.join(logs.output))

    def test_descarga_se_mantiene_en_stream_y_estaticos_conservan_cache(self):
        respuesta = self.cliente.get('/timing/stream')
        self.assertTrue(respuesta.is_streamed)
        self.assertEqual(respuesta.data, b'parte unoparte dos')
        self.assertIn('sql_queries;desc="0"', respuesta.headers.get('Server-Timing', ''))
        estatico = self.cliente.get('/static/js/loading-indicator.js')
        self.assertEqual(estatico.status_code, 200)
        self.assertNotIn('Server-Timing', estatico.headers)
        self.assertIn('immutable', estatico.headers['Cache-Control'])

    def test_consultas_fuera_de_peticion_y_404_no_rompen_el_registro(self):
        with self.app.app_context():
            self.assertEqual(db.session.execute(text('SELECT 7')).scalar_one(), 7)
        self.app.config['HTTP_SLOW_REQUEST_MS'] = 60000
        with self.assertNoLogs(self.app.logger, level='WARNING'):
            respuesta = self.cliente.get('/timing/no-existe')
        self.assertEqual(respuesta.status_code, 404)
        self.assertIn('sql_queries;desc="0"', respuesta.headers.get('Server-Timing', ''))

    def test_health_identifica_motor_sin_publicar_uri(self):
        respuesta = self.cliente.get('/health')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json.get('database_engine'), 'sqlite')
        self.assertNotIn('SQLALCHEMY_DATABASE_URI', respuesta.json)

    def test_instrumentacion_no_retiene_aplicaciones_descartadas(self):
        temporal_db = SQLAlchemy()
        temporal_app = Flask('tiempos-temporales')
        temporal_app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', HTTP_SLOW_REQUEST_MS=1000)
        temporal_db.init_app(temporal_app)
        registrar_tiempos_http(temporal_app, temporal_db)
        referencia = weakref.ref(temporal_app)
        del temporal_app
        gc.collect()
        self.assertIsNone(referencia(), 'Los callbacks SQL deben permitir liberar la aplicación.')
