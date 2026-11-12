"""Pruebas automatizadas para verificar el sistema de diseño, profundidad, transparencias,

botones e iconografía vectorial Lucide en el panel de instructores.
"""

import os
import unittest
from datetime import date
from types import SimpleNamespace
from flask import render_template
from app import create_app


class DesignSystemAndDepthTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
        })
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Ruta de styles.css
        self.css_path = os.path.join(self.app.root_path, 'static', 'css', 'styles.css')
        with open(self.css_path, 'r', encoding='utf-8') as f:
            self.css_content = f.read()

    def tearDown(self):
        self.app_context.pop()

    def test_css_contains_depth_tokens(self):
        """Verifica que los tokens de elevación, desenfoque y luz interna estén presentes."""
        self.assertIn('--blur-glass:', self.css_content)
        self.assertIn('--blur-glass-sm:', self.css_content)
        self.assertIn('--shadow-sm:', self.css_content)
        self.assertIn('--shadow:', self.css_content)
        self.assertIn('--shadow-lg:', self.css_content)
        self.assertIn('--shadow-xl:', self.css_content)
        self.assertIn('--btn-inner-highlight:', self.css_content)
        self.assertIn('--btn-inner-shadow-active:', self.css_content)

    def test_css_button_variants_and_microinteractions(self):
        """Verifica la definición de microinteracciones y variantes de botones."""
        self.assertIn('.btn {', self.css_content)
        self.assertIn('.btn:hover {', self.css_content)
        self.assertIn('.btn:active {', self.css_content)
        self.assertIn('.btn-primary {', self.css_content)
        self.assertIn('.btn-secondary {', self.css_content)
        self.assertIn('.btn-outline {', self.css_content)
        self.assertIn('.btn-warning {', self.css_content)
        self.assertIn('.btn-danger {', self.css_content)
        self.assertIn('.btn-success {', self.css_content)

        # Microinteracciones físicas de elevación y compresión
        self.assertIn('translateY(-2px)', self.css_content)
        self.assertIn('translateY(1px)', self.css_content)

    def test_css_glassmorphism_surfaces(self):
        """Verifica la aplicación de backdrop-filter y bordes translúcidos en tarjetas y barras."""
        self.assertIn('.card {', self.css_content)
        self.assertIn('backdrop-filter: var(--blur-glass);', self.css_content)
        self.assertIn('.navbar {', self.css_content)
        self.assertIn('.ficha-toolbar {', self.css_content)

    def test_css_prefers_reduced_motion(self):
        """Verifica que la regla prefers-reduced-motion neutralice los desplazamientos."""
        self.assertIn('@media (prefers-reduced-motion: reduce)', self.css_content)
        self.assertIn('transform: none !important', self.css_content)

    def test_css_surface_tokens_are_defined_for_every_theme(self):
        """Verifica las capas de superficie, borde y control del sistema visual."""
        for token in (
            '--surface-glass:',
            '--surface-glass-strong:',
            '--surface-data:',
            '--surface-control:',
            '--border-glass:',
            '--border-control:',
            '--radius-md:',
            '--radius-control:',
            '--control-h-sm:',
            '--bg-base:',
        ):
            self.assertIn(token, self.css_content, f'Falta el token {token} en styles.css')

        # Los tres temas calibran su propia superficie translúcida.
        self.assertGreaterEqual(
            self.css_content.count('--surface-glass:'),
            3,
            'Los temas elegant, sena y ocean deben declarar --surface-glass',
        )
        self.assertGreaterEqual(self.css_content.count('--surface-glass-strong:'), 3)
        self.assertGreaterEqual(self.css_content.count('--surface-data:'), 3)

    def test_css_glass_fallbacks_and_accessibility_media_queries(self):
        """Verifica los fallbacks y preferencias de accesibilidad del vidrio."""
        self.assertIn('@supports not', self.css_content)
        self.assertIn('@media (prefers-reduced-transparency: reduce)', self.css_content)
        self.assertIn('@media (prefers-contrast: more)', self.css_content)
        self.assertIn('@media (forced-colors: active)', self.css_content)
        # En colores forzados los controles recuperan borde y foco del sistema.
        self.assertIn('outline: 3px solid Highlight', self.css_content)

    def test_css_canonical_button_states_and_outline_variants(self):
        """Verifica los estados y variantes de botón del sistema de componentes."""
        for selector in (
            '.btn:disabled',
            '.btn[aria-disabled="true"]',
            '.btn[aria-busy="true"]',
            '.btn-icon',
            '.btn-ghost',
            '.btn-outline-danger',
            '.btn-outline-success',
        ):
            self.assertIn(selector, self.css_content, f'Falta el selector {selector}')

        # La pista del spinner en botones rellenos usa el token de contraste.
        self.assertIn('--button-on-accent', self.css_content)

    def test_css_canonical_table_filter_and_upload_components(self):
        """Verifica los componentes canónicos que consumen table-filters.js y uploads.js."""
        for selector in (
            '.table-toolbar',
            '.table-filters-container',
            '.table-filter-search',
            '.table-filter-select',
            '.table-filter-result',
            '.table-filter-empty',
            '.table-filter-toggle.is-active',
            '.upload-progress',
            '.upload-progress-text',
            '.upload-progress-bar',
            '.upload-progress-fill',
            '.upload-error',
        ):
            self.assertIn(selector, self.css_content, f'Falta el componente {selector}')

    @staticmethod
    def _desbalance_de_llaves(css):
        """Devuelve (línea, motivo) del primer desbalance de llaves, o None.

        Ignora comentarios y cadenas para no contar llaves que no abren bloques.
        """
        profundidad = 0
        linea = 1
        i = 0
        total = len(css)
        while i < total:
            caracter = css[i]
            if caracter == '\n':
                linea += 1
            elif css.startswith('/*', i):
                fin = css.find('*/', i + 2)
                fin = total if fin == -1 else fin + 2
                linea += css.count('\n', i, fin)
                i = fin
                continue
            elif caracter in ('"', "'"):
                i += 1
                while i < total and css[i] != caracter:
                    if css[i] == '\\':
                        i += 1
                    elif css[i] == '\n':
                        linea += 1
                    i += 1
            elif caracter == '{':
                profundidad += 1
            elif caracter == '}':
                profundidad -= 1
                if profundidad < 0:
                    return linea, 'llave de cierre sin bloque abierto'
            i += 1
        if profundidad:
            return linea, f'quedan {profundidad} bloques sin cerrar'
        return None

    def test_detector_de_llaves_reconoce_css_valido_e_invalido(self):
        """El detector distingue bloques bien cerrados, sobrantes y faltantes."""
        valido = '/* } */ .a { content: "}"; } @media (x) { .b { c: d; } }'
        self.assertIsNone(self._desbalance_de_llaves(valido))
        self.assertEqual(
            self._desbalance_de_llaves('.a { b: c; }\n}\n.d { e: f; }'),
            (2, 'llave de cierre sin bloque abierto'),
        )
        self.assertEqual(
            self._desbalance_de_llaves('.a { b: c;'),
            (1, 'quedan 1 bloques sin cerrar'),
        )

    def test_css_llaves_balanceadas(self):
        """Una llave suelta anula la regla siguiente: ninguna hoja de estilos puede tenerla."""
        carpeta = os.path.join(self.app.root_path, 'static', 'css')
        hojas = sorted(nombre for nombre in os.listdir(carpeta) if nombre.endswith('.css'))
        self.assertIn('styles.css', hojas)
        for nombre in hojas:
            with open(os.path.join(carpeta, nombre), 'r', encoding='utf-8') as archivo:
                desbalance = self._desbalance_de_llaves(archivo.read())
            self.assertIsNone(desbalance, f'{nombre}: {desbalance}')

    def test_nav_user_es_fila_flexible(self):
        """El bloque de usuario del menú se dispone en una fila alineada a la derecha."""
        import re

        reglas = re.findall(r'(?m)^\.nav-user\s*\{([^}]*)\}', self.css_content)
        self.assertEqual(len(reglas), 1, 'Debe existir una sola regla base .nav-user')
        declaraciones = {
            parte.split(':', 1)[0].strip(): parte.split(':', 1)[1].strip()
            for parte in reglas[0].split(';') if ':' in parte
        }
        self.assertEqual(declaraciones.get('display'), 'flex')
        self.assertEqual(declaraciones.get('align-items'), 'center')
        self.assertEqual(declaraciones.get('margin-left'), 'auto')
        self.assertEqual(declaraciones.get('flex'), '0 0 auto')
        # La regla anterior debe cerrar una sola vez; una llave extra invalida .nav-user.
        self.assertIsNone(
            re.search(r'\}\s*\}\s*\.nav-user\s*\{', self.css_content),
            'Hay una llave suelta antes de .nav-user',
        )

    def test_contador_compacto_limita_cifras_altas(self):
        """El contador del menú muestra 99+ por encima de 99 y la cifra exacta hasta 99."""
        contador = self.app.jinja_env.filters['contador_compacto']
        self.assertEqual(contador(5), '5')
        self.assertEqual(contador(99), '99')
        self.assertEqual(contador(100), '99+')
        self.assertEqual(contador(217), '99+')
        self.assertEqual(contador(12, tope=9), '9+')
        self.assertEqual(contador(None), '0')
        self.assertEqual(contador('no numérico'), '0')
        self.assertEqual(contador(-3), '0')

    def test_base_template_muestra_contador_compacto_y_cifra_exacta_accesible(self):
        """El distintivo usa la forma compacta; la etiqueta accesible conserva el total."""
        from flask import render_template_string

        base_path = os.path.join(self.app.root_path, 'templates', 'base.html')
        with open(base_path, 'r', encoding='utf-8') as f:
            base_html = f.read()

        self.assertIn(
            '<span class="notification-count">{{ notificaciones_no_leidas|contador_compacto }}</span>',
            base_html,
        )
        self.assertIn('{{ notificaciones_no_leidas }} sin leer', base_html)

        with self.app.test_request_context('/'):
            html = render_template_string(
                '<span class="notification-count">{{ n|contador_compacto }}</span>', n=217,
            )
        self.assertEqual(html, '<span class="notification-count">99+</span>')

    def test_base_template_includes_lucide_and_scripts(self):
        """Verifica que base.html incluya lucide.min.js e inicialice los iconos."""
        base_path = os.path.join(self.app.root_path, 'templates', 'base.html')
        with open(base_path, 'r', encoding='utf-8') as f:
            base_html = f.read()

        self.assertIn('vendor/lucide/lucide.min.js', base_html)
        self.assertIn('lucide.createIcons()', base_html)
        self.assertIn('htmx:afterSwap', base_html)

    def test_base_template_navigation_uses_lucide_icons(self):
        """Verifica que la barra de navegación de fichas use iconos data-lucide."""
        base_path = os.path.join(self.app.root_path, 'templates', 'base.html')
        with open(base_path, 'r', encoding='utf-8') as f:
            base_html = f.read()

        nav_path = os.path.join(self.app.root_path, 'navegacion.py')
        with open(nav_path, 'r', encoding='utf-8') as f:
            nav_py = f.read()

        # El menú de la ficha declara cada icono en navegacion.py y base.html lo pinta con data-lucide.
        self.assertIn('data-lucide="{{ m.icon }}"', base_html)
        for icono in ('layout-dashboard', 'clipboard-check', 'file-check', 'sparkles', 'users', 'graduation-cap', 'compass', 'bar-chart-3', 'alert-triangle', 'book-open', 'search-check', 'folder', 'trophy', 'users-2'):
            self.assertIn(f"'{icono}'", nav_py)
        self.assertIn('data-lucide="bell"', base_html)
        self.assertIn('data-lucide="log-out"', base_html)


    def test_dashboard_template_renders_lucide_icons(self):
        """Verifica que dashboard.html renderice los iconos vectoriales de Lucide."""
        with self.app.test_request_context('/instructor/dashboard'):
            ficha = SimpleNamespace(
                id=1,
                codigo='3235642',
                codigo_programa='228118',
                nombre_programa='ANALISIS Y DESARROLLO DE SOFTWARE.',
                fecha_inicio=date(2025, 7, 25),
                fecha_fin=date(2027, 10, 24),
                duracion_productiva_meses=6,
            )
            cronograma = {
                'configurado': True,
                'porcentaje': 64.9,
                'porcentaje_lectiva': 64.9,
                'porcentaje_restante': 35.1,
                'fase': 'lectiva',
                'fase_label': 'Etapa lectiva',
                'inicio_lectiva': date(2025, 7, 25),
                'fin_lectiva': date(2027, 4, 23),
                'inicio_productiva': date(2027, 4, 24),
                'fin_productiva': date(2027, 10, 24),
                'dias_transcurridos': 414,
                'dias_totales': 638,
                'dias_restantes': 407,
                'dias_restantes_lectiva': 224,
                'meses_restantes_lectiva': 7.4,
                'meses_restantes_total': 13.4,
                'meses_productiva': 6,
                'mensaje': 'La etapa productiva dura 6 meses.',
            }
            fases_data = {
                'disponible': True,
                'planeacion_sincronizada': True,
                'desfase_fases': 0,
                'fase_esperada': {'nombre': 'EJECUCIÓN', 'icono': '⚙️', 'orden': 3},
                'fase_real': {'nombre': 'ANÁLISIS', 'icono': '🔍', 'orden': 1},
                'fases': [],
                'resumen_raps': {'porcentaje_aprobados': 38, 'aprobados': 29, 'total': 76},
                'mensaje_veredicto': 'Al día',
            }
            extra = {
                'total_aprendices': 20,
                'sesiones': 4,
                'pct_asistencia': 90,
                'pct_entregas': 80,
                'tareas_totales': 5,
                'entregas_totales': 16,
                'pendientes': 2,
                'planes_pendientes': 1,
                'aprendices_certificados': 0,
                'alertas_activas': 0,
                'top_competencias': [],
            }

            html = render_template(
                'instructor/dashboard.html',
                fichas=[ficha],
                cronogramas={1: cronograma},
                fases_fichas={1: fases_data},
                estadisticas_fichas={1: {'activos': 20, 'total': 20, 'estados': {'EN_FORMACION': 20}}},
                estadisticas_extra={1: extra},
                progreso_tyt=lambda f, n: None,
            )

            self.assertIn('data-lucide="folder-plus"', html)
            self.assertIn('data-lucide="search"', html)
            self.assertIn('data-lucide="layout-grid"', html)
            self.assertIn('data-lucide="list"', html)
            self.assertIn('data-lucide="file-text"', html)
            self.assertIn('data-lucide="inbox"', html)
            self.assertIn('data-lucide="clipboard-check"', html)
