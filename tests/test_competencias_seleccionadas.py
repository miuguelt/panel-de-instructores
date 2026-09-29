import json
import unittest
from app import create_app, db
from app.models import Ficha, Instructor, FichaInstructor, JuicioEvaluativo, FichaCompetenciaSeleccionada, Aprendiz


class CompetenciasSeleccionadasTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        # Crear instructores
        self.inst1 = Instructor(nombre='Instructor Uno', correo='inst1@sena.edu.co')
        self.inst1.set_password('pass123')
        self.inst2 = Instructor(nombre='Instructor Dos', correo='inst2@sena.edu.co')
        self.inst2.set_password('pass123')
        db.session.add_all([self.inst1, self.inst2])
        db.session.commit()

        # Crear ficha
        self.ficha = Ficha(codigo=222333, nombre_programa='PROD SOFTWARE', instructor_id=self.inst1.id)
        db.session.add(self.ficha)
        db.session.commit()

        # Asociar inst2 a ficha
        fi = FichaInstructor(ficha_id=self.ficha.id, instructor_id=self.inst2.id)
        db.session.add(fi)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _autenticar(self, instructor):
        from flask import g
        g.pop('_login_user', None)
        with self.client.session_transaction() as sesion:
            sesion['_user_id'] = str(instructor.id)
            sesion['_fresh'] = True

    def test_toggle_competencia_seleccion(self):
        self._autenticar(self.inst1)

        # 1. Seleccionar competencia para inst1
        comp_name = "ESTABLECER REQUISITOS DEL SOFTWARE"
        res = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/toggle',
            json={'competencia': comp_name}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'selected')
        self.assertTrue(data['esta_seleccionada'])
        self.assertTrue(data['seleccionada_por']['es_propia'])
        self.assertEqual(data['seleccionada_por']['nombre'], 'Instructor Uno')

        # Verificar persisencia en DB
        sel_db = FichaCompetenciaSeleccionada.query.filter_by(
            ficha_id=self.ficha.id, competencia=comp_name
        ).first()
        self.assertIsNotNone(sel_db)
        self.assertEqual(sel_db.instructor_id, self.inst1.id)

        # 2. Deseleccionar por el mismo instructor (inst1)
        res2 = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/toggle',
            json={'competencia': comp_name}
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2['success'])
        self.assertEqual(data2['action'], 'deselected')
        self.assertFalse(data2['esta_seleccionada'])

        sel_db2 = FichaCompetenciaSeleccionada.query.filter_by(
            ficha_id=self.ficha.id, competencia=comp_name
        ).first()
        self.assertIsNone(sel_db2)

    def test_reinstalar_o_cambiar_seleccion_entre_instructores(self):
        # 1. inst1 selecciona la competencia
        self._autenticar(self.inst1)
        comp_name = "DISEÑAR LA SOLUCION DE SOFTWARE"
        self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/toggle',
            json={'competencia': comp_name}
        )

        # 2. inst2 hace login y toma la competencia
        self._autenticar(self.inst2)

        # inst2 hace toggle en la misma competencia
        res = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/toggle',
            json={'competencia': comp_name}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['action'], 'selected')
        self.assertTrue(data['seleccionada_por']['es_propia'])
        self.assertEqual(data['seleccionada_por']['nombre'], 'Instructor Dos')

        sel_db = FichaCompetenciaSeleccionada.query.filter_by(
            ficha_id=self.ficha.id, competencia=comp_name
        ).first()
        self.assertEqual(sel_db.instructor_id, self.inst2.id)

    def test_verificacion_permisos(self):
        # Crear instructor3 sin acceso a la ficha
        inst3 = Instructor(nombre='Instructor Tres', correo='inst3@sena.edu.co')
        inst3.set_password('pass123')
        db.session.add(inst3)
        db.session.commit()

        self._autenticar(inst3)
        res = self.client.post(
            f'/instructor/fichas/{self.ficha.id}/competencias/toggle',
            json={'competencia': 'COMPETENCIA PRUEBA'}
        )
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertFalse(data['success'])

    def test_juicios_header_in_navbar(self):
        self._autenticar(self.inst1)
        res = self.client.get(f'/instructor/fichas/{self.ficha.id}/juicios')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        # Verificar que la barra contextual aparece en el navbar
        self.assertIn('nav-context-slot', html)
        self.assertIn('nav-context-bar', html)
        self.assertIn('nav-context-btn-back', html)
        self.assertIn('Juicios de Evaluación', html)
        self.assertIn('Analizar planeación', html)
        # Verificar que el header antiguo no duplica el contenido dentro de juicios-container
        self.assertNotIn('<div class="page-header">\n        <div class="page-title-cluster">', html)

    def test_modal_detalle_competencia_estructura_y_dialogo(self):
        self._autenticar(self.inst1)
        res = self.client.get(f'/instructor/fichas/{self.ficha.id}/juicios')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # 1. El modal debe ser un elemento <dialog> nativo con la clase estándar
        self.assertIn('<dialog id="comp-modal-overlay" class="app-modal-overlay"', html)
        self.assertIn('aria-labelledby="modal-comp-title"', html)

        # 2. Encabezado con eyebrow, h2 semántico y botón accesible de cierre
        self.assertIn('class="app-modal-eyebrow">Detalle de competencia</span>', html)
        self.assertIn('id="modal-comp-title"', html)
        self.assertIn('aria-label="Cerrar detalle"', html)
        self.assertIn('onclick="closeCompModal()"', html)

        # 3. Contenedores de KPIs, evaluadores, RAPs y aprendices pendientes
        self.assertIn('id="modal-kpis"', html)
        self.assertIn('id="modal-ring-wrap"', html)
        self.assertIn('id="modal-evaluadores"', html)
        self.assertIn('id="modal-raps"', html)
        self.assertIn('id="modal-pendientes-section"', html)
        self.assertIn('</dialog>', html)

    def test_modal_detalle_datos_json_y_acceso(self):
        # Crear un aprendiz y un juicio evaluativo
        ap = Aprendiz(
            ficha_id=self.ficha.id,
            documento='1098765432',
            nombre='Carlos',
            apellidos='Gomez',
            estado='EN_FORMACION'
        )
        db.session.add(ap)
        db.session.commit()

        j = JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=ap.id,
            competencia='38199 - Orientar investigacion',
            resultado_aprendizaje='RAP 01 - Formular propuesta',
            juicio='APROBADO',
            tipo_competencia='transversal',
            funcionario_registro='Instructor Demo'
        )
        db.session.add(j)
        db.session.commit()

        self._autenticar(self.inst1)
        res = self.client.get(f'/instructor/fichas/{self.ficha.id}/juicios')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # La tarjeta debe incluir la acción de análisis detallado y el trigger del modal
        self.assertIn('openCompModal(0)', html)
        self.assertIn('Ver análisis detallado', html)

        # El JSON de comp-data debe existir y ser válido
        self.assertIn('<script id="comp-data" type="application/json">', html)
        start = html.find('id="comp-data"')
        s = html.find('>', start) + 1
        e = html.find('</script>', s)
        json_data = json.loads(html[s:e].strip())
        self.assertIsInstance(json_data, list)
        self.assertGreaterEqual(len(json_data), 1)

        comp = json_data[0]
        self.assertEqual(comp['nombre'], '38199 - Orientar investigacion')
        self.assertEqual(comp['tipo'], 'transversal')
        self.assertIn('detalles', comp)
        self.assertEqual(len(comp['detalles']), 1)
        det = comp['detalles'][0]
        self.assertEqual(det['documento'], '1098765432')
        self.assertEqual(det['estado'], 'APROBADO')
        self.assertEqual(det['evaluador'], 'Instructor Demo')

    def test_estilos_sin_will_change_en_contenido_principal(self):
        # Verificar que el CSS de main#contenido-principal no tenga will-change: transform
        import os
        css_path = os.path.join(self.app.root_path, 'static', 'css', 'styles.css')
        with open(css_path, 'r', encoding='utf-8') as f:
            css = f.read()

        # En main#contenido-principal no debe estar will-change que rompa modales fixed
        idx = css.find('main#contenido-principal')
        self.assertNotEqual(idx, -1)
        bloque = css[idx:idx+150]
        self.assertNotIn('will-change', bloque)


if __name__ == '__main__':
    unittest.main()

