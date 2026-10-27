"""Pruebas de persistencia de sesión prolongada (365 días), clave secreta duradera e invalidación."""

import datetime
from datetime import timedelta
import os
import secrets
import shutil
import tempfile
import unittest
from unittest.mock import patch

from flask import g

from app import create_app, db
from app.models.instructor import Instructor, load_user
import config


class PersistenciaSesionTestCase(unittest.TestCase):
    """Pruebas unitarias y de integración para la persistencia de sesiones y directivas de cookies."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.secret_file = os.path.join(self.temp_dir, '.secret_key')
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'PUBLIC_BASE_URL': 'https://panel.example.com',
            'SECRET_KEY_FILE': self.secret_file,
            'PERMANENT_SESSION_LIFETIME': timedelta(days=365),
            'SESSION_COOKIE_NAME': 'session',
            'SESSION_COOKIE_HTTPONLY': True,
            'SESSION_COOKIE_SAMESITE': 'Lax',
            'SESSION_COOKIE_SECURE': True,
            'REMEMBER_COOKIE_DURATION': timedelta(days=365),
            'REMEMBER_COOKIE_HTTPONLY': True,
            'REMEMBER_COOKIE_SAMESITE': 'Lax',
            'REMEMBER_COOKIE_SECURE': True,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Instructor Persistencia',
            correo='instructor.persistencia@sena.edu.co',
            rol='admin',
            activo=True,
            auth_version=1,
        )
        self.instructor.set_password('ClaveSegura123!')
        db.session.add(self.instructor)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_directivas_de_cookie_de_sesion_para_365_dias(self):
        """Verifica que el login emite cookies con duración de 365 días, HttpOnly y SameSite=Lax."""
        cliente = self.app.test_client()
        respuesta = cliente.post('/login', data={
            'correo': self.instructor.correo,
            'password': 'ClaveSegura123!',
        })
        self.assertEqual(respuesta.status_code, 302)

        # Inspeccionar la cabecera Set-Cookie
        cabeceras_set_cookie = respuesta.headers.getlist('Set-Cookie')
        cookie_sesion_str = next((c for c in cabeceras_set_cookie if c.startswith('session=')), None)
        self.assertIsNotNone(cookie_sesion_str, 'No se encontró la cookie de sesión en Set-Cookie')

        # Verificar atributos en la cadena Set-Cookie
        self.assertIn('HttpOnly', cookie_sesion_str)
        self.assertIn('SameSite=Lax', cookie_sesion_str)
        self.assertIn('Expires=', cookie_sesion_str)

        # Inspeccionar el objeto Cookie en el cliente
        cookie_obj = cliente.get_cookie('session')
        self.assertIsNotNone(cookie_obj)
        self.assertTrue(cookie_obj.http_only)
        self.assertEqual(cookie_obj.same_site, 'Lax')
        self.assertIsNotNone(cookie_obj.expires)

        # La fecha de expiración debe ser aproximadamente 365 días en el futuro (±2 días de margen)
        ahora = datetime.datetime.now(datetime.timezone.utc)
        dias_restantes = (cookie_obj.expires - ahora).total_seconds() / 86400.0
        self.assertGreater(dias_restantes, 360)
        self.assertLess(dias_restantes, 370)

        # Verificar cookie de recordar sesión de Flask-Login
        cookie_remember_str = next((c for c in cabeceras_set_cookie if c.startswith('remember_token=')), None)
        self.assertIsNotNone(cookie_remember_str, 'No se encontró la cookie remember_token en Set-Cookie')
        self.assertIn('HttpOnly', cookie_remember_str)
        self.assertIn('SameSite=Lax', cookie_remember_str)
        self.assertIn('Expires=', cookie_remember_str)

    def test_sesion_sobrevive_a_reinicio_del_navegador(self):
        """Simula un reinicio del navegador descartando cookies transitorias y comprobando que la sesión persiste."""
        cliente = self.app.test_client()
        respuesta_login = cliente.post('/login', data={
            'correo': self.instructor.correo,
            'password': 'ClaveSegura123!',
        })
        self.assertEqual(respuesta_login.status_code, 302)

        # Comprobar acceso exitoso al panel
        respuesta_panel = cliente.get('/instructor/')
        self.assertEqual(respuesta_panel.status_code, 200)

        # Simular reinicio del navegador: se abre un nuevo cliente y se copian ÚNICAMENTE
        # las cookies persistentes (que tienen fecha de expiración definida).
        # Las cookies de sesión sin `session.permanent = True` tendrían `expires is None` y se perderían.
        nuevo_cliente = self.app.test_client()
        cookies_transferidas = 0
        for (_, _, _), cookie in cliente._cookies.items():
            if cookie.expires is not None or cookie.max_age is not None:
                nuevo_cliente.set_cookie(
                    key=cookie.key,
                    value=cookie.value,
                    domain=cookie.domain,
                    path=cookie.path,
                )
                cookies_transferidas += 1

        self.assertGreater(cookies_transferidas, 0, 'Debe haber cookies persistentes con expiración')

        # El nuevo cliente debe mantener la autenticación tras el reinicio simulado
        respuesta_reinicio = nuevo_cliente.get('/instructor/')
        self.assertEqual(respuesta_reinicio.status_code, 200)
        self.assertIn(self.instructor.nombre.encode('utf-8'), respuesta_reinicio.data)

    def test_cierre_de_sesion_limpia_la_sesion(self):
        """Verifica que /logout limpia la sesión y revoca el acceso al panel."""
        cliente = self.app.test_client()
        cliente.post('/login', data={
            'correo': self.instructor.correo,
            'password': 'ClaveSegura123!',
        })
        self.assertEqual(cliente.get('/instructor/').status_code, 200)

        respuesta_logout = cliente.post('/logout')
        self.assertEqual(respuesta_logout.status_code, 302)

        # Tras logout, el acceso a /instructor/ debe redirigir al login
        respuesta_posterior = cliente.get('/instructor/')
        self.assertEqual(respuesta_posterior.status_code, 302)
        self.assertIn('/login', respuesta_posterior.headers['Location'])

    def test_invalidacion_multidispositivo_cuando_cambia_auth_version(self):
        """Comprueba que al actualizar auth_version las sesiones en otros dispositivos quedan invalidadas."""
        dispositivo_a = self.app.test_client()
        dispositivo_b = self.app.test_client()

        # Iniciar sesión en ambos dispositivos
        dispositivo_a.post('/login', data={'correo': self.instructor.correo, 'password': 'ClaveSegura123!'})
        g.pop('_login_user', None)
        dispositivo_b.post('/login', data={'correo': self.instructor.correo, 'password': 'ClaveSegura123!'})
        g.pop('_login_user', None)

        self.assertEqual(dispositivo_a.get('/instructor/').status_code, 200)
        g.pop('_login_user', None)
        self.assertEqual(dispositivo_b.get('/instructor/').status_code, 200)

        # El usuario cambia su contraseña en dispositivo_a, lo cual incrementa auth_version
        self.instructor.set_password('NuevaClaveSuperSegura456!')
        self.instructor.auth_version += 1
        db.session.commit()
        g.pop('_login_user', None)

        # Dispositivo B intenta navegar con la sesión previa atada a la versión antigua (auth_version=1)
        respuesta_dispositivo_b = dispositivo_b.get('/instructor/')
        self.assertEqual(respuesta_dispositivo_b.status_code, 302)
        self.assertIn('/login', respuesta_dispositivo_b.headers['Location'])

    def test_instructor_inactivo_es_rechazado_inmediatamente_en_load_user(self):
        """Comprueba que desactivar un instructor invalida su sesión activa de inmediato."""
        cliente = self.app.test_client()
        cliente.post('/login', data={'correo': self.instructor.correo, 'password': 'ClaveSegura123!'})
        self.assertEqual(cliente.get('/instructor/').status_code, 200)

        # Administrador desactiva la cuenta del instructor
        self.instructor.activo = False
        db.session.commit()
        g.pop('_login_user', None)

        # La sesión existente debe ser rechazada de inmediato sin necesidad de cambio de clave
        respuesta = cliente.get('/instructor/')
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/login', respuesta.headers['Location'])

    def test_load_user_rechaza_usuario_inactivo_con_formato_antiguo(self):
        """Verifica que sesiones heredadas sin prefijo de versión ('id') también validen instructor.activo."""
        self.instructor.activo = False
        db.session.commit()

        # user_id numérico sin ':'
        usuario_cargado = load_user(str(self.instructor.id))
        self.assertIsNone(usuario_cargado)

        # Reactivar y comprobar que carga
        self.instructor.activo = True
        db.session.commit()
        usuario_activo = load_user(str(self.instructor.id))
        self.assertIsNotNone(usuario_activo)
        self.assertEqual(usuario_activo.id, self.instructor.id)

    def test_load_user_entradas_invalidas_y_vacias_retornan_none(self):
        """Verifica que entradas vacías, tipos erróneos o identificadores malformados en load_user retornen None."""
        self.assertIsNone(load_user(None))
        self.assertIsNone(load_user(''))
        self.assertIsNone(load_user('no_es_entero'))
        self.assertIsNone(load_user('no_es_entero:1'))
        self.assertIsNone(load_user(f'{self.instructor.id}:no_es_version'))
        self.assertIsNone(load_user('999999:1'))
        self.assertIsNone(load_user('999999'))

    def test_load_user_tipo_entero_y_no_string_tolerados_sin_error(self):
        """Verifica que load_user soporte identificadores numéricos enteros y tipos no-string sin lanzar TypeError."""
        # Instructor activo con auth_version = 1 debe cargar exitosamente si se pasa como entero
        usuario = load_user(self.instructor.id)
        self.assertIsNotNone(usuario)
        self.assertEqual(usuario.id, self.instructor.id)

        # ID inexistente numérico debe retornar None
        self.assertIsNone(load_user(999999))

        # Tipos no-string diversos deben retornar None de forma segura
        for caso_invalido in [1.5, [1], {'id': 1}, object(), True, False]:
            self.assertIsNone(load_user(caso_invalido))


class SecretKeyPersistenciaTestCase(unittest.TestCase):
    """Pruebas para la persistencia y carga duradera de SECRET_KEY en almacenamiento local."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.archivo_secreto = os.path.join(self.temp_dir, 'instance', '.secret_key')

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_obtener_o_persistir_crea_archivo_y_reutiliza_la_misma_clave(self):
        """Verifica que la primera llamada crea el archivo y la segunda llamada reutiliza la misma clave."""
        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.archivo_secreto}):
            clave1, efimera1 = config._obtener_o_persistir_secret_key(self.temp_dir)
            self.assertTrue(efimera1)
            self.assertEqual(len(clave1), 128)
            self.assertTrue(os.path.isfile(self.archivo_secreto))

            # Segunda llamada debe leer exactamente la misma clave del archivo
            clave2, efimera2 = config._obtener_o_persistir_secret_key(self.temp_dir)
            self.assertTrue(efimera2)
            self.assertEqual(clave1, clave2)

    def test_obtener_o_persistir_respeta_secret_key_valida_del_entorno(self):
        """Verifica que una clave válida configurada en el entorno tiene prioridad y no es efímera."""
        clave_fuerte = secrets.token_hex(32)
        with patch.dict(os.environ, {'SECRET_KEY': clave_fuerte, 'SECRET_KEY_FILE': self.archivo_secreto}):
            clave, efimera = config._obtener_o_persistir_secret_key(self.temp_dir)
            self.assertEqual(clave, clave_fuerte)
            self.assertFalse(efimera)
            self.assertFalse(os.path.exists(self.archivo_secreto))

    def test_obtener_o_persistir_regenera_si_archivo_esta_corrupto(self):
        """Verifica que si el archivo de clave tiene contenido corrupto (<32 caracteres o inseguro) se regenera."""
        os.makedirs(os.path.dirname(self.archivo_secreto), exist_ok=True)
        with open(self.archivo_secreto, 'w', encoding='utf-8') as f:
            f.write('corta')

        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.archivo_secreto}):
            clave, efimera = config._obtener_o_persistir_secret_key(self.temp_dir)
            self.assertTrue(efimera)
            self.assertEqual(len(clave), 128)
            self.assertNotEqual(clave, 'corta')

            # El archivo debe haber sido sobreescrito con la nueva clave válida
            with open(self.archivo_secreto, 'r', encoding='utf-8') as f:
                self.assertEqual(f.read().strip(), clave)

    def test_obtener_o_persistir_tolera_error_de_lectura_oserror(self):
        """Verifica que si la lectura del archivo lanza OSError se genera una clave nueva sin abortar."""
        os.makedirs(os.path.dirname(self.archivo_secreto), exist_ok=True)
        with open(self.archivo_secreto, 'w', encoding='utf-8') as f:
            f.write(secrets.token_hex(64))

        real_open = open

        def open_con_fallo_de_lectura(archivo, mode='r', *args, **kwargs):
            if 'r' in mode:
                raise OSError('Error simulado de lectura')
            return real_open(archivo, mode, *args, **kwargs)

        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.archivo_secreto}):
            with patch('builtins.open', side_effect=open_con_fallo_de_lectura):
                clave, efimera = config._obtener_o_persistir_secret_key(self.temp_dir)
                self.assertTrue(efimera)
                self.assertEqual(len(clave), 128)

    def test_obtener_o_persistir_tolera_corrupcion_binaria_no_utf8(self):
        """Verifica que bytes binarios inválidos (no UTF-8) en .secret_key sean tolerados y la clave se regenere."""
        os.makedirs(os.path.dirname(self.archivo_secreto), exist_ok=True)
        with open(self.archivo_secreto, 'wb') as f:
            f.write(b'\x80\x81\x82\xff\xfe\x00\x01\x02')

        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.archivo_secreto}):
            clave, efimera = config._obtener_o_persistir_secret_key(self.temp_dir)
            self.assertTrue(efimera)
            self.assertEqual(len(clave), 128)

            # Debe haber sobreescrito el archivo con una clave válida en texto UTF-8
            with open(self.archivo_secreto, 'r', encoding='utf-8') as f:
                self.assertEqual(f.read().strip(), clave)

    def test_obtener_o_persistir_tolera_error_de_escritura_oserror(self):
        """Verifica que si la escritura lanza OSError se registra advertencia y se retorna la clave generada."""
        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.archivo_secreto}):
            with patch('os.open', side_effect=OSError('Permiso denegado simulado')):
                clave, efimera = config._obtener_o_persistir_secret_key(self.temp_dir)
                self.assertTrue(efimera)
                self.assertEqual(len(clave), 128)

    def test_sesion_sobrevive_a_reinicio_de_aplicacion_con_clave_persistente(self):
        """Demuestra que dos instancias independientes de la aplicación que comparten SECRET_KEY_FILE

        mantienen válidas las cookies de sesión generadas por la primera instancia.
        """
        # Crear clave persistente en disco
        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.archivo_secreto}):
            clave_compartida, _ = config._obtener_o_persistir_secret_key(self.temp_dir)

        # Configuración común para ambas instancias
        config_base = {
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'PUBLIC_BASE_URL': 'https://panel.example.com',
            'SECRET_KEY': clave_compartida,
            'PERMANENT_SESSION_LIFETIME': timedelta(days=365),
            'SESSION_COOKIE_NAME': 'session',
        }

        # Instancia 1 de la aplicación (antes del reinicio)
        app1 = create_app(config_base)
        with app1.app_context():
            db.create_all()
            inst = Instructor(nombre='Instructor Reinicio', correo='reinicio@sena.edu.co', rol='admin', activo=True)
            inst.set_password('Clave123!')
            db.session.add(inst)
            db.session.commit()
            inst_id = inst.id

            cliente1 = app1.test_client()
            r_login = cliente1.post('/login', data={'correo': 'reinicio@sena.edu.co', 'password': 'Clave123!'})
            self.assertEqual(r_login.status_code, 302)
            cookie_sesion = cliente1.get_cookie('session')
            self.assertIsNotNone(cookie_sesion)

        # Instancia 2 de la aplicación (después del reinicio del proceso/contenedor)
        # Se recrea la base de datos con los mismos datos
        app2 = create_app(config_base)
        with app2.app_context():
            db.create_all()
            inst2 = Instructor(id=inst_id, nombre='Instructor Reinicio', correo='reinicio@sena.edu.co', rol='admin', activo=True)
            inst2.set_password('Clave123!')
            db.session.add(inst2)
            db.session.commit()

            cliente2 = app2.test_client()
            # Asignar la cookie emitida por la Instancia 1
            cliente2.set_cookie(key=cookie_sesion.key, value=cookie_sesion.value)

            # La Instancia 2 debe validar con éxito la firma HMAC y aceptar la sesión sin pedir login
            respuesta_app2 = cliente2.get('/instructor/')
            self.assertEqual(respuesta_app2.status_code, 200)
            self.assertIn('Instructor Reinicio'.encode('utf-8'), respuesta_app2.data)


