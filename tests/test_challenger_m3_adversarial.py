"""Pruebas de desafío empírico y estrés adversarial para Milestone M3 (Challenger 2).

Verifica empíricamente:
1. Compatibilidad de la migración Alembic v46 (sintaxis batch, SQLite y PostgreSQL, upgrade y downgrade).
2. Comportamiento ante instructores inactivos (activo = False) en restablecimiento asistido y cambio forzado.
3. Anulación irreversible de tokens de autoservicio previos al ejecutar el restablecimiento administrativo.
4. Preservación estricta de las directivas de sesión de 365 días tras completar el cambio forzado.
5. Límites y entradas adversariales (espacios, contraseñas de 5/6/128/129 caracteres, unicode, CSRF y HTMX).
"""

import datetime
from datetime import timedelta
import hashlib
import importlib.util
import os
import secrets
import unittest
from unittest.mock import patch

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from flask import g
from sqlalchemy import create_engine, inspect, text

from app import create_app, db
from app.helpers import utc_now
from app.models.instructor import Instructor, load_user
from app.routes.admin import generar_clave_temporal

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_MIGRACION_V46 = os.path.join(
    RAIZ, 'migrations', 'versions', 'v46_debe_cambiar_password.py'
)


def _cargar_migracion_v46():
    spec = importlib.util.spec_from_file_location('v46_debe_cambiar_password', RUTA_MIGRACION_V46)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class AlembicMigrationV46EmpiricalTestCase(unittest.TestCase):
    """Desafío 1: Verificación empírica de reversibilidad y sintaxis batch en Alembic v46."""

    def setUp(self):
        self.motor = create_engine('sqlite:///:memory:')
        self.conexion = self.motor.connect()
        # Crear tabla instructores idéntica al estado previo a v46
        self.conexion.execute(text(
            'CREATE TABLE instructores ('
            'id INTEGER PRIMARY KEY, '
            'nombre VARCHAR(150) NOT NULL, '
            'correo VARCHAR(150) UNIQUE NOT NULL, '
            'password_hash VARCHAR(256) NOT NULL, '
            'auth_version INTEGER DEFAULT 1 NOT NULL, '
            'password_reset_token_hash VARCHAR(64), '
            'password_reset_expires_at TIMESTAMP, '
            "rol VARCHAR(20) DEFAULT 'colaborador' NOT NULL, "
            'activo BOOLEAN DEFAULT 1, '
            'creado_en TIMESTAMP'
            ')'
        ))
        self.conexion.execute(text(
            "INSERT INTO instructores (id, nombre, correo, password_hash, auth_version, activo) "
            "VALUES (1, 'Instructor Existente', 'existente@sena.edu.co', 'hash_previo_123', 1, 1)"
        ))
        self.conexion.commit()
        self.migracion = _cargar_migracion_v46()

    def tearDown(self):
        self.conexion.close()
        self.motor.dispose()

    def _aplicar(self, fn):
        contexto = MigrationContext.configure(self.conexion)
        with Operations.context(contexto):
            fn()
        self.conexion.commit()

    def test_v46_upgrade_agrega_columna_debe_cambiar_password_con_false(self):
        """upgrade() agrega debe_cambiar_password NOT NULL y asigna False a filas preexistentes."""
        self._aplicar(self.migracion.upgrade)

        columnas = {col['name']: col for col in inspect(self.conexion).get_columns('instructores')}
        self.assertIn('debe_cambiar_password', columnas)
        self.assertFalse(columnas['debe_cambiar_password']['nullable'])

        # Verificar que el registro preexistente tiene debe_cambiar_password == 0 / False
        fila = self.conexion.execute(
            text('SELECT id, nombre, debe_cambiar_password FROM instructores WHERE id = 1')
        ).fetchone()
        self.assertEqual(fila[0], 1)
        self.assertEqual(fila[1], 'Instructor Existente')
        self.assertFalse(bool(fila[2]))

    def test_v46_downgrade_remueve_columna_sin_afectar_datos(self):
        """downgrade() revierte de forma limpia la columna preservando las demás columnas y datos."""
        self._aplicar(self.migracion.upgrade)
        self._aplicar(self.migracion.downgrade)

        columnas = {col['name']: col for col in inspect(self.conexion).get_columns('instructores')}
        self.assertNotIn('debe_cambiar_password', columnas)

        fila = self.conexion.execute(
            text('SELECT id, nombre, correo, auth_version FROM instructores WHERE id = 1')
        ).fetchone()
        self.assertEqual(fila[0], 1)
        self.assertEqual(fila[1], 'Instructor Existente')
        self.assertEqual(fila[2], 'existente@sena.edu.co')
        self.assertEqual(fila[3], 1)

    def test_alembic_topologia_y_revisión_head(self):
        """Verifica la cadena de revisiones Alembic: v46cambiopassword tiene down_revision = u45avisospush."""
        config_alembic = Config()
        config_alembic.set_main_option(
            'script_location', os.path.join(RAIZ, 'migrations').replace('\\', '/')
        )
        scripts = ScriptDirectory.from_config(config_alembic)

        heads = scripts.get_heads()
        self.assertEqual(heads, ['v46cambiopassword'])
        rev_v46 = scripts.get_revision('v46cambiopassword')
        self.assertEqual(rev_v46.down_revision, 'u45avisospush')


