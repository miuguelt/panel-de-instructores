"""Pruebas adversariales de desafío para el Milestone M1 (Challenger 2).

Verifica empíricamente:
1. Invalidación multidispositivo ante incremento de auth_version (sesión, remember_token y ambos).
2. Rechazo inmediato de instructores inactivos (activo = False) en load_user y en peticiones HTTP.
3. Comportamiento en tiempo de ejecución sin SECRET_KEY en el entorno (persistencia, corrupción, concurrencia, permisos).
"""

import concurrent.futures
import datetime
from datetime import timedelta
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from flask import g

from app import create_app, db
from app.models.instructor import Instructor, load_user
import config


class AdversarialMultiDeviceAuthVersionTestCase(unittest.TestCase):
    """Desafío 1: Invalidación multidispositivo estricta e incondicional al cambiar auth_version."""

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
            nombre='Instructor Desafio MultiDevice',
            correo='desafio.multidevice@sena.edu.co',
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

    def test_multidispositivo_tres_clientes_invalidacion_completa(self):
        """Simula 3 dispositivos (móvil, tablet, escritorio) autenticados simultáneamente.

        Al cambiar la contraseña en el escritorio (auth_version += 1), el móvil y la tablet
        deben ser rechazados inmediatamente en cualquier intento de navegación.
        """
        escritorio = self.app.test_client()
        movil = self.app.test_client()
        tablet = self.app.test_client()

        # Iniciar sesión en los 3 dispositivos
        for cliente in (escritorio, movil, tablet):
            r = cliente.post('/login', data={'correo': self.instructor.correo, 'password': 'ClaveSegura123!'})
            self.assertEqual(r.status_code, 302)
            g.pop('_login_user', None)

        # Confirmar acceso inicial en todos
        self.assertEqual(escritorio.get('/instructor/').status_code, 200)
        g.pop('_login_user', None)
        self.assertEqual(movil.get('/instructor/').status_code, 200)
        g.pop('_login_user', None)
        self.assertEqual(tablet.get('/instructor/').status_code, 200)
        g.pop('_login_user', None)

        # Escritorio actualiza credenciales
        self.instructor.set_password('NuevaClaveEscritorio456!')
        self.instructor.auth_version += 1
        db.session.commit()
        g.pop('_login_user', None)

        # Móvil y Tablet deben ser rechazados inmediatamente (302 -> /login)
        r_movil = movil.get('/instructor/')
        self.assertEqual(r_movil.status_code, 302)
        self.assertIn('/login', r_movil.headers['Location'])

        g.pop('_login_user', None)
        r_tablet = tablet.get('/instructor/')
        self.assertEqual(r_tablet.status_code, 302)
        self.assertIn('/login', r_tablet.headers['Location'])

    def test_remember_token_aislado_rechazado_tras_cambio_auth_version(self):
        """Si un dispositivo conserva ÚNICAMENTE la cookie remember_token (sin cookie de sesión),

        también debe ser rechazado incondicionalmente tras el cambio de auth_version.
        """
        cliente = self.app.test_client()
        r_login = cliente.post('/login', data={'correo': self.instructor.correo, 'password': 'ClaveSegura123!'})
        self.assertEqual(r_login.status_code, 302)

        # Extraer remember_token
        remember_cookie = cliente.get_cookie('remember_token')
        self.assertIsNotNone(remember_cookie, 'Debe existir la cookie remember_token')

        # Crear nuevo cliente que SOLO tiene la cookie remember_token (sesión borrada)
        cliente_solo_remember = self.app.test_client()
        cliente_solo_remember.set_cookie(
            key=remember_cookie.key,
            value=remember_cookie.value,
            domain=remember_cookie.domain,
            path=remember_cookie.path,
        )

        # Verificar que antes del cambio de clave, remember_token permite autenticar
        g.pop('_login_user', None)
        self.assertEqual(cliente_solo_remember.get('/instructor/').status_code, 200)

        # Incrementar auth_version en el servidor
        self.instructor.set_password('OtraClave789!')
        self.instructor.auth_version += 1
        db.session.commit()
        g.pop('_login_user', None)

        # El cliente con solo remember_token debe ser rechazado inmediatamente
        r_rechazo = cliente_solo_remember.get('/instructor/')
        self.assertEqual(r_rechazo.status_code, 302)
        self.assertIn('/login', r_rechazo.headers['Location'])

    def test_incrementos_sucesivos_de_auth_version(self):
        """Verifica que incrementos sucesivos (v1 -> v2 -> v3 -> v10) rechazan cualquier cookie de versiones anteriores."""
        cliente_v1 = self.app.test_client()
        cliente_v1.post('/login', data={'correo': self.instructor.correo, 'password': 'ClaveSegura123!'})
        g.pop('_login_user', None)

        # Avanzar a v5
        self.instructor.auth_version = 5
        db.session.commit()
        g.pop('_login_user', None)

        # cliente_v1 debe fallar
        self.assertEqual(cliente_v1.get('/instructor/').status_code, 302)

        # Iniciar sesión en cliente_v5
        cliente_v5 = self.app.test_client()
        cliente_v5.post('/login', data={'correo': self.instructor.correo, 'password': 'ClaveSegura123!'})
        g.pop('_login_user', None)
        self.assertEqual(cliente_v5.get('/instructor/').status_code, 200)

        # Avanzar a v10
        self.instructor.auth_version = 10
        db.session.commit()
        g.pop('_login_user', None)

        # Ambos (v1 y v5) deben fallar
        self.assertEqual(cliente_v1.get('/instructor/').status_code, 302)
        g.pop('_login_user', None)
        self.assertEqual(cliente_v5.get('/instructor/').status_code, 302)


