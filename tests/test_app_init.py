"""Pruebas unitarias para inicialización de la aplicación, utilidades de infraestructura y errores."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from flask_wtf.csrf import CSRFError

from app import (
    _encode_redis_url,
    _inventario_uploads,
    _preparar_uploads,
    _probe_redis,
    _sanitize_storage_uri,
    create_app,
    db,
)


class AppInitInfraestructuraTestCase(unittest.TestCase):
    def test_encode_redis_url_con_caracteres_especiales(self):
        url_original = 'redis://adso:clave/con@simbolos#y+mas@redis-host:6379/0'
        url_codificada = _encode_redis_url(url_original)
        self.assertIn('redis://adso:', url_codificada)
        self.assertNotIn('/con@simbolos', url_codificada)
        self.assertIn('@redis-host:6379/0', url_codificada)

    def test_encode_redis_url_sin_caracteres_especiales(self):
        url = 'redis://:clave@redis-host:6379/0'
        self.assertEqual(_encode_redis_url(url), url)

    def test_sanitize_storage_uri_oculta_credenciales(self):
        uri = 'redis://:clave@redis.internal:6379/0'
        sanitizada = _sanitize_storage_uri(uri)
        self.assertEqual(sanitizada, 'redis://****@redis.internal:6379/0')
        self.assertNotIn('clave', sanitizada)

    def test_sanitize_storage_uri_inmodificada_si_no_hay_credenciales(self):
        self.assertEqual(_sanitize_storage_uri('memory://'), 'memory://')
        self.assertEqual(_sanitize_storage_uri(''), '')
        self.assertEqual(_sanitize_storage_uri('sin_esquema'), 'sin_esquema')

    def test_probe_redis_vacio_retorna_memory(self):
        self.assertEqual(_probe_redis(''), 'memory://')
        self.assertEqual(_probe_redis(None), 'memory://')

    def test_probe_redis_con_espacios_o_comillas(self):
        self.assertEqual(_probe_redis('  "invalido"  '), 'memory://')

    def test_probe_redis_esquema_no_soportado(self):
        self.assertEqual(_probe_redis('http://localhost:6379'), 'memory://')

    def test_probe_redis_conexion_exitosa(self):
        mock_client = MagicMock()
        with patch('redis.from_url', return_value=mock_client):
            resultado = _probe_redis('redis://:clave@localhost:6379/0')
            self.assertEqual(resultado, 'redis://:clave@localhost:6379/0')
            mock_client.ping.assert_called_once()
            mock_client.close.assert_called_once()

    def test_probe_redis_conexion_fallida(self):
        with patch('redis.from_url', side_effect=ConnectionError('fallo de red')):
            resultado = _probe_redis('redis://:clave@localhost:6379/0')
            self.assertEqual(resultado, 'memory://')

    def test_preparar_uploads_exito(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_mock = MagicMock()
            app_mock.config = {'UPLOAD_FOLDER': temp_dir}
            _preparar_uploads(app_mock)
            estado = app_mock.config.get('UPLOADS_ESTADO')
            self.assertTrue(estado['escribible'])
            self.assertEqual(estado['detalle'], '')

    def test_preparar_uploads_error_escritura(self):
        app_mock = MagicMock()
        app_mock.config = {'UPLOAD_FOLDER': '/directorio/invalido/imposible/de/crear'}
        with patch('os.makedirs', side_effect=OSError('Permiso denegado')):
            _preparar_uploads(app_mock)
            estado = app_mock.config.get('UPLOADS_ESTADO')
            self.assertFalse(estado['escribible'])
            self.assertIn('Permiso denegado', estado['detalle'])

    def test_inventario_uploads_calcula_resumen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archivo_valido = os.path.join(temp_dir, 'valido.txt')
            with open(archivo_valido, 'wb') as f:
                f.write(b'contenido')

            archivo_vacio = os.path.join(temp_dir, 'vacio.txt')
            with open(archivo_vacio, 'wb') as f:
                pass

            archivo_part = os.path.join(temp_dir, 'parcial.txt.part')
            with open(archivo_part, 'wb') as f:
                f.write(b'incompleto')

            resumen = _inventario_uploads(temp_dir)
            self.assertEqual(resumen['archivos'], 2)
            self.assertEqual(resumen['vacios'], 1)
            self.assertEqual(resumen['parciales'], 1)
            self.assertEqual(resumen['bytes'], len(b'contenido'))
            self.assertFalse(resumen['truncado'])

    def test_inventario_uploads_limite_tope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for i in range(5):
                with open(os.path.join(temp_dir, f'doc_{i}.txt'), 'wb') as f:
                    f.write(b'x')
            resumen = _inventario_uploads(temp_dir, tope=3)
            self.assertTrue(resumen['truncado'])

    def test_inventario_uploads_carpeta_inexistente(self):
        resumen = _inventario_uploads('/ruta/no/existente')
        self.assertEqual(resumen['archivos'], 0)
        self.assertFalse(resumen['truncado'])


class AppInitEndpointsTestCase(unittest.TestCase):
    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'UPLOAD_FOLDER': self.uploads.name,
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        self.cliente = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def test_health_endpoint_ok(self):
        respuesta = self.cliente.get('/health')
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.get_json()
        self.assertEqual(datos['status'], 'ok')
        self.assertEqual(datos['database'], 'connected')
        self.assertTrue(datos['uploads']['escribible'])

    def test_health_endpoint_con_db_caida(self):
        with patch.object(db.engine, 'connect', side_effect=Exception('Fallo de red')):
            respuesta = self.cliente.get('/health')
            self.assertEqual(respuesta.status_code, 200)
            datos = respuesta.get_json()
            self.assertEqual(datos['status'], 'degraded')
            self.assertIn('Fallo de red', datos['database'])

    def test_health_endpoint_con_inventario_uploads(self):
        respuesta = self.cliente.get('/health?uploads=1')
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.get_json()
        self.assertIn('archivos', datos['uploads'])

    def test_index_redirecciona_a_login(self):
        respuesta = self.cliente.get('/')
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta.headers['Location'].endswith('/login'))

    def test_error_404_personalizado(self):
        respuesta = self.cliente.get('/ruta-que-definitivamente-no-existe-12345')
        self.assertEqual(respuesta.status_code, 404)
        self.assertIn('Página no encontrada', respuesta.get_data(as_text=True))

    def test_filtro_format_size(self):
        filtro = self.app.jinja_env.filters['format_size']
        self.assertEqual(filtro(0), '0 B')
        self.assertEqual(filtro(None), '0 B')
        self.assertEqual(filtro(1024), '1.0 KB')
        self.assertEqual(filtro(1024 * 1024 * 5), '5.0 MB')

    def test_filtro_etiqueta_y_tono_estado(self):
        filtro_etiqueta = self.app.jinja_env.filters['etiqueta_estado']
        filtro_tono = self.app.jinja_env.filters['tono_estado']
        self.assertEqual(filtro_etiqueta('EN FORMACION'), 'En formación')
        self.assertEqual(filtro_tono('EN FORMACION'), 'success')

    def test_filtro_tipo_competencia(self):
        filtro = self.app.jinja_env.filters['tipo_competencia']
        self.assertIn(filtro('240201500 - Promover la interacción idónea'), ('transversal', 'tecnica', 'clave', 'basica'))

    def test_csrf_error_handler_get(self):
        with self.app.test_request_context('/', method='GET'):
            error = CSRFError('Token no coincide')
            handler = self.app.error_handler_spec[None][400][CSRFError]
            respuesta, codigo = handler(error)
            self.assertEqual(codigo, 400)
            self.assertIn('Sesión expirada', respuesta)

    def test_csrf_error_handler_post_redirecciona(self):
        with self.app.test_request_context('/', method='POST'):
            error = CSRFError('Token expirado')
            handler = self.app.error_handler_spec[None][400][CSRFError]
            respuesta = handler(error)
            self.assertEqual(respuesta.status_code, 302)

    def test_error_500_handler_api_devuelve_json(self):
        with self.app.test_request_context('/api/test-error', method='GET'):
            error = RuntimeError('Fallo crítico simulado')
            handler = self.app.error_handler_spec[None][None][Exception]
            respuesta, codigo = handler(error)
            self.assertEqual(codigo, 500)
            self.assertEqual(respuesta.get_json()['error'], 'Error interno del servidor.')

    def test_error_500_handler_html_devuelve_render(self):
        with self.app.test_request_context('/instructor/vista', method='GET'):
            error = RuntimeError('Fallo web')
            handler = self.app.error_handler_spec[None][None][Exception]
            respuesta, codigo = handler(error)
            self.assertEqual(codigo, 500)
            self.assertIn('Error interno del servidor', respuesta)


if __name__ == '__main__':
    unittest.main()
