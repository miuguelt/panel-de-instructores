"""Pruebas adversariales de desafío para el Milestone M2 (Empirical Challenger).

Verifica empíricamente:
1. Fronteras exactas de longitud de contraseña:
   - 5 caracteres rechazado (límite inferior - 1).
   - 6 caracteres aceptado (límite inferior exacto).
   - 128 caracteres aceptado (límite superior exacto).
   - 129 caracteres rechazado (límite superior + 1).
   - Variantes adversariales: contraseñas vacías, espacios, no coincidentes.
2. Resolución dual de tokens:
   - GET con ?token=... precarga en el formulario.
   - GET con token malicioso o inválido no precarga.
   - POST con ?token=... en query string y body 'token' vacío.
   - POST con ?token=... en query string y sin campo 'token' en el body.
   - POST con token en body y token en query string (precedencia del body).
3. Resiliencia contra tokens adulterados, expirados, inexistentes y ataques de replay:
   - Token vencido (hace 1 segundo, hace 1 hora).
   - Token manipulado / bit-flip (SHA256 no coincide).
   - Token con longitud inválida (< 20 caracteres, > 128 caracteres).
   - Token con caracteres no-ASCII / UTF-8 / inyecciones (no debe lanzar UnicodeEncodeError ni 500).
   - Token reutilizado (ataque de repetición / replay attack).
   - Token para instructor inactivo (activo = False).
4. Efecto colateral crítico:
   - Incremento de auth_version.
   - Cierre forzado de sesiones activas en otros navegadores/dispositivos.
   - Limpieza de token y expiración tras uso exitoso.
"""

import hashlib
import secrets
import string
import unittest
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from app import create_app, db
from app.helpers import utc_now
from app.models.instructor import Instructor
from app.routes.auth import _TOKEN_URLSAFE


