"""Pruebas de restablecimiento asistido por administrador y cambio forzado de contraseña."""

import re
import unittest
from datetime import timedelta

from flask import g, get_flashed_messages
from app import create_app, db
from app.models.instructor import Instructor
from app.routes.admin import generar_clave_temporal


class AdminRestablecimientoTestCase(unittest.TestCase):
    """Pruebas unitarias y de integración para la gestión administrativa y cambio forzado."""

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

        # Instructor Administrador
        self.admin = Instructor(
            nombre='Instructor Administrador',
            correo='admin@sena.edu.co',
            rol='admin',
            activo=True,
            auth_version=1,
            debe_cambiar_password=False,
        )
        self.admin.set_password('AdminPass123!')

        # Instructor Colaborador estándar
        self.colaborador = Instructor(
            nombre='Carlos Colaborador',
            correo='colaborador@sena.edu.co',
            rol='colaborador',
            activo=True,
            auth_version=1,
            debe_cambiar_password=False,
        )
        self.colaborador.set_password('ColabPass123!')

        # Instructor Inactivo
        self.inactivo = Instructor(
            nombre='Inactivo SENA',
            correo='inactivo@sena.edu.co',
            rol='colaborador',
            activo=False,
            auth_version=1,
            debe_cambiar_password=False,
        )
        self.inactivo.set_password('InactivoPass123!')

        db.session.add_all([self.admin, self.colaborador, self.inactivo])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    # --- 1. Decorador y control de acceso @admin_required ---

    def test_admin_required_anonimo_redirige_a_login(self):
        """Usuario anónimo es redirigido a login al intentar acceder a rutas administrativas."""
        cliente = self.app.test_client()
        respuesta = cliente.get('/admin/instructores')
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/login', respuesta.headers['Location'])

    def test_admin_required_no_admin_aborta_403(self):
        """Instructor sin rol admin recibe 403 Forbidden en rutas administrativas."""
        cliente = self.app.test_client()
        cliente.post('/login', data={
            'correo': self.colaborador.correo,
            'password': 'ColabPass123!',
        })
        respuesta_get = cliente.get('/admin/instructores')
        self.assertEqual(respuesta_get.status_code, 403)

        respuesta_post = cliente.post(f'/admin/instructores/{self.colaborador.id}/restablecer-clave')
        self.assertEqual(respuesta_post.status_code, 403)

    def test_admin_acceso_permitido_listar_instructores(self):
        """Administrador accede correctamente al listado de instructores en /admin/instructores."""
        cliente = self.app.test_client()
        cliente.post('/login', data={
            'correo': self.admin.correo,
            'password': 'AdminPass123!',
        })
        respuesta = cliente.get('/admin/instructores')
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('Administración de Cuentas de Instructores'.encode('utf-8'), respuesta.data)
        self.assertIn(self.admin.nombre.encode('utf-8'), respuesta.data)
        self.assertIn(self.colaborador.nombre.encode('utf-8'), respuesta.data)

    def test_admin_buscar_instructores_filtro(self):
        """El buscador filtra por nombre o correo y maneja resultados vacíos."""
        cliente = self.app.test_client()
        cliente.post('/login', data={
            'correo': self.admin.correo,
            'password': 'AdminPass123!',
        })
        # Búsqueda coincidente
        resp = cliente.get('/admin/instructores?q=Carlos')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('colaborador@sena.edu.co'.encode('utf-8'), resp.data)
        self.assertNotIn('admin@sena.edu.co'.encode('utf-8'), resp.data)

        # Búsqueda sin coincidencias
        resp_vacia = cliente.get('/admin/instructores?q=InexistenteTotal')
        self.assertEqual(resp_vacia.status_code, 200)
        self.assertIn('No se encontraron instructores registrados'.encode('utf-8'), resp_vacia.data)

    # --- 2. Función generadora de clave temporal ---

    def test_generar_clave_temporal_longitudes_y_alfanumerico(self):
        """Verifica que la función auxiliar de generación cree claves alfanuméricas con longitud exacta."""
        clave_8 = generar_clave_temporal()
        self.assertEqual(len(clave_8), 8)
        self.assertTrue(clave_8.isalnum())

        clave_12 = generar_clave_temporal(12)
        self.assertEqual(len(clave_12), 12)
        self.assertTrue(clave_12.isalnum())

    # --- 3. Restablecimiento asistido por el Administrador ---

    def test_restablecer_clave_automatica_asigna_temporal_y_activa_debe_cambiar(self):
        """El administrador genera clave temporal automática: activa debe_cambiar_password e incrementa auth_version."""
        cliente_admin = self.app.test_client()
        cliente_admin.post('/login', data={
            'correo': self.admin.correo,
            'password': 'AdminPass123!',
        })

        version_inicial = self.colaborador.auth_version
        respuesta = cliente_admin.post(
            f'/admin/instructores/{self.colaborador.id}/restablecer-clave',
            follow_redirects=True,
        )
        self.assertEqual(respuesta.status_code, 200)

        # Verificar actualización en base de datos
        db.session.refresh(self.colaborador)
        self.assertTrue(self.colaborador.debe_cambiar_password)
        self.assertEqual(self.colaborador.auth_version, version_inicial + 1)
        self.assertIsNone(self.colaborador.password_reset_token_hash)
        self.assertIsNone(self.colaborador.password_reset_expires_at)

        # Extraer la clave temporal del mensaje flash en HTML
        coincidencia = re.search(r'contrase\u00f1a temporal al instructor Carlos Colaborador: ([a-zA-Z0-9]{8})', respuesta.data.decode('utf-8'))
        self.assertIsNotNone(coincidencia, 'Debe emitir el flash con la clave temporal de 8 caracteres')
        clave_temporal = coincidencia.group(1)

        # La clave anterior ya no funciona
        self.assertFalse(self.colaborador.check_password('ColabPass123!'))
        # La clave temporal sí funciona
        self.assertTrue(self.colaborador.check_password(clave_temporal))

    def test_restablecer_clave_manual_validaciones(self):
        """Valida que una clave manual respete las reglas de mínimo 6 caracteres y máximo 128."""
        cliente_admin = self.app.test_client()
        cliente_admin.post('/login', data={
            'correo': self.admin.correo,
            'password': 'AdminPass123!',
        })

        # Rechazar menor a 6 caracteres
        resp_corta = cliente_admin.post(
            f'/admin/instructores/{self.colaborador.id}/restablecer-clave',
            data={'clave_temporal': '12345'},
            follow_redirects=True,
        )
        self.assertEqual(resp_corta.status_code, 200)
        self.assertIn('La contraseña temporal debe tener al menos 6 caracteres.'.encode('utf-8'), resp_corta.data)
        db.session.refresh(self.colaborador)
        self.assertFalse(self.colaborador.debe_cambiar_password)

        # Rechazar mayor a 128 caracteres
        resp_larga = cliente_admin.post(
            f'/admin/instructores/{self.colaborador.id}/restablecer-clave',
            data={'clave_temporal': 'A' * 129},
            follow_redirects=True,
        )
        self.assertEqual(resp_larga.status_code, 200)
        self.assertIn('La contraseña temporal no puede superar 128 caracteres.'.encode('utf-8'), resp_larga.data)

        # Aceptar clave manual válida >= 6 caracteres
        resp_valida = cliente_admin.post(
            f'/admin/instructores/{self.colaborador.id}/restablecer-clave',
            data={'clave_temporal': 'ClaveTemporal789!'},
            follow_redirects=True,
        )
        self.assertEqual(resp_valida.status_code, 200)
        db.session.refresh(self.colaborador)
        self.assertTrue(self.colaborador.debe_cambiar_password)
        self.assertTrue(self.colaborador.check_password('ClaveTemporal789!'))

    def test_restablecer_clave_inexistente_o_inactivo(self):
        """Restablecimiento falla con 404 si el instructor no existe y con error flash si está inactivo."""
        cliente_admin = self.app.test_client()
        cliente_admin.post('/login', data={
            'correo': self.admin.correo,
            'password': 'AdminPass123!',
        })

        # No existe -> 404
        resp_404 = cliente_admin.post('/admin/instructores/99999/restablecer-clave')
        self.assertEqual(resp_404.status_code, 404)

        # Inactivo -> Error y redirección
        resp_inactivo = cliente_admin.post(
            f'/admin/instructores/{self.inactivo.id}/restablecer-clave',
            follow_redirects=True,
        )
        self.assertEqual(resp_inactivo.status_code, 200)
        self.assertIn('No se puede restablecer la contraseña de una cuenta inactiva.'.encode('utf-8'), resp_inactivo.data)
        db.session.refresh(self.inactivo)
        self.assertFalse(self.inactivo.debe_cambiar_password)

    def test_restablecimiento_asistido_invalida_sesiones_remotas_inmediatamente(self):
        """Al restablecer la contraseña de forma asistida, cualquier sesión previa en otro navegador queda revocada."""
        # Cliente del colaborador con sesión activa en auth_version = 1
        cliente_colaborador = self.app.test_client()
        cliente_colaborador.post('/login', data={
            'correo': self.colaborador.correo,
            'password': 'ColabPass123!',
        })
        # Verifica acceso normal previo
        self.assertEqual(cliente_colaborador.get('/instructor/').status_code, 200)

        g.pop('_login_user', None)

        # Administrador restablece la contraseña desde su propio cliente
        cliente_admin = self.app.test_client()
        cliente_admin.post('/login', data={
            'correo': self.admin.correo,
            'password': 'AdminPass123!',
        })
        cliente_admin.post(
            f'/admin/instructores/{self.colaborador.id}/restablecer-clave',
            data={'clave_temporal': 'NuevaClaveTemp1'},
        )

        g.pop('_login_user', None)

        # La sesión remota previa del colaborador ya no es válida y es expulsada a /login
        resp_expulsado = cliente_colaborador.get('/instructor/')
        self.assertEqual(resp_expulsado.status_code, 302)
        self.assertIn('/login', resp_expulsado.headers['Location'])

    # --- 4. Interceptor @before_request y redirección forzada ---

    def test_login_con_debe_cambiar_password_redirige_a_cambio_obligatorio(self):
        """Al iniciar sesión con debe_cambiar_password == True, redirige directamente a /cambiar-password-obligatorio."""
        self.colaborador.debe_cambiar_password = True
        self.colaborador.set_password('Temporal123!')
        db.session.commit()

        cliente = self.app.test_client()
        resp_login = cliente.post('/login', data={
            'correo': self.colaborador.correo,
            'password': 'Temporal123!',
        })
        self.assertEqual(resp_login.status_code, 302)
        self.assertTrue(resp_login.headers['Location'].endswith('/cambiar-password-obligatorio'))

        # Si ya está autenticado e intenta ir a /login, vuelve a ser redirigido a cambio obligatorio
        resp_ya_autenticado = cliente.get('/login')
        self.assertEqual(resp_ya_autenticado.status_code, 302)
        self.assertTrue(resp_ya_autenticado.headers['Location'].endswith('/cambiar-password-obligatorio'))

    def test_before_request_intercepta_rutas_protegidas(self):
        """Usuario con debe_cambiar_password == True no puede navegar a otros módulos del panel."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        # Intento de ir al dashboard
        resp_dashboard = cliente.get('/instructor/')
        self.assertEqual(resp_dashboard.status_code, 302)
        self.assertTrue(resp_dashboard.headers['Location'].endswith('/cambiar-password-obligatorio'))

        # Intento de ir a fichas
        resp_fichas = cliente.get('/instructor/fichas')
        self.assertEqual(resp_fichas.status_code, 302)
        self.assertTrue(resp_fichas.headers['Location'].endswith('/cambiar-password-obligatorio'))

        # Intento de ir a admin
        resp_admin = cliente.get('/admin/instructores')
        self.assertEqual(resp_admin.status_code, 302)
        self.assertTrue(resp_admin.headers['Location'].endswith('/cambiar-password-obligatorio'))

    def test_before_request_permite_rutas_en_lista_blanca(self):
        """Usuario con debe_cambiar_password == True sí puede acceder a la vista de cambio forzado y a logout."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        # Acceso permitido a cambio obligatorio (GET)
        resp_cambio = cliente.get('/cambiar-password-obligatorio')
        self.assertEqual(resp_cambio.status_code, 200)
        self.assertIn('Cambio obligatorio de contraseña'.encode('utf-8'), resp_cambio.data)

        # Acceso permitido a logout (POST)
        resp_logout = cliente.post('/logout')
        self.assertEqual(resp_logout.status_code, 302)
        self.assertIn('/login', resp_logout.headers['Location'])

    def test_before_request_soporta_htmx_hx_redirect(self):
        """Peticiones HTMX interceptadas reciben HTTP 200 con cabecera HX-Redirect."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        resp_htmx = cliente.get('/instructor/', headers={'HX-Request': 'true'})
        self.assertEqual(resp_htmx.status_code, 200)
        self.assertIn('HX-Redirect', resp_htmx.headers)
        self.assertTrue(resp_htmx.headers['HX-Redirect'].endswith('/cambiar-password-obligatorio'))

    # --- 5. Flujo de cambio forzado (/cambiar-password-obligatorio) ---

    def test_cambiar_password_obligatorio_acceso_restringido(self):
        """Solo accesible a usuarios autenticados con debe_cambiar_password == True."""
        cliente_anonimo = self.app.test_client()
        resp_anonimo = cliente_anonimo.get('/cambiar-password-obligatorio')
        self.assertEqual(resp_anonimo.status_code, 302)
        self.assertIn('/login', resp_anonimo.headers['Location'])

        # Usuario autenticado que NO debe cambiar contraseña es enviado a su dashboard
        cliente_normal = self.app.test_client()
        cliente_normal.post('/login', data={
            'correo': self.colaborador.correo,
            'password': 'ColabPass123!',
        })
        resp_normal = cliente_normal.get('/cambiar-password-obligatorio')
        self.assertEqual(resp_normal.status_code, 302)
        self.assertIn('/instructor', resp_normal.headers['Location'])

    def test_cambiar_password_obligatorio_validaciones_formulario(self):
        """Valida que la nueva contraseña tenga mínimo 6 caracteres, máximo 128 y coincida con la confirmación."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        # Menor a 6 caracteres
        resp_corta = cliente.post('/cambiar-password-obligatorio', data={
            'nueva_password': '12345',
            'confirmacion': '12345',
        })
        self.assertEqual(resp_corta.status_code, 200)
        self.assertIn('La nueva contraseña debe tener al menos 6 caracteres.'.encode('utf-8'), resp_corta.data)

        # Mayor a 128 caracteres
        resp_larga = cliente.post('/cambiar-password-obligatorio', data={
            'nueva_password': 'A' * 129,
            'confirmacion': 'A' * 129,
        })
        self.assertEqual(resp_larga.status_code, 200)
        self.assertIn('La contraseña no puede superar 128 caracteres.'.encode('utf-8'), resp_larga.data)

        # Discrepancia entre contraseñas
        resp_distinta = cliente.post('/cambiar-password-obligatorio', data={
            'nueva_password': 'ClaveDefinitiva1!',
            'confirmacion': 'ClaveDefinitiva2!',
        })
        self.assertEqual(resp_distinta.status_code, 200)
        self.assertIn('Las contraseñas no coinciden.'.encode('utf-8'), resp_distinta.data)

    def test_cambiar_password_obligatorio_exitoso_y_renovacion_local(self):
        """Flujo exitoso: actualiza clave, apaga bandera, renueva cookie local e invalida sesiones remotas."""
        self.colaborador.debe_cambiar_password = True
        self.colaborador.auth_version = 5
        db.session.commit()

        # Dispositivo A (local)
        cliente_local = self.app.test_client()
        with cliente_local.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:5'
            sesion['_fresh'] = True

        # Dispositivo B (remoto previo)
        cliente_remoto = self.app.test_client()
        with cliente_remoto.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:5'
            sesion['_fresh'] = True

        # El dispositivo local completa el cambio obligatorio
        resp_exito = cliente_local.post('/cambiar-password-obligatorio', data={
            'nueva_password': 'MiNuevaClaveSegura2026!',
            'confirmacion': 'MiNuevaClaveSegura2026!',
        })
        self.assertEqual(resp_exito.status_code, 302)
        self.assertTrue(resp_exito.headers['Location'].endswith('/instructor/'))

        # Verificar base de datos
        db.session.refresh(self.colaborador)
        self.assertFalse(self.colaborador.debe_cambiar_password)
        self.assertEqual(self.colaborador.auth_version, 6)
        self.assertTrue(self.colaborador.check_password('MiNuevaClaveSegura2026!'))

        # El dispositivo local continúa navegando sin ser expulsado
        g.pop('_login_user', None)
        resp_local_nav = cliente_local.get('/instructor/')
        self.assertEqual(resp_local_nav.status_code, 200)

        # El dispositivo remoto B queda inmediatamente revocado (302 a login)
        g.pop('_login_user', None)
        resp_remoto_nav = cliente_remoto.get('/instructor/')
        self.assertEqual(resp_remoto_nav.status_code, 302)
        self.assertIn('/login', resp_remoto_nav.headers['Location'])

    # --- 6. Interfaz y navegación base.html ---

    def test_navbar_enlace_administracion_solo_visible_para_admin(self):
        """El enlace de Administración en la barra de navegación solo se muestra al instructor administrador."""
        cliente_colab = self.app.test_client()
        cliente_colab.post('/login', data={
            'correo': self.colaborador.correo,
            'password': 'ColabPass123!',
        })
        resp_colab = cliente_colab.get('/instructor/')
        self.assertEqual(resp_colab.status_code, 200)
        self.assertNotIn('/admin/instructores'.encode('utf-8'), resp_colab.data)

        g.pop('_login_user', None)

        cliente_admin = self.app.test_client()
        cliente_admin.post('/login', data={
            'correo': self.admin.correo,
            'password': 'AdminPass123!',
        })
        g.pop('_login_user', None)
        resp_admin = cliente_admin.get('/instructor/')
        self.assertEqual(resp_admin.status_code, 200)
        self.assertIn('/admin/instructores'.encode('utf-8'), resp_admin.data)
        self.assertIn('Administración'.encode('utf-8'), resp_admin.data)

    def test_plantilla_cambiar_password_obligatorio_sin_enlaces_de_fuga_y_con_logout(self):
        """Verifica que la plantilla de cambio forzado no contenga enlaces al panel y provea opción de logout."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        resp = cliente.get('/cambiar-password-obligatorio')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # No contiene enlaces de navegación general
        self.assertNotIn('href="/instructor/"', html)
        self.assertNotIn('href="/instructor/fichas"', html)
        self.assertNotIn('href="/instructor"', html)

        # Contiene formulario y botón para cerrar sesión
        self.assertIn('action="/logout"', html)
        self.assertIn('Cerrar sesión', html)