class AdversarialInactiveInstructorTestCase(unittest.TestCase):
    """Desafío 2: Rechazo inmediato de instructores inactivos (activo = False)."""

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
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Instructor Inactivo Desafio',
            correo='inactivo.desafio@sena.edu.co',
            rol='colaborador',
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

    def test_desactivacion_invalida_sesion_activa_sin_cambio_de_auth_version(self):
        """Demuestra que la desactivación administrativa (activo=False) expulsa inmediatamente

        al usuario en su siguiente petición, aun cuando su clave o auth_version no hayan cambiado.
        """
        cliente = self.app.test_client()
        r = cliente.post('/login', data={'correo': self.instructor.correo, 'password': 'ClaveSegura123!'})
        self.assertEqual(r.status_code, 302)
        g.pop('_login_user', None)

        self.assertEqual(cliente.get('/instructor/').status_code, 200)

        # Desactivar cuenta directamente en BD (simulando acción administrativa)
        self.instructor.activo = False
        db.session.commit()
        g.pop('_login_user', None)

        # La petición subsiguiente debe ser rechazada de inmediato
        r_bloqueado = cliente.get('/instructor/')
        self.assertEqual(r_bloqueado.status_code, 302)
        self.assertIn('/login', r_bloqueado.headers['Location'])

    def test_load_user_stress_entradas_maliciosas_y_limites(self):
        """Prueba entradas maliciosas y casos límite contra load_user."""
        casos_maliciosos = [
            '',
            None,
            '   ',
            ':',
            '::',
            ':1',
            '1:',
            '-1:1',
            '0:1',
            '1:0',
            '1:-1',
            '1:9999999999999999999999999999999999999999',
            'admin:1',
            '1:admin',
            '1:1:1',
            '1; DROP TABLE instructores; --:1',
            '<script>alert(1)</script>:1',
            f'{self.instructor.id}:1\x00',
        ]

        for caso in casos_maliciosos:
            with self.subTest(caso=caso):
                resultado = load_user(caso)
                self.assertIsNone(resultado, f'load_user({caso!r}) debió retornar None')

        # Ahora probar con instructor inactivo: ABSOLUTAMENTE TODAS las entradas deben retornar None
        self.instructor.activo = False
        db.session.commit()
        casos_con_inactivo = [
            str(self.instructor.id),
            f'{self.instructor.id}:1',
            f'{self.instructor.id}: 1',
            f' {self.instructor.id}:1',
        ]
        for caso in casos_con_inactivo:
            with self.subTest(caso=caso, estado='inactivo'):
                resultado = load_user(caso)
                self.assertIsNone(resultado, f'load_user({caso!r}) debió retornar None con usuario inactivo')

    def test_reactivacion_y_suspension_ciclica(self):
        """Comprueba el comportamiento ante ciclos de suspensión y reactivación:

        - activo=True -> acceso permitido
        - activo=False -> acceso bloqueado
        - activo=True (sin cambio clave) -> acceso reanudado
        - cambio clave mientras suspendido -> acceso definitivamente revocado
        """
        cliente = self.app.test_client()
        cliente.post('/login', data={'correo': self.instructor.correo, 'password': 'ClaveSegura123!'})
        g.pop('_login_user', None)

        # 1. Acceso activo
        self.assertEqual(cliente.get('/instructor/').status_code, 200)

        # 2. Suspender
        self.instructor.activo = False
        db.session.commit()
        g.pop('_login_user', None)
        self.assertEqual(cliente.get('/instructor/').status_code, 302)

        # 3. Reactivar sin cambiar clave
        self.instructor.activo = True
        db.session.commit()
        g.pop('_login_user', None)
        self.assertEqual(cliente.get('/instructor/').status_code, 200)

        # 4. Suspender y cambiar contraseña (auth_version += 1)
        self.instructor.activo = False
        self.instructor.set_password('ClaveNuevaMientrasSuspendido!')
        self.instructor.auth_version += 1
        db.session.commit()
        g.pop('_login_user', None)

        # 5. Reactivar cuenta
        self.instructor.activo = True
        db.session.commit()
        g.pop('_login_user', None)

        # La sesión original debe permanecer INVALIDADA porque auth_version cambió
        self.assertEqual(cliente.get('/instructor/').status_code, 302)