class InactiveInstructorAssistedResetTestCase(unittest.TestCase):
    """Desafío 2: Restablecimiento asistido y cambio forzado con cuentas inactivas."""

    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'PUBLIC_BASE_URL': 'https://panel.example.com',
            'PERMANENT_SESSION_LIFETIME': timedelta(days=365),
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.admin = Instructor(
            nombre='Admin General',
            correo='admin@sena.edu.co',
            rol='admin',
            activo=True,
            auth_version=1,
        )
        self.admin.set_password('AdminPass123!')

        self.inactivo = Instructor(
            nombre='Instructor Bloqueado',
            correo='bloqueado@sena.edu.co',
            rol='colaborador',
            activo=False,
            auth_version=7,
            debe_cambiar_password=False,
            password_reset_token_hash='token_hash_previo_inactivo',
            password_reset_expires_at=utc_now() + timedelta(minutes=20),
        )
        self.inactivo.set_password('ClaveAntiguaInactivo!')

        db.session.add_all([self.admin, self.inactivo])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def test_restablecimiento_cuenta_inactiva_preserva_estado_y_no_emite_clave(self):
        """El administrador no puede asignar clave temporal a cuentas inactivas y el estado en DB queda intacto."""
        hash_original = self.inactivo.password_hash
        token_hash_original = self.inactivo.password_reset_token_hash

        cliente = self.app.test_client()
        cliente.post('/login', data={'correo': self.admin.correo, 'password': 'AdminPass123!'})

        respuesta = cliente.post(
            f'/admin/instructores/{self.inactivo.id}/restablecer-clave',
            data={'clave_temporal': 'NuevaClaveTemp1!'},
            follow_redirects=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('No se puede restablecer la contraseña de una cuenta inactiva.'.encode('utf-8'), respuesta.data)

        # Base de datos inmutable
        db.session.refresh(self.inactivo)
        self.assertEqual(self.inactivo.password_hash, hash_original)
        self.assertEqual(self.inactivo.auth_version, 7)
        self.assertFalse(self.inactivo.debe_cambiar_password)
        self.assertEqual(self.inactivo.password_reset_token_hash, token_hash_original)
        self.assertFalse(self.inactivo.check_password('NuevaClaveTemp1!'))
        self.assertTrue(self.inactivo.check_password('ClaveAntiguaInactivo!'))

    def test_desactivacion_posterior_de_instructor_impide_completar_cambio_forzado(self):
        """Si un instructor con debe_cambiar_password es desactivado, no puede completar el formulario de cambio."""
        instructor = Instructor(
            nombre='Instructor Pendiente',
            correo='pendiente@sena.edu.co',
            rol='colaborador',
            activo=True,
            auth_version=2,
            debe_cambiar_password=True,
        )
        instructor.set_password('ClaveTemporal123!')
        db.session.add(instructor)
        db.session.commit()

        # Inicia sesión mientras aún está activo
        cliente = self.app.test_client()
        resp_login = cliente.post('/login', data={'correo': instructor.correo, 'password': 'ClaveTemporal123!'})
        self.assertEqual(resp_login.status_code, 302)
        self.assertTrue(resp_login.headers['Location'].endswith('/cambiar-password-obligatorio'))

        # Ahora el administrador desactiva su cuenta en base de datos
        instructor.activo = False
        db.session.commit()
        g.pop('_login_user', None)

        # El instructor intenta enviar el formulario de cambio obligatorio
        resp_post = cliente.post('/cambiar-password-obligatorio', data={
            'nueva_password': 'MiNuevaClaveDefinitiva1!',
            'confirmacion': 'MiNuevaClaveDefinitiva1!',
        })
        # Debe ser rechazado porque load_user retorna None para usuarios inactivos
        self.assertEqual(resp_post.status_code, 302)
        self.assertIn('/login', resp_post.headers['Location'])

        # Verificar que la clave en DB NO fue modificada
        db.session.refresh(instructor)
        self.assertTrue(instructor.check_password('ClaveTemporal123!'))
        self.assertFalse(instructor.check_password('MiNuevaClaveDefinitiva1!'))


class PasswordResetTokenInvalidationTestCase(unittest.TestCase):
    """Desafío 3: Anulación simultánea de tokens de recuperación por autoservicio."""

    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'PUBLIC_BASE_URL': 'https://panel.example.com',
            'PERMANENT_SESSION_LIFETIME': timedelta(days=365),
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.admin = Instructor(
            nombre='Admin General',
            correo='admin@sena.edu.co',
            rol='admin',
            activo=True,
            auth_version=1,
        )
        self.admin.set_password('AdminPass123!')

        self.colaborador = Instructor(
            nombre='Pedro Colaborador',
            correo='pedro@sena.edu.co',
            rol='colaborador',
            activo=True,
            auth_version=1,
            debe_cambiar_password=False,
        )
        self.colaborador.set_password('ClaveViejaPedro1!')

        db.session.add_all([self.admin, self.colaborador])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def test_restablecimiento_asistido_invalida_token_autoservicio_pendiente(self):
        """Un token de autoservicio activo queda inmediatamente invalidado si el admin hace reset asistido."""
        # 1. Simular solicitud previa de recuperación por correo
        token_plano = secrets.token_urlsafe(32)
        hash_token = hashlib.sha256(token_plano.encode('ascii')).hexdigest()
        self.colaborador.password_reset_token_hash = hash_token
        self.colaborador.password_reset_expires_at = utc_now() + timedelta(minutes=25)
        db.session.commit()

        # 2. El administrador realiza restablecimiento asistido
        cliente_admin = self.app.test_client()
        cliente_admin.post('/login', data={'correo': self.admin.correo, 'password': 'AdminPass123!'})
        resp_admin = cliente_admin.post(
            f'/admin/instructores/{self.colaborador.id}/restablecer-clave',
            data={'clave_temporal': 'ClaveTemporal888!'},
        )
        self.assertEqual(resp_admin.status_code, 302)

        # 3. Verificar en base de datos que los campos de token fueron vaciados a None
        db.session.refresh(self.colaborador)
        self.assertIsNone(self.colaborador.password_reset_token_hash)
        self.assertIsNone(self.colaborador.password_reset_expires_at)
        self.assertEqual(self.colaborador.auth_version, 2)

        # 4. El usuario intenta usar el enlace de correo antiguo con el token original
        cliente_usuario = self.app.test_client()
        resp_intento = cliente_usuario.post(
            f'/restablecer-contrasena?token={token_plano}',
            data={
                'token': token_plano,
                'password': 'NuevaClaveHackeada1!',
                'confirmacion': 'NuevaClaveHackeada1!',
            },
            follow_redirects=True,
        )
        self.assertEqual(resp_intento.status_code, 200)
        self.assertIn('El enlace no es válido o venció. Solicita uno nuevo.'.encode('utf-8'), resp_intento.data)

        # Comprobar que la clave temporal asignada por el admin sigue intacta y la intentada por token no se aplicó
        db.session.refresh(self.colaborador)
        self.assertTrue(self.colaborador.check_password('ClaveTemporal888!'))
        self.assertFalse(self.colaborador.check_password('NuevaClaveHackeada1!'))

    def test_cambio_forzado_tambien_limpia_cualquier_token_residual(self):
        """Al completar cambiar_password_obligatorio, cualquier token residual en DB se elimina."""
        self.colaborador.debe_cambiar_password = True
        self.colaborador.password_reset_token_hash = 'token_residual_123'
        self.colaborador.password_reset_expires_at = utc_now() + timedelta(minutes=15)
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        resp = cliente.post('/cambiar-password-obligatorio', data={
            'nueva_password': 'ClaveLimpia2026!',
            'confirmacion': 'ClaveLimpia2026!',
        })
        self.assertEqual(resp.status_code, 302)

        db.session.refresh(self.colaborador)
        self.assertIsNone(self.colaborador.password_reset_token_hash)
        self.assertIsNone(self.colaborador.password_reset_expires_at)


class SessionDurationAndCookiesPreservationTestCase(unittest.TestCase):
    """Desafío 4: Preservación de 365 días en cookies de sesión tras cambio forzado."""

    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'PUBLIC_BASE_URL': 'https://panel.example.com',
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
            nombre='Instructor Sesion 365',
            correo='sesion365@sena.edu.co',
            rol='colaborador',
            activo=True,
            auth_version=1,
            debe_cambiar_password=True,
        )
        self.instructor.set_password('ClaveTemporal123!')
        db.session.add(self.instructor)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def test_directivas_de_cookie_tras_cambiar_password_obligatorio(self):
        """Verifica que cambiar_password_obligatorio emite Set-Cookie persistente de 365 días."""
        cliente = self.app.test_client()
        # Login inicial con clave temporal
        resp_login = cliente.post('/login', data={
            'correo': self.instructor.correo,
            'password': 'ClaveTemporal123!',
        })
        self.assertEqual(resp_login.status_code, 302)
        self.assertTrue(resp_login.headers['Location'].endswith('/cambiar-password-obligatorio'))

        # Envío del formulario de cambio forzado
        respuesta = cliente.post('/cambiar-password-obligatorio', data={
            'nueva_password': 'ClaveDefinitiva365Dias!',
            'confirmacion': 'ClaveDefinitiva365Dias!',
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta.headers['Location'].endswith('/instructor/'))

        # Inspección minuciosa de cabeceras Set-Cookie
        cabeceras = respuesta.headers.getlist('Set-Cookie')
        cookie_sesion_str = next((c for c in cabeceras if c.startswith('session=')), None)
        self.assertIsNotNone(cookie_sesion_str, 'Debe emitir cookie de session')
        self.assertIn('HttpOnly', cookie_sesion_str)
        self.assertIn('SameSite=Lax', cookie_sesion_str)
        self.assertIn('Expires=', cookie_sesion_str)

        # Inspección del objeto cookie en el cliente
        cookie_obj = cliente.get_cookie('session')
        self.assertIsNotNone(cookie_obj)
        self.assertTrue(cookie_obj.http_only)
        self.assertEqual(cookie_obj.same_site, 'Lax')
        self.assertIsNotNone(cookie_obj.expires)

        # Validar cálculo de días (aprox 365 días en el futuro ± 3 días)
        ahora = datetime.datetime.now(datetime.timezone.utc)
        dias_restantes = (cookie_obj.expires - ahora).total_seconds() / 86400.0
        self.assertGreater(dias_restantes, 360)
        self.assertLess(dias_restantes, 370)

        # Verificar cookie remember_token emitida por login_user(remember=True)
        cookie_remember_str = next((c for c in cabeceras if c.startswith('remember_token=')), None)
        self.assertIsNotNone(cookie_remember_str, 'Debe emitir cookie remember_token')
        self.assertIn('HttpOnly', cookie_remember_str)
        self.assertIn('Expires=', cookie_remember_str)

    def test_sesion_renovada_sobrevive_a_reinicio_simulado_de_navegador(self):
        """La sesión obtenida tras cambiar contraseña sobrevive al reinicio del navegador."""
        cliente = self.app.test_client()
        cliente.post('/login', data={
            'correo': self.instructor.correo,
            'password': 'ClaveTemporal123!',
        })
        cliente.post('/cambiar-password-obligatorio', data={
            'nueva_password': 'ClaveNuevaSobrevive!',
            'confirmacion': 'ClaveNuevaSobrevive!',
        })

        # Simular reinicio del navegador conservando solo cookies con expires
        nuevo_navegador = self.app.test_client()
        cookies_copiadas = 0
        for (_, _, _), c in cliente._cookies.items():
            if c.expires is not None or c.max_age is not None:
                nuevo_navegador.set_cookie(
                    key=c.key,
                    value=c.value,
                    domain=c.domain,
                    path=c.path,
                )
                cookies_copiadas += 1

        self.assertGreater(cookies_copiadas, 0)
        resp_reinicio = nuevo_navegador.get('/instructor/')
        self.assertEqual(resp_reinicio.status_code, 200)
        self.assertIn(self.instructor.nombre.encode('utf-8'), resp_reinicio.data)


class AdversarialInputAndEdgeCasesTestCase(unittest.TestCase):
    """Desafío 5: Entradas extremas, espacios en blanco, unicode y compatibilidad HTMX."""

    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'PUBLIC_BASE_URL': 'https://panel.example.com',
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.admin = Instructor(
            nombre='Admin Adversarial',
            correo='admin.adv@sena.edu.co',
            rol='admin',
            activo=True,
            auth_version=1,
        )
        self.admin.set_password('AdminPass123!')

        self.colaborador = Instructor(
            nombre='Colaborador Adv',
            correo='colab.adv@sena.edu.co',
            rol='colaborador',
            activo=True,
            auth_version=1,
        )
        self.colaborador.set_password('ColabPass123!')

        db.session.add_all([self.admin, self.colaborador])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def test_clave_manual_con_unicode_y_espacios(self):
        """Admite claves manuales con caracteres unicode y recorta espacios de los bordes."""
        cliente = self.app.test_client()
        cliente.post('/login', data={'correo': self.admin.correo, 'password': 'AdminPass123!'})

        # Clave con espacios externos y caracteres tildados
        clave_unicode = '  ClavéTildadaÑ2026!  '
        resp = cliente.post(
            f'/admin/instructores/{self.colaborador.id}/restablecer-clave',
            data={'clave_temporal': clave_unicode},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        db.session.refresh(self.colaborador)
        self.assertTrue(self.colaborador.debe_cambiar_password)
        # La clave almacenada debe ser la versión recortada
        self.assertTrue(self.colaborador.check_password('ClavéTildadaÑ2026!'))

    def test_interceptor_htmx_con_ruta_anidada(self):
        """Peticiones HTMX a rutas secundarias reciben HX-Redirect a /cambiar-password-obligatorio."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        resp = cliente.get(
            '/instructor/fichas',
            headers={'HX-Request': 'true'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get('HX-Redirect'), '/cambiar-password-obligatorio')


if __name__ == '__main__':
    unittest.main()
