"""Pruebas adversariales de estrés para el Milestone M1.

Diseñado por Challenger 1 para estresar:
1. Persistencia y manipulación de cookies de sesión en el cliente.
2. Casos extremos y corrupción de archivos de clave secreta (.secret_key).
3. Entradas adversariales y tipos no estándar en load_user.
4. Concurrencia y condiciones de carrera en _obtener_o_persistir_secret_key.
"""

import concurrent.futures
import datetime
from datetime import timedelta
import os
import secrets
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app import create_app, db
from app.models.instructor import Instructor, load_user
import config


class AdversarialCookieTestCase(unittest.TestCase):
    """Estresado adversarial del ciclo de vida y manipulación de cookies de sesión."""

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
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.inst = Instructor(
            nombre='Instructor Adversarial',
            correo='adversarial@sena.edu.co',
            rol='admin',
            activo=True,
            auth_version=1,
        )
        self.inst.set_password('ClaveSegura123!')
        db.session.add(self.inst)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_manipulacion_de_firma_hmac_en_cookie_es_rechazada_limpiamente(self):
        """Si el cliente adultera la firma HMAC o contenido de la cookie, el servidor debe redirigir a login sin 500."""
        client = self.app.test_client()
        r_login = client.post('/login', data={'correo': self.inst.correo, 'password': 'ClaveSegura123!'})
        self.assertEqual(r_login.status_code, 302)

        cookie_real = client.get_cookie('session')
        self.assertIsNotNone(cookie_real)

        # Adulterar la firma alterando el último carácter
        valor_adulterado = cookie_real.value[:-1] + ('A' if cookie_real.value[-1] != 'A' else 'B')
        client.set_cookie(key='session', value=valor_adulterado)
        client.delete_cookie('remember_token')

        from flask import g
        g.pop('_login_user', None)

        resp = client.get('/instructor/')
        self.assertEqual(resp.status_code, 302, 'La cookie adulterada no debe otorgar acceso')
        self.assertIn('/login', resp.headers['Location'])
        self.assertIn('/login', resp.headers['Location'])

    def test_inyeccion_de_cadenas_maliciosas_como_cookie(self):
        """Envío de cadenas con inyecciones SQL, XSS, bytes nulos y basura binaria en el valor de la cookie."""
        client = self.app.test_client()
        payloads_maliciosos = [
            "' OR 1=1; --",
            "<script>alert(1)</script>",
            "\x00\x01\x02\xff\xfe",
            "session=" * 50,
            "A" * 10000,  # Cookie inflada
            "None",
            "{}",
            "True",
        ]
        for payload in payloads_maliciosos:
            client.set_cookie(key='session', value=payload)
            resp = client.get('/instructor/')
            self.assertEqual(resp.status_code, 302, f'Payload falló al ser rechazado limpiamente: {payload!r}')
            self.assertIn('/login', resp.headers['Location'])

    def test_persistencia_continua_en_multiples_peticiones_sucesivas(self):
        """Verifica que tras 10 peticiones consecutivas la sesión permanece permanente y no se degrada a volátil."""
        client = self.app.test_client()
        client.post('/login', data={'correo': self.inst.correo, 'password': 'ClaveSegura123!'})

        for i in range(10):
            resp = client.get('/instructor/')
            self.assertEqual(resp.status_code, 200)
            cookie = client.get_cookie('session')
            self.assertIsNotNone(cookie.expires, f'La cookie perdió su expiración en la petición {i}')
            ahora = datetime.datetime.now(datetime.timezone.utc)
            dias_restantes = (cookie.expires - ahora).total_seconds() / 86400.0
            self.assertGreater(dias_restantes, 360, f'Días restantes degradados en petición {i}: {dias_restantes}')

    def test_remember_token_tampered_is_ignored(self):
        """Si la cookie remember_token es manipulada, no debe autenticar ni provocar excepción."""
        client = self.app.test_client()
        client.set_cookie(key='remember_token', value='token_falso_manipulado_12345')
        resp = client.get('/instructor/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])


class AdversarialSecretKeyTestCase(unittest.TestCase):
    """Estresado adversarial de la función _obtener_o_persistir_secret_key."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.secret_file = os.path.join(self.temp_dir, 'instance', '.secret_key')

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_secret_key_archivo_vacio_es_regenerado(self):
        """Archivo .secret_key de 0 bytes debe ser detectado como inválido y regenerado a 128 caracteres."""
        os.makedirs(os.path.dirname(self.secret_file), exist_ok=True)
        with open(self.secret_file, 'wb') as f:
            pass  # Archivo vacío

        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.secret_file}):
            clave, efimera = config._obtener_o_persistir_secret_key(self.temp_dir)
            self.assertTrue(efimera)
            self.assertEqual(len(clave), 128)

    def test_secret_key_boundary_31_vs_32_caracteres(self):
        """Prueba de frontera: 31 caracteres debe ser regenerada; 32 caracteres debe ser aceptada."""
        os.makedirs(os.path.dirname(self.secret_file), exist_ok=True)

        # 31 caracteres
        with open(self.secret_file, 'w', encoding='utf-8') as f:
            f.write('a' * 31)
        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.secret_file}):
            clave31, _ = config._obtener_o_persistir_secret_key(self.temp_dir)
            self.assertEqual(len(clave31), 128, 'Clave de 31 caracteres debió regenerarse')

        # 32 caracteres válidos
        clave_32 = 'b' * 32
        with open(self.secret_file, 'w', encoding='utf-8') as f:
            f.write(clave_32)
        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.secret_file}):
            clave32, _ = config._obtener_o_persistir_secret_key(self.temp_dir)
            self.assertEqual(clave32, clave_32, 'Clave de 32 caracteres debió aceptarse')

    def test_secret_key_insegura_en_archivo_es_regenerada(self):
        """Si el archivo contiene literales de _INSECURE_SECRETS, debe regenerarse."""
        os.makedirs(os.path.dirname(self.secret_file), exist_ok=True)
        for insecure in ['dev-key-change-me', 'cambiar-esta-clave-en-produccion']:
            with open(self.secret_file, 'w', encoding='utf-8') as f:
                f.write(insecure)
            with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.secret_file}):
                clave, efimera = config._obtener_o_persistir_secret_key(self.temp_dir)
                self.assertTrue(efimera)
                self.assertEqual(len(clave), 128)
                self.assertNotEqual(clave, insecure)

    def test_secret_key_concurrencia_multi_hilo(self):
        """Múltiples llamadas concurrentes en ausencia del archivo deben generar claves válidas de 128 caracteres."""
        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.secret_file}):
            def ejecutar_llamada(idx):
                return config._obtener_o_persistir_secret_key(self.temp_dir)

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                resultados = list(executor.map(ejecutar_llamada, range(16)))

            for clave, efimera in resultados:
                self.assertEqual(len(clave), 128)
                self.assertTrue(efimera)

            # Verificar que el archivo final en disco es legible y contiene una clave de 128 caracteres
            with open(self.secret_file, 'r', encoding='utf-8') as f:
                contenido = f.read().strip()
            self.assertEqual(len(contenido), 128)

    def test_secret_key_corrupcion_binaria_no_utf8(self):
        """BUG TEST: Si el archivo contiene bytes binarios no-UTF8 (ej. corrupción en disco),

        _obtener_o_persistir_secret_key NO debe lanzar UnicodeDecodeError no capturado.
        """
        os.makedirs(os.path.dirname(self.secret_file), exist_ok=True)
        with open(self.secret_file, 'wb') as f:
            f.write(b'\x80\x81\x82\xff\xfe\x00\x01\x02')

        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.secret_file}):
            try:
                clave, efimera = config._obtener_o_persistir_secret_key(self.temp_dir)
                self.assertEqual(len(clave), 128)
                self.assertTrue(efimera)
            except UnicodeDecodeError as exc:
                self.fail(f"FALLO DE RESILIENCIA: _obtener_o_persistir_secret_key lanzó UnicodeDecodeError: {exc}")


class AdversarialLoadUserTestCase(unittest.TestCase):
    """Estresado adversarial de app.models.instructor.load_user."""

    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.inst = Instructor(
            nombre='Instructor UserLoader',
            correo='userloader@sena.edu.co',
            rol='admin',
            activo=True,
            auth_version=2,
        )
        self.inst.set_password('ClaveSegura123!')
        db.session.add(self.inst)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_load_user_tipo_entero_no_debe_lanzar_type_error(self):
        """BUG TEST: Si load_user recibe un entero (ej. load_user(1)),

        NO debe lanzar TypeError: argument of type 'int' is not iterable.
        Debe retornar el usuario o None.
        """
        try:
            # Instructor tiene auth_version=2, por lo que versión antigua (formato legacy numérico) debe retornar None
            resultado = load_user(self.inst.id)
            self.assertIsNone(resultado)
        except TypeError as exc:
            self.fail(f"FALLO DE RESILIENCIA: load_user({self.inst.id}) lanzó TypeError: {exc}")

    def test_load_user_tipos_no_string_diversos(self):
        """load_user no debe explotar con float, dict, list u object."""
        casos = [
            1.5,
            [1],
            {'id': 1},
            object(),
            True,
            False,
        ]
        for caso in casos:
            try:
                res = load_user(caso)
                self.assertIsNone(res, f"Esperaba None para {caso!r}, obtuvo {res!r}")
            except Exception as exc:
                self.fail(f"FALLO DE RESILIENCIA: load_user({caso!r}) lanzó excepción inesperada {type(exc)}: {exc}")

    def test_load_user_tampering_versiones_adversarias(self):
        """Prueba de strings con múltiples separadores, versiones negativas, espacios y SQLi."""
        casos = [
            f"{self.inst.id}:2:1",
            f"{self.inst.id}:-1",
            f"{self.inst.id}:0",
            f"{self.inst.id}: 2",   # Espacio antes del entero
            f"{self.inst.id}:2 ",   # Espacio después del entero
            f"{self.inst.id}:2.0",
            f"{self.inst.id}:0x02",
            f":{self.inst.id}",
            "::",
            f"{self.inst.id}:",
            f"{self.inst.id}:\x00",
            f"{self.inst.id}:' OR '1'='1",
            f"{self.inst.id}:NaN",
            f"{self.inst.id}:Infinity",
            f"-{self.inst.id}:2",
        ]
        for caso in casos:
            try:
                res = load_user(caso)
                # Solo el caso con versión exactamente 2 si fue parseada correctamente podría ser el instructor,
                # pero variantes malformadas deben retornar None o el instructor si limpió el string.
                if caso in (f"{self.inst.id}: 2", f"{self.inst.id}:2 "):
                    # int(" 2") es 2 en Python, lo cual es admisible
                    self.assertIn(res, (self.inst, None))
                else:
                    self.assertIsNone(res, f"Se esperaba None para el caso adversarial {caso!r}, pero retornó {res!r}")
            except Exception as exc:
                self.fail(f"load_user lanzó excepción no capturada para caso {caso!r}: {type(exc).__name__}: {exc}")


if __name__ == '__main__':
    unittest.main()