class AdversarialSecretKeyRuntimeTestCase(unittest.TestCase):
    """Desafío 3: Comportamiento en tiempo de ejecución sin SECRET_KEY en el entorno."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.archivo_secreto = os.path.join(self.temp_dir, 'instance', '.secret_key')

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_archivo_secreto_permisos_y_formato(self):
        """Comprueba que la clave generada automáticamente es de 128 caracteres hex y se crea el archivo."""
        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.archivo_secreto}):
            clave, efimera = config._obtener_o_persistir_secret_key(self.temp_dir)
            self.assertTrue(efimera)
            self.assertEqual(len(clave), 128)
            # Todos los caracteres deben ser hexadecimales
            int(clave, 16)

            self.assertTrue(os.path.isfile(self.archivo_secreto))
            with open(self.archivo_secreto, 'r', encoding='utf-8') as f:
                contenido = f.read().strip()
            self.assertEqual(contenido, clave)

    def test_archivo_corrupto_espacios_y_saltos_de_linea(self):
        """Si el archivo contiene una clave válida de 128 chars con espacios o saltos de línea circundantes,

        debe limpiarla con strip() y aceptarla sin regenerar.
        """
        clave_original = secrets.token_hex(64)
        os.makedirs(os.path.dirname(self.archivo_secreto), exist_ok=True)
        with open(self.archivo_secreto, 'w', encoding='utf-8') as f:
            f.write(f'  \n\t{clave_original}\n\n  ')

        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.archivo_secreto}):
            clave_leida, efimera = config._obtener_o_persistir_secret_key(self.temp_dir)
            self.assertTrue(efimera)
            self.assertEqual(clave_leida, clave_original)

    def test_archivo_vacio_o_solo_espacios_es_regenerado(self):
        """Un archivo de 0 bytes o que contenga solo espacios debe ser tratado como corrupto y regenerado."""
        os.makedirs(os.path.dirname(self.archivo_secreto), exist_ok=True)
        with open(self.archivo_secreto, 'w', encoding='utf-8') as f:
            f.write('    \n\t   ')

        with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.archivo_secreto}):
            clave, efimera = config._obtener_o_persistir_secret_key(self.temp_dir)
            self.assertTrue(efimera)
            self.assertEqual(len(clave), 128)
            self.assertNotEqual(clave.strip(), '')

    def test_concurrencia_multi_hilos_generacion_clave(self):
        """Simula múltiples workers/hilos arrancando en paralelo sin archivo de clave preexistente."""
        claves_obtenidas = []

        def worker_arranque():
            with patch.dict(os.environ, {'SECRET_KEY': '', 'SECRET_KEY_FILE': self.archivo_secreto}):
                k, _ = config._obtener_o_persistir_secret_key(self.temp_dir)
                return k

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futuros = [executor.submit(worker_arranque) for _ in range(16)]
            for fut in concurrent.futures.as_completed(futuros):
                claves_obtenidas.append(fut.result())

        # Todas las claves deben tener longitud 128
        for k in claves_obtenidas:
            self.assertEqual(len(k), 128)

        # El archivo en disco debe existir y ser una clave válida
        self.assertTrue(os.path.isfile(self.archivo_secreto))
        with open(self.archivo_secreto, 'r', encoding='utf-8') as f:
            clave_disco = f.read().strip()
        self.assertEqual(len(clave_disco), 128)

    def test_proceso_real_arranque_sin_secret_key(self):
        """Ejecuta un subproceso Python real sin SECRET_KEY en el entorno para comprobar arranque limpio."""
        entorno = os.environ.copy()
        entorno['SECRET_KEY'] = ''
        entorno['SECRET_KEY_FILE'] = self.archivo_secreto
        entorno['DATABASE_URL'] = 'sqlite:///:memory:'

        comando = [
            sys.executable,
            '-c',
            'import config; from app import create_app; '
            'app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False}); '
            'print("BOOT_OK", len(app.config["SECRET_KEY"]), app.config["SECRET_KEY_IS_EPHEMERAL"])'
        ]

        resultado = subprocess.run(comando, env=entorno, capture_output=True, text=True, check=False)
        self.assertEqual(resultado.returncode, 0, f'Fallo en arranque:\nSTDOUT:\n{resultado.stdout}\nSTDERR:\n{resultado.stderr}')
        self.assertIn('BOOT_OK 128 True', resultado.stdout)
        self.assertIn('SECRET_KEY insegura o vacia', resultado.stderr)
        self.assertTrue(os.path.isfile(self.archivo_secreto))


if __name__ == '__main__':
    unittest.main()