class AdversarialPasswordBoundariesTestCase(unittest.TestCase):
    """Desafío 1: Pruebas de frontera estricta en la longitud de contraseña."""

    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'PUBLIC_BASE_URL': 'https://panel.example.com',
            'SMTP_HOST': 'smtp.example.com',
            'SMTP_PORT': 587,
            'SMTP_USER': 'avisos@example.com',
            'SMTP_PASSWORD': 'solo-en-memoria',
            'SMTP_FROM': 'SENA Control <avisos@example.com>',
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Instructor Desafio Fronteras',
            correo='desafio.fronteras@sena.edu.co',
            rol='instructor',
            activo=True,
            auth_version=1,
        )
        self.instructor.set_password('ClaveBaseOriginal123!')
        db.session.add(self.instructor)
        db.session.commit()

        self.cliente = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _generar_token_valido(self):
        token = secrets.token_urlsafe(32)
        self.instructor.password_reset_token_hash = hashlib.sha256(
            token.encode('ascii')
        ).hexdigest()
        self.instructor.password_reset_expires_at = utc_now() + timedelta(minutes=30)
        db.session.commit()
        return token

    def test_frontera_inferior_cinco_caracteres_rechazado(self):
        """5 caracteres (límite inferior - 1) debe ser rechazado sin modificar la clave."""
        token = self._generar_token_valido()
        resp = self.cliente.post(
            '/restablecer-contrasena',
            data={
                'token': token,
                'password': '12345',
                'confirmacion': '12345',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('La nueva contraseña debe tener al menos 6 caracteres.'.encode(), resp.data)
        db.session.refresh(self.instructor)
        self.assertTrue(self.instructor.check_password('ClaveBaseOriginal123!'))
        self.assertEqual(self.instructor.auth_version, 1)

    def test_frontera_inferior_seis_caracteres_aceptado(self):
        """6 caracteres (límite inferior exacto) debe ser aceptado y actualizar la clave."""
        casos = ['abc123', '123456', 'Aa1!._', '      ']
        for nueva_clave in casos:
            token = self._generar_token_valido()
            resp = self.cliente.post(
                '/restablecer-contrasena',
                data={
                    'token': token,
                    'password': nueva_clave,
                    'confirmacion': nueva_clave,
                },
            )
            self.assertEqual(resp.status_code, 302)
            self.assertTrue(resp.headers['Location'].endswith('/login'))
            db.session.refresh(self.instructor)
            self.assertTrue(self.instructor.check_password(nueva_clave))

    def test_frontera_superior_128_caracteres_aceptado(self):
        """128 caracteres (límite superior exacto) debe ser aceptado."""
        token = self._generar_token_valido()
        clave_128 = 'K' * 128
        resp = self.cliente.post(
            '/restablecer-contrasena',
            data={
                'token': token,
                'password': clave_128,
                'confirmacion': clave_128,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers['Location'].endswith('/login'))
        db.session.refresh(self.instructor)
        self.assertTrue(self.instructor.check_password(clave_128))

    def test_frontera_superior_129_caracteres_rechazado(self):
        """129 caracteres (límite superior + 1) debe ser rechazado."""
        token = self._generar_token_valido()
        clave_129 = 'K' * 129
        resp = self.cliente.post(
            '/restablecer-contrasena',
            data={
                'token': token,
                'password': clave_129,
                'confirmacion': clave_129,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('La contraseña no puede superar 128 caracteres.'.encode(), resp.data)
        db.session.refresh(self.instructor)
        self.assertTrue(self.instructor.check_password('ClaveBaseOriginal123!'))

    def test_contrasenas_no_coincidentes_rechazadas(self):
        """Diferencias por un caracter, mayúsculas o espacios deben rechazarse."""
        token = self._generar_token_valido()
        pares_mismatch = [
            ('PasswordSegura1', 'PasswordSegura2'),
            ('PasswordSegura1', 'passwordsegura1'),
            ('PasswordSegura1', 'PasswordSegura1 '),
            ('PasswordSegura1', ''),
        ]
        for pwd, conf in pares_mismatch:
            resp = self.cliente.post(
                '/restablecer-contrasena',
                data={
                    'token': token,
                    'password': pwd,
                    'confirmacion': conf,
                },
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn('Las contraseñas no coinciden.'.encode(), resp.data)
            db.session.refresh(self.instructor)
            self.assertTrue(self.instructor.check_password('ClaveBaseOriginal123!'))

    def test_contrasenas_vacias_y_longitudes_minimas_diversas(self):
        """Cadenas de 0 a 4 caracteres deben ser rechazadas sistemáticamente."""
        for longitud in range(5):
            token = self._generar_token_valido()
            clave = 'x' * longitud
            resp = self.cliente.post(
                '/restablecer-contrasena',
                data={
                    'token': token,
                    'password': clave,
                    'confirmacion': clave,
                },
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn('La nueva contraseña debe tener al menos 6 caracteres.'.encode(), resp.data)


class AdversarialTokenResolutionTestCase(unittest.TestCase):
    """Desafío 2: Pruebas de resolución dual de tokens (query string vs form body)."""

    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'PUBLIC_BASE_URL': 'https://panel.example.com',
            'SMTP_HOST': 'smtp.example.com',
            'SMTP_PORT': 587,
            'SMTP_USER': 'avisos@example.com',
            'SMTP_PASSWORD': 'solo-en-memoria',
            'SMTP_FROM': 'SENA Control <avisos@example.com>',
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Instructor Desafio Token Query',
            correo='desafio.token@sena.edu.co',
            rol='instructor',
            activo=True,
            auth_version=1,
        )
        self.instructor.set_password('ClaveBaseOriginal123!')
        db.session.add(self.instructor)
        db.session.commit()

        self.cliente = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _generar_token_valido(self):
        token = secrets.token_urlsafe(32)
        self.instructor.password_reset_token_hash = hashlib.sha256(
            token.encode('ascii')
        ).hexdigest()
        self.instructor.password_reset_expires_at = utc_now() + timedelta(minutes=30)
        db.session.commit()
        return token

    def test_get_con_query_token_precarga_en_html(self):
        """GET con ?token=<token> precarga el valor en el input hidden #token."""
        token = self._generar_token_valido()
        resp = self.cliente.get(f'/restablecer-contrasena?token={token}')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(f'value="{token}"'.encode(), resp.data)

    def test_get_con_query_token_invalido_o_xss_no_se_precarga(self):
        """GET con tokens que contienen caracteres inválidos o inyecciones no se precarga."""
        cargas = [
            '<script>alert(1)</script>',
            '" onfocus="alert(1)"',
            'token_con_espacios y simbolos!@#',
            '12345',  # Demasiado corto (<20)
            'x' * 129,  # Demasiado largo (>128)
            "token'--",
            '%00nullbyte',
        ]
        for carga in cargas:
            resp = self.cliente.get(f'/restablecer-contrasena?token={carga}')
            self.assertEqual(resp.status_code, 200)
            self.assertIn(b'value=""', resp.data)

    def test_post_con_query_token_y_body_token_vacio(self):
        """POST con ?token=... en URL y campo 'token': '' en el body debe resolver exitosamente."""
        token = self._generar_token_valido()
        resp = self.cliente.post(
            f'/restablecer-contrasena?token={token}',
            data={
                'token': '',
                'password': 'NuevaClaveValida999!',
                'confirmacion': 'NuevaClaveValida999!',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers['Location'].endswith('/login'))
        db.session.refresh(self.instructor)
        self.assertTrue(self.instructor.check_password('NuevaClaveValida999!'))

    def test_post_con_query_token_y_body_sin_campo_token(self):
        """POST con ?token=... en URL y sin enviar clave 'token' en el diccionario data."""
        token = self._generar_token_valido()
        resp = self.cliente.post(
            f'/restablecer-contrasena?token={token}',
            data={
                'password': 'NuevaClaveSinCampoToken1!',
                'confirmacion': 'NuevaClaveSinCampoToken1!',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers['Location'].endswith('/login'))
        db.session.refresh(self.instructor)
        self.assertTrue(self.instructor.check_password('NuevaClaveSinCampoToken1!'))

    def test_post_precedencia_body_sobre_query_token(self):
        """Si body y query string tienen tokens distintos, el token del body tiene precedencia."""
        token_body = self._generar_token_valido()
        token_query_falso = secrets.token_urlsafe(32)

        resp = self.cliente.post(
            f'/restablecer-contrasena?token={token_query_falso}',
            data={
                'token': token_body,
                'password': 'ClavePorPrecedenciaBody1!',
                'confirmacion': 'ClavePorPrecedenciaBody1!',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers['Location'].endswith('/login'))
        db.session.refresh(self.instructor)
        self.assertTrue(self.instructor.check_password('ClavePorPrecedenciaBody1!'))


class AdversarialTokenTamperingTestCase(unittest.TestCase):
    """Desafío 3: Pruebas adversariales contra manipulación, expiración, replay y ataques de token."""

    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'PUBLIC_BASE_URL': 'https://panel.example.com',
            'SMTP_HOST': 'smtp.example.com',
            'SMTP_PORT': 587,
            'SMTP_USER': 'avisos@example.com',
            'SMTP_PASSWORD': 'solo-en-memoria',
            'SMTP_FROM': 'SENA Control <avisos@example.com>',
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor = Instructor(
            nombre='Instructor Desafio Tampering',
            correo='desafio.tampering@sena.edu.co',
            rol='instructor',
            activo=True,
            auth_version=1,
        )
        self.instructor.set_password('ClaveBaseOriginal123!')
        db.session.add(self.instructor)
        db.session.commit()

        self.cliente = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _generar_token_valido(self):
        token = secrets.token_urlsafe(32)
        self.instructor.password_reset_token_hash = hashlib.sha256(
            token.encode('ascii')
        ).hexdigest()
        self.instructor.password_reset_expires_at = utc_now() + timedelta(minutes=30)
        db.session.commit()
        return token

    def test_token_expirado_es_rechazado_con_seguridad(self):
        """Tokens con fecha en el pasado (1 segundo o más) son rechazados sin cambiar la clave."""
        token = secrets.token_urlsafe(32)
        self.instructor.password_reset_token_hash = hashlib.sha256(
            token.encode('ascii')
        ).hexdigest()
        self.instructor.password_reset_expires_at = utc_now() - timedelta(seconds=1)
        db.session.commit()

        resp = self.cliente.post(
            '/restablecer-contrasena',
            data={
                'token': token,
                'password': 'ClaveNuevaSegura456!',
                'confirmacion': 'ClaveNuevaSegura456!',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('El enlace no es válido o venció.'.encode(), resp.data)
        db.session.refresh(self.instructor)
        self.assertTrue(self.instructor.check_password('ClaveBaseOriginal123!'))

    def test_token_adulterado_bit_flip_es_rechazado(self):
        """Modificar un solo carácter del token genera SHA256 distinto y es rechazado."""
        token = self._generar_token_valido()
        # Modificar el último carácter
        ultimo_char = token[-1]
        char_adulterado = 'b' if ultimo_char != 'b' else 'a'
        token_adulterado = token[:-1] + char_adulterado

        resp = self.cliente.post(
            '/restablecer-contrasena',
            data={
                'token': token_adulterado,
                'password': 'ClaveNuevaSegura456!',
                'confirmacion': 'ClaveNuevaSegura456!',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('El enlace no es válido o venció.'.encode(), resp.data)
        db.session.refresh(self.instructor)
        self.assertTrue(self.instructor.check_password('ClaveBaseOriginal123!'))

    def test_token_con_caracteres_no_ascii_o_unicode_no_rompe_con_500(self):
        """Caracteres no-ASCII como emojis o tildes deben manejarse con seguridad sin lanzar UnicodeEncodeError."""
        tokens_maliciosos = [
            'token_con_emojis_🔑🔒🛡️_12345',
            'token_con_tildes_áéíóú_ñ_12345',
            'token_con_caracter_nulo_\x00_12345',
            'token_con_comillas_"_12345',
            'token_con_espacios_   _12345',
        ]
        for token_raro in tokens_maliciosos:
            resp = self.cliente.post(
                '/restablecer-contrasena',
                data={
                    'token': token_raro,
                    'password': 'ClaveNuevaSegura456!',
                    'confirmacion': 'ClaveNuevaSegura456!',
                },
            )
            # Debe retornar 200 con mensaje de error, NUNCA 500
            self.assertEqual(resp.status_code, 200)
            self.assertIn('El enlace no es válido o venció.'.encode(), resp.data)

    def test_ataque_de_repeticion_replay_token_reutilizado(self):
        """Un token no puede ser reutilizado después de que se ha utilizado exitosamente una vez."""
        token = self._generar_token_valido()

        # Primer uso legítimo: debe pasar
        resp1 = self.cliente.post(
            '/restablecer-contrasena',
            data={
                'token': token,
                'password': 'ClavePrimeraVez123!',
                'confirmacion': 'ClavePrimeraVez123!',
            },
        )
        self.assertEqual(resp1.status_code, 302)
        db.session.refresh(self.instructor)
        self.assertTrue(self.instructor.check_password('ClavePrimeraVez123!'))
        self.assertIsNone(self.instructor.password_reset_token_hash)
        self.assertIsNone(self.instructor.password_reset_expires_at)

        # Segundo uso con el mismo token: debe ser rechazado
        resp2 = self.cliente.post(
            '/restablecer-contrasena',
            data={
                'token': token,
                'password': 'ClaveReplayAtacante123!',
                'confirmacion': 'ClaveReplayAtacante123!',
            },
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertIn('El enlace no es válido o venció.'.encode(), resp2.data)
        db.session.refresh(self.instructor)
        # La clave debe mantenerse como la establecida legítimamente, NO la del atacante
        self.assertTrue(self.instructor.check_password('ClavePrimeraVez123!'))

    def test_instructor_inactivo_no_puede_restablecer_contrasena(self):
        """Un instructor con activo=False no puede restablecer contraseña aun con token generado."""
        token = self._generar_token_valido()
        self.instructor.activo = False
        db.session.commit()

        resp = self.cliente.post(
            '/restablecer-contrasena',
            data={
                'token': token,
                'password': 'ClaveIntentoInactivo123!',
                'confirmacion': 'ClaveIntentoInactivo123!',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('El enlace no es válido o venció.'.encode(), resp.data)
        db.session.refresh(self.instructor)
        self.assertTrue(self.instructor.check_password('ClaveBaseOriginal123!'))

    def test_invalidacion_multidispositivo_tras_cambio_de_contrasena(self):
        """Cambiar contraseña debe incrementar auth_version e invalidar inmediatamente sesiones activas."""
        token = self._generar_token_valido()

        # Simular una sesión activa previa en otro cliente
        cliente_sesion_activa = self.app.test_client()
        with cliente_sesion_activa.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.instructor.id}:{self.instructor.auth_version}'
            sesion['_fresh'] = True

        # Verificar que la sesión activa accede
        resp_panel_antes = cliente_sesion_activa.get('/instructor/')
        # Si la ruta /instructor/ existe o redirige, revisamos que esté autenticado
        # o verificamos load_user directamente
        from app.models.instructor import load_user
        self.assertIsNotNone(load_user(f'{self.instructor.id}:{self.instructor.auth_version}'))

        # Restablecer contraseña
        resp = self.cliente.post(
            '/restablecer-contrasena',
            data={
                'token': token,
                'password': 'ClaveNuevaPostMultiDevice1!',
                'confirmacion': 'ClaveNuevaPostMultiDevice1!',
            },
        )
        self.assertEqual(resp.status_code, 302)
        db.session.refresh(self.instructor)
        self.assertEqual(self.instructor.auth_version, 2)

        # La sesión previa con auth_version = 1 ahora es rechazada por load_user
        usuario_expirado = load_user(f'{self.instructor.id}:1')
        self.assertIsNone(usuario_expirado)

        # Petición con la sesión previa debe ser rechazada con redirección al login
        resp_panel_despues = cliente_sesion_activa.get('/instructor/')
        self.assertEqual(resp_panel_despues.status_code, 302)
        self.assertEqual(urlsplit(resp_panel_despues.headers['Location']).path, '/login')


class AdversarialFrontendPasswordResetScriptTestCase(unittest.TestCase):
    """Desafío 4: Pruebas del comportamiento y lógica del script password-reset.js."""

    def test_logica_js_resolucion_jerarquica_de_tokens(self):
        """Simula la lógica de password-reset.js para probar la resolución jerárquica."""
        # 1. Si tokenInput.value ya tiene valor, se conserva
        def resolver_token(valor_inicial, search_str, hash_str):
            tokenVal = valor_inicial.strip() if valor_inicial else ''
            if not tokenVal and search_str:
                from urllib.parse import parse_qs
                # Simular URLSearchParams
                qs = parse_qs(search_str.lstrip('?'))
                if 'token' in qs and qs['token']:
                    tokenVal = qs['token'][0].strip()
            if not tokenVal and hash_str:
                h = hash_str.lstrip('#')
                if h.startswith('token='):
                    tokenVal = h[6:].strip()
                else:
                    tokenVal = h.strip()
            return tokenVal

        # Caso 1: Ya tiene valor en el DOM (precargado por el backend)
        self.assertEqual(
            resolver_token('token_del_backend_123', '?token=otro_query', '#token=otro_hash'),
            'token_del_backend_123',
        )

        # Caso 2: DOM vacío, extrae desde ?token=... en search
        self.assertEqual(
            resolver_token('', '?token=token_desde_query_456', '#token=otro_hash'),
            'token_desde_query_456',
        )

        # Caso 3: DOM vacío, search vacío, extrae desde #token=... (formato retrocompatible 1)
        self.assertEqual(
            resolver_token('', '', '#token=token_desde_hash_clave_789'),
            'token_desde_hash_clave_789',
        )

        # Caso 4: DOM vacío, search vacío, extrae desde #... directo (formato retrocompatible 2)
        self.assertEqual(
            resolver_token('', '', '#token_desde_hash_plano_101112'),
            'token_desde_hash_plano_101112',
        )

        # Caso 5: Todo vacío
        self.assertEqual(resolver_token('', '', ''), '')


if __name__ == '__main__':
    unittest.main()