class ConfiguracionSeguridadCookieTestCase(unittest.TestCase):
    """Pruebas para las reglas de activación de SESSION_COOKIE_SECURE."""

    def test_session_cookie_secure_en_produccion(self):
        with patch.dict(os.environ, {'FLASK_ENV': 'production', 'PUBLIC_BASE_URL': 'http://inseguro.local'}):
            import importlib
            importlib.reload(config)
            self.assertTrue(config.Config.SESSION_COOKIE_SECURE)
            self.assertTrue(config.Config.REMEMBER_COOKIE_SECURE)

    def test_session_cookie_secure_con_variable_explicita(self):
        with patch.dict(os.environ, {'FLASK_ENV': 'development', 'SESSION_COOKIE_SECURE': 'true', 'PUBLIC_BASE_URL': ''}):
            import importlib
            importlib.reload(config)
            self.assertTrue(config.Config.SESSION_COOKIE_SECURE)

    def test_session_cookie_secure_con_url_https(self):
        with patch.dict(os.environ, {'FLASK_ENV': 'development', 'SESSION_COOKIE_SECURE': '', 'PUBLIC_BASE_URL': 'https://panel.sena.edu.co'}):
            import importlib
            importlib.reload(config)
            self.assertTrue(config.Config.SESSION_COOKIE_SECURE)

    def test_session_cookie_insegura_en_desarrollo_local_http(self):
        with patch.dict(os.environ, {'FLASK_ENV': 'development', 'SESSION_COOKIE_SECURE': '', 'PUBLIC_BASE_URL': 'http://127.0.0.1:5000'}):
            import importlib
            importlib.reload(config)
            self.assertFalse(config.Config.SESSION_COOKIE_SECURE)
            self.assertFalse(config.Config.REMEMBER_COOKIE_SECURE)


if __name__ == '__main__':
    unittest.main()
