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

        self.assertIn('data-lucide="layout-dashboard"', base_html)
        self.assertIn('data-lucide="clipboard-check"', base_html)
        self.assertIn('data-lucide="file-check"', base_html)
        self.assertIn('data-lucide="sparkles"', base_html)
        self.assertIn('data-lucide="users"', base_html)
        self.assertIn('data-lucide="graduation-cap"', base_html)
        self.assertIn('data-lucide="compass"', base_html)
        self.assertIn('data-lucide="bar-chart-3"', base_html)
        self.assertIn('data-lucide="alert-triangle"', base_html)
        self.assertIn('data-lucide="book-open"', base_html)
        self.assertIn('data-lucide="search-check"', base_html)
        self.assertIn('data-lucide="folder"', base_html)
        self.assertIn('data-lucide="trophy"', base_html)
        self.assertIn('data-lucide="users-2"', base_html)
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
