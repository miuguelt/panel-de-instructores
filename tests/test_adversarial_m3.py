"""Suite de pruebas adversariales y de estrés para Milestone M3.

Desafíos empíricos sobre:
1. Escalada de privilegios (/admin/* desde anónimo o colaborador).
2. Evasión del cambio forzado de contraseña (navegación directa, POST, API, HTMX).
3. Fronteras de validación de contraseña (5, 6, 128, 129 caracteres, discrepancia).
4. Invalidación multidispositivo estricta y preservación de sesión local.
"""

import unittest
from datetime import timedelta
from flask import g
from app import create_app, db
from app.models.instructor import Instructor, load_user
from app.models.ficha import Ficha


class AdversarialM3TestCase(unittest.TestCase):
    """Batería adversarial exhaustiva para verificación empírica de M3."""

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

        # Administrador activo
        self.admin = Instructor(
            nombre='Super Admin',
            correo='admin.principal@sena.edu.co',
            rol='admin',
            activo=True,
            auth_version=1,
            debe_cambiar_password=False,
        )
        self.admin.set_password('AdminMaster123!')

        # Colaborador estándar
        self.colaborador = Instructor(
            nombre='Instructor Pedro',
            correo='pedro.colaborador@sena.edu.co',
            rol='colaborador',
            activo=True,
            auth_version=1,
            debe_cambiar_password=False,
        )
        self.colaborador.set_password('PedroPass123!')

        # Víctima / Objetivo de restablecimiento
        self.victima = Instructor(
            nombre='Instructora Maria',
            correo='maria.victima@sena.edu.co',
            rol='colaborador',
            activo=True,
            auth_version=1,
            debe_cambiar_password=False,
        )
        self.victima.set_password('MariaPass123!')

        # Instructor inactivo
        self.inactivo = Instructor(
            nombre='Instructor Inactivo',
            correo='inactivo@sena.edu.co',
            rol='colaborador',
            activo=False,
            auth_version=1,
            debe_cambiar_password=False,
        )
        self.inactivo.set_password('InactivoPass123!')

        # Admin inactivo (caso de prueba de seguridad)
        self.admin_inactivo = Instructor(
            nombre='Admin Suspendido',
            correo='admin.suspendido@sena.edu.co',
            rol='admin',
            activo=False,
            auth_version=1,
            debe_cambiar_password=False,
        )
        self.admin_inactivo.set_password('AdminSusp123!')

        db.session.add_all([
            self.admin, self.colaborador, self.victima, self.inactivo, self.admin_inactivo
        ])
        db.session.commit()

        # Ficha asociada para pruebas de rutas protegidas
        self.ficha = Ficha(
            codigo='2694500',
            nombre_programa='ADSO',
            instructor_id=self.colaborador.id,
        )
        db.session.add(self.ficha)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    # =========================================================================
    # DESAFÍO 1: ESCALADA DE PRIVILEGIOS Y CONTROL DE ACCESO (/admin/*)
    # =========================================================================

    def test_adv_anonimo_get_admin_instructores_redirige_a_login(self):
        """Usuario anónimo intentando GET /admin/instructores debe ser redirigido a /login."""
        cliente = self.app.test_client()
        resp = cliente.get('/admin/instructores')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])
        self.assertIn('next=', resp.headers['Location'])

    def test_adv_anonimo_post_admin_restablecer_clave_redirige_a_login(self):
        """Usuario anónimo intentando POST /admin/instructores/<id>/restablecer-clave debe ser redirigido a /login."""
        cliente = self.app.test_client()
        resp = cliente.post(
            f'/admin/instructores/{self.victima.id}/restablecer-clave',
            data={'clave_temporal': 'HackerClave123!'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])
        # Asegurar que el estado en DB NO fue alterado
        db.session.refresh(self.victima)
        self.assertEqual(self.victima.auth_version, 1)
        self.assertFalse(self.victima.debe_cambiar_password)
        self.assertTrue(self.victima.check_password('MariaPass123!'))

    def test_adv_colaborador_get_admin_instructores_aborta_403(self):
        """Instructor con rol 'colaborador' no puede consultar el panel administrativo (403 Forbidden)."""
        cliente = self.app.test_client()
        cliente.post('/login', data={
            'correo': self.colaborador.correo,
            'password': 'PedroPass123!',
        })
        resp = cliente.get('/admin/instructores')
        self.assertEqual(resp.status_code, 403)

    def test_adv_colaborador_post_admin_restablecer_tercero_aborta_403(self):
        """Instructor colaborador no puede forzar el restablecimiento de clave de otro usuario (403 Forbidden)."""
        cliente = self.app.test_client()
        cliente.post('/login', data={
            'correo': self.colaborador.correo,
            'password': 'PedroPass123!',
        })
        resp = cliente.post(
            f'/admin/instructores/{self.victima.id}/restablecer-clave',
            data={'clave_temporal': 'ClaveSecuestrada1!'},
        )
        self.assertEqual(resp.status_code, 403)
        # La víctima no sufrió modificaciones
        db.session.refresh(self.victima)
        self.assertEqual(self.victima.auth_version, 1)
        self.assertFalse(self.victima.debe_cambiar_password)
        self.assertTrue(self.victima.check_password('MariaPass123!'))

    def test_adv_colaborador_post_admin_restablecer_auto_aborta_403(self):
        """Instructor colaborador no puede usar el endpoint de admin para auto-asignarse clave o brincar flujo (403 Forbidden)."""
        cliente = self.app.test_client()
        cliente.post('/login', data={
            'correo': self.colaborador.correo,
            'password': 'PedroPass123!',
        })
        resp = cliente.post(
            f'/admin/instructores/{self.colaborador.id}/restablecer-clave',
            data={'clave_temporal': 'ClaveAuto123!'},
        )
        self.assertEqual(resp.status_code, 403)
        db.session.refresh(self.colaborador)
        self.assertEqual(self.colaborador.auth_version, 1)
        self.assertFalse(self.colaborador.debe_cambiar_password)

    def test_adv_colaborador_htmx_probe_admin_aborta_403(self):
        """Inyección de cabecera HX-Request por parte de colaborador sigue devolviendo 403 Forbidden."""
        cliente = self.app.test_client()
        cliente.post('/login', data={
            'correo': self.colaborador.correo,
            'password': 'PedroPass123!',
        })
        resp = cliente.get('/admin/instructores', headers={'HX-Request': 'true'})
        self.assertEqual(resp.status_code, 403)

    def test_adv_roles_no_autorizados_abortan_403(self):
        """Cualquier rol distinto a 'admin' estricto ('coordinador', 'aprendiz', 'ADMIN', '') es rechazado."""
        roles_adversarios = ['coordinador', 'aprendiz', 'ADMIN', '', 'none', 'root']
        for r in roles_adversarios:
            usuario = Instructor(
                nombre=f'Usuario Rol {r}',
                correo=f'usuario_{r}@sena.edu.co',
                rol=r,
                activo=True,
                auth_version=1,
            )
            usuario.set_password('TestPass123!')
            db.session.add(usuario)
            db.session.commit()

            cliente = self.app.test_client()
            with cliente.session_transaction() as sesion:
                sesion['_user_id'] = f'{usuario.id}:1'
                sesion['_fresh'] = True

            resp = cliente.get('/admin/instructores')
            self.assertEqual(resp.status_code, 403, f'El rol {r} debió recibir 403')

    def test_adv_admin_suspendido_rechazado_por_load_user(self):
        """Un administrador inactivo no puede autenticarse ni mantener sesión en /admin/instructores."""
        cliente = self.app.test_client()
        # Intento con sesión existente
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.admin_inactivo.id}:1'
            sesion['_fresh'] = True

        resp = cliente.get('/admin/instructores')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    # =========================================================================
    # DESAFÍO 2: EVASIÓN DEL CAMBIO FORZADO DE CONTRASEÑA
    # =========================================================================

    def test_adv_evasion_directa_get_rutas_protegidas(self):
        """Instructor con debe_cambiar_password == True es interceptado en todas las rutas funcionales."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        rutas_a_probar = [
            '/instructor/',
            '/instructor/fichas',
            f'/api/fichas/{self.ficha.id}/resumen',
            '/admin/instructores',
            '/ruta-que-no-existe-en-el-sistema',
        ]
        for ruta in rutas_a_probar:
            resp = cliente.get(ruta)
            self.assertEqual(resp.status_code, 302, f'Ruta {ruta} no fue interceptada con 302')
            self.assertTrue(
                resp.headers['Location'].endswith('/cambiar-password-obligatorio'),
                f'Ruta {ruta} redirigió a {resp.headers["Location"]} en lugar de cambio obligatorio',
            )

    def test_adv_evasion_post_mutacion_bloqueada_por_before_request(self):
        """Petición POST a endpoints de mutación es interceptada antes de que la función de vista se ejecute."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        # Intento de POST hacia cargas
        resp_cargas = cliente.post('/cargas', json={'test': 'data'})
        self.assertEqual(resp_cargas.status_code, 302)
        self.assertTrue(resp_cargas.headers['Location'].endswith('/cambiar-password-obligatorio'))

    def test_adv_evasion_htmx_recibe_hx_redirect_y_cero_fuga_de_datos(self):
        """Solicitudes con cabecera HX-Request reciben 200 con HX-Redirect y cuerpo vacío sin datos protegidos."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        # GET con HTMX
        resp_get = cliente.get('/instructor/', headers={'HX-Request': 'true'})
        self.assertEqual(resp_get.status_code, 200)
        self.assertIn('HX-Redirect', resp_get.headers)
        self.assertTrue(resp_get.headers['HX-Redirect'].endswith('/cambiar-password-obligatorio'))
        self.assertEqual(resp_get.data.decode('utf-8').strip(), '', 'El cuerpo no debe contener HTML del panel')

        # POST con HTMX
        resp_post = cliente.post('/cargas', headers={'HX-Request': 'true'}, json={'data': 123})
        self.assertEqual(resp_post.status_code, 200)
        self.assertIn('HX-Redirect', resp_post.headers)
        self.assertTrue(resp_post.headers['HX-Redirect'].endswith('/cambiar-password-obligatorio'))
        self.assertEqual(resp_post.data.decode('utf-8').strip(), '')

    def test_adv_lista_blanca_permite_logout_y_recursos_estaticos(self):
        """Las únicas rutas accesibles son cambio obligatorio, logout y recursos estáticos."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        # 1. GET a la vista obligatoria es 200
        resp_view = cliente.get('/cambiar-password-obligatorio')
        self.assertEqual(resp_view.status_code, 200)

        # 2. POST a logout es 302 hacia /login y limpia la sesión
        resp_logout = cliente.post('/logout')
        self.assertEqual(resp_logout.status_code, 302)
        self.assertIn('/login', resp_logout.headers['Location'])

    # =========================================================================
    # DESAFÍO 3: FRONTERAS DE VALIDACIÓN DE CONTRASEÑA EN CAMBIO FORZADO
    # =========================================================================

    def test_adv_frontera_5_caracteres_rechazada(self):
        """5 caracteres debe ser rechazado taxativamente en el cambio obligatorio."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        resp = cliente.post('/cambiar-password-obligatorio', data={
            'nueva_password': '12345',
            'confirmacion': '12345',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('al menos 6 caracteres'.encode('utf-8'), resp.data)
        # DB preservada
        db.session.refresh(self.colaborador)
        self.assertTrue(self.colaborador.debe_cambiar_password)
        self.assertEqual(self.colaborador.auth_version, 1)

    def test_adv_frontera_6_caracteres_aceptada(self):
        """6 caracteres exactos debe ser aceptado con éxito."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        resp = cliente.post('/cambiar-password-obligatorio', data={
            'nueva_password': '123456',
            'confirmacion': '123456',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers['Location'].endswith('/instructor/'))
        # DB actualizada
        db.session.refresh(self.colaborador)
        self.assertFalse(self.colaborador.debe_cambiar_password)
        self.assertEqual(self.colaborador.auth_version, 2)
        self.assertTrue(self.colaborador.check_password('123456'))

    def test_adv_frontera_128_caracteres_aceptada(self):
        """128 caracteres exactos debe ser aceptado con éxito."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        clave_128 = 'K' * 128
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        resp = cliente.post('/cambiar-password-obligatorio', data={
            'nueva_password': clave_128,
            'confirmacion': clave_128,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers['Location'].endswith('/instructor/'))
        db.session.refresh(self.colaborador)
        self.assertFalse(self.colaborador.debe_cambiar_password)
        self.assertEqual(self.colaborador.auth_version, 2)
        self.assertTrue(self.colaborador.check_password(clave_128))

    def test_adv_frontera_129_caracteres_rechazada(self):
        """129 caracteres debe ser rechazado taxativamente en el cambio obligatorio."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        clave_129 = 'M' * 129
        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        resp = cliente.post('/cambiar-password-obligatorio', data={
            'nueva_password': clave_129,
            'confirmacion': clave_129,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('no puede superar 128 caracteres'.encode('utf-8'), resp.data)
        db.session.refresh(self.colaborador)
        self.assertTrue(self.colaborador.debe_cambiar_password)
        self.assertEqual(self.colaborador.auth_version, 1)

    def test_adv_frontera_discrepancia_confirmacion_rechazada(self):
        """Contraseña y confirmación con diferencias mínimas (1 carácter) deben ser rechazadas."""
        self.colaborador.debe_cambiar_password = True
        db.session.commit()

        cliente = self.app.test_client()
        with cliente.session_transaction() as sesion:
            sesion['_user_id'] = f'{self.colaborador.id}:1'
            sesion['_fresh'] = True

        resp = cliente.post('/cambiar-password-obligatorio', data={
            'nueva_password': 'ClaveSuperSegura1',
            'confirmacion': 'ClaveSuperSegura2',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Las contraseñas no coinciden'.encode('utf-8'), resp.data)
        db.session.refresh(self.colaborador)
        self.assertTrue(self.colaborador.debe_cambiar_password)

    def test_adv_frontera_admin_restablecer_manual_5_y_129_rechazados(self):
        """En el panel de administración, claves manuales de 5 y 129 chars son rechazadas, 6 y 128 aceptadas."""
        cliente_admin = self.app.test_client()
        cliente_admin.post('/login', data={
            'correo': self.admin.correo,
            'password': 'AdminMaster123!',
        })

        # 5 chars -> rechazado
        resp_5 = cliente_admin.post(
            f'/admin/instructores/{self.victima.id}/restablecer-clave',
            data={'clave_temporal': '12345'},
            follow_redirects=True,
        )
        self.assertIn('al menos 6 caracteres'.encode('utf-8'), resp_5.data)
        db.session.refresh(self.victima)
        self.assertFalse(self.victima.debe_cambiar_password)

        # 129 chars -> rechazado
        resp_129 = cliente_admin.post(
            f'/admin/instructores/{self.victima.id}/restablecer-clave',
            data={'clave_temporal': 'Z' * 129},
            follow_redirects=True,
        )
        self.assertIn('no puede superar 128 caracteres'.encode('utf-8'), resp_129.data)
        db.session.refresh(self.victima)
        self.assertFalse(self.victima.debe_cambiar_password)

        # 6 chars -> aceptado
        resp_6 = cliente_admin.post(
            f'/admin/instructores/{self.victima.id}/restablecer-clave',
            data={'clave_temporal': 'Temp06'},
            follow_redirects=True,
        )
        self.assertEqual(resp_6.status_code, 200)
        db.session.refresh(self.victima)
        self.assertTrue(self.victima.debe_cambiar_password)
        self.assertTrue(self.victima.check_password('Temp06'))

        # 128 chars -> aceptado
        clave_128 = 'W' * 128
        resp_128 = cliente_admin.post(
            f'/admin/instructores/{self.victima.id}/restablecer-clave',
            data={'clave_temporal': clave_128},
            follow_redirects=True,
        )
        self.assertEqual(resp_128.status_code, 200)
        db.session.refresh(self.victima)
        self.assertTrue(self.victima.check_password(clave_128))

    # =========================================================================
    # DESAFÍO 4: INVALIDACIÓN MULTIDISPOSITIVO ESTRICTA Y PRESERVACIÓN LOCAL
    # =========================================================================

    def test_adv_multidispositivo_admin_reset_expulsa_todos_los_navegadores(self):
        """Cuando el administrador restablece la clave, 3 sesiones abiertas en distintos dispositivos quedan invalidadas."""
        # Sesión Navegador 1 (Laptop)
        nav1 = self.app.test_client()
        with nav1.session_transaction() as s:
            s['_user_id'] = f'{self.victima.id}:1'
            s['_fresh'] = True

        # Sesión Navegador 2 (Celular)
        nav2 = self.app.test_client()
        with nav2.session_transaction() as s:
            s['_user_id'] = f'{self.victima.id}:1'
            s['_fresh'] = True

        # Sesión Navegador 3 (Tablet)
        nav3 = self.app.test_client()
        with nav3.session_transaction() as s:
            s['_user_id'] = f'{self.victima.id}:1'
            s['_fresh'] = True

        # Verificamos acceso inicial válido en los 3
        self.assertEqual(nav1.get('/instructor/').status_code, 200)
        g.pop('_login_user', None)
        self.assertEqual(nav2.get('/instructor/').status_code, 200)
        g.pop('_login_user', None)
        self.assertEqual(nav3.get('/instructor/').status_code, 200)
        g.pop('_login_user', None)

        # Administrador ejecuta restablecimiento asistido
        admin_client = self.app.test_client()
        admin_client.post('/login', data={
            'correo': self.admin.correo,
            'password': 'AdminMaster123!',
        })
        admin_client.post(
            f'/admin/instructores/{self.victima.id}/restablecer-clave',
            data={'clave_temporal': 'ClaveNuevaTemp12'},
        )

        g.pop('_login_user', None)

        # Los tres navegadores deben recibir 302 hacia /login al intentar navegar
        for i, nav in enumerate([nav1, nav2, nav3], 1):
            g.pop('_login_user', None)
            resp = nav.get('/instructor/')
            self.assertEqual(resp.status_code, 302, f'Navegador {i} no fue expulsado con 302')
            self.assertIn('/login', resp.headers['Location'])

    def test_adv_multidispositivo_cambio_forzado_preserva_cliente_y_revoca_otros(self):
        """Al completar cambio forzado, la sesión activa se actualiza y permanece, mientras las otras son expulsadas."""
        self.victima.auth_version = 2
        self.victima.debe_cambiar_password = True
        self.victima.set_password('TemporalValida1!')
        db.session.commit()

        # Dispositivo A (hace el cambio forzado)
        dev_a = self.app.test_client()
        with dev_a.session_transaction() as s:
            s['_user_id'] = f'{self.victima.id}:2'
            s['_fresh'] = True

        # Dispositivo B (otra pestaña/dispositivo que también ingresó con la temporal versión 2)
        dev_b = self.app.test_client()
        with dev_b.session_transaction() as s:
            s['_user_id'] = f'{self.victima.id}:2'
            s['_fresh'] = True

        # Ambos son redirigidos si intentan ir al dashboard antes del cambio
        self.assertEqual(dev_a.get('/instructor/').status_code, 302)
        g.pop('_login_user', None)
        self.assertEqual(dev_b.get('/instructor/').status_code, 302)
        g.pop('_login_user', None)

        # Dispositivo A realiza el cambio exitosamente
        resp_cambio = dev_a.post('/cambiar-password-obligatorio', data={
            'nueva_password': 'ClaveDefinitiva2026!',
            'confirmacion': 'ClaveDefinitiva2026!',
        })
        self.assertEqual(resp_cambio.status_code, 302)
        self.assertTrue(resp_cambio.headers['Location'].endswith('/instructor/'))

        # Verificación en BD
        db.session.refresh(self.victima)
        self.assertEqual(self.victima.auth_version, 3)
        self.assertFalse(self.victima.debe_cambiar_password)

        # Dispositivo A puede navegar libremente (200 OK)
        g.pop('_login_user', None)
        resp_dev_a = dev_a.get('/instructor/')
        self.assertEqual(resp_dev_a.status_code, 200, 'Dispositivo A debió mantener su sesión activa')

        # Dispositivo B (que se quedó con versión 2) es expulsado inmediatamente a /login
        g.pop('_login_user', None)
        resp_dev_b = dev_b.get('/instructor/')
        self.assertEqual(resp_dev_b.status_code, 302, 'Dispositivo B debió ser revocado')
        self.assertIn('/login', resp_dev_b.headers['Location'])

        # Dispositivo B tampoco puede usar /cambiar-password-obligatorio porque ya no está autenticado
        g.pop('_login_user', None)
        resp_dev_b_cambio = dev_b.get('/cambiar-password-obligatorio')
        self.assertEqual(resp_dev_b_cambio.status_code, 302)
        self.assertIn('/login', resp_dev_b_cambio.headers['Location'])

    def test_adv_sesion_legacy_sin_dos_puntos_invalida_al_subir_version(self):
        """Sesiones antiguas sin ':' quedan invalidadas en cuanto auth_version > 1."""
        # Versión 1 en DB: carga usuario si auth_version == 1
        inst_v1 = load_user(str(self.colaborador.id))
        self.assertIsNotNone(inst_v1)

        # Subimos versión a 2
        self.colaborador.auth_version = 2
        db.session.commit()

        # Con auth_version > 1, la sesión legacy sin versión es rechazada taxativamente
        inst_revocado = load_user(str(self.colaborador.id))
        self.assertIsNone(inst_revocado)


if __name__ == '__main__':
    unittest.main()
