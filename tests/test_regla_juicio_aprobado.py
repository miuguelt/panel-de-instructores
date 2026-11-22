"""Un juicio solo cuenta como aprobado si dice «APROBADO» de forma explícita.

SOFIA Plus también reporta «NO APROBADO» y «AÚN NO APROBADO». La regla
anterior (`'APROBADO' in texto and 'AUN NO' not in texto`) los contaba como
aprobados y por eso inflaba el avance en todas las vistas.
"""

import re
import secrets
import unittest
from pathlib import Path

from flask import template_rendered

from app import create_app, db
from app.models import Aprendiz, Ficha, Instructor
from app.models.juicio import JuicioEvaluativo
from app.services.resumen_ficha import obtener_resumen_ficha_360

RAIZ = Path(__file__).resolve().parents[1]
JUICIOS = ['APROBADO', 'NO APROBADO', 'AÚN NO APROBADO', 'AUN NO APROBADO', 'POR EVALUAR']


class ReglaJuicioAprobadoTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                               'SQLALCHEMY_ENGINE_OPTIONS': {}, 'WTF_CSRF_ENABLED': False,
                               'RATELIMIT_ENABLED': False, 'SECRET_KEY': secrets.token_hex(16)})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.instructor = Instructor(nombre='Instructor', correo='regla-juicio@example.com')
        self.instructor.set_password(secrets.token_urlsafe(16))
        db.session.add(self.instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='4040', nombre_programa='ADSO', instructor_id=self.instructor.id)
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendiz = Aprendiz(documento='777', nombre='Ana', apellidos='Ruiz', ficha_id=self.ficha.id)
        db.session.add(self.aprendiz)
        db.session.flush()
        for i, juicio in enumerate(JUICIOS):
            db.session.add(JuicioEvaluativo(
                ficha_id=self.ficha.id, aprendiz_id=self.aprendiz.id, competencia='220501096 - Desarrollar',
                tipo_competencia='tecnica', resultado_aprendizaje=f'RAP {i}', juicio=juicio,
                funcionario_registro='Instructora'))
        db.session.commit()
        self.cliente = self.app.test_client()
        self.contextos = []
        template_rendered.connect(self._capturar, self.app)

    def tearDown(self):
        template_rendered.disconnect(self._capturar, self.app)
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _capturar(self, _app, template=None, context=None, **_extra):
        self.contextos.append(context or {})

    def _como_instructor(self):
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True

    def _contexto(self, url, clave):
        respuesta = self.cliente.get(url)
        self.assertEqual(respuesta.status_code, 200, url)
        return next(c[clave] for c in reversed(self.contextos) if clave in c)

    def test_no_queda_la_regla_por_subcadena_en_la_aplicacion(self):
        patron = re.compile(r"'APROBADO'\s+in\s|like\(\s*'%APROBADO%'")
        hallazgos = [f'{ruta.relative_to(RAIZ)}:{n}'
                     for ruta in (RAIZ / 'app').rglob('*.py')
                     for n, linea in enumerate(ruta.read_text(encoding='utf-8').splitlines(), 1)
                     if patron.search(linea)]
        self.assertEqual(hallazgos, [], 'Use es_aprobado() o condicion_aprobado_sql().')

    def test_vision_general_cuenta_un_solo_aprobado(self):
        resumen = obtener_resumen_ficha_360(self.ficha)
        self.assertEqual((resumen['juicios_aprobados'], resumen['juicios_totales']), (1, 5))
        self.assertEqual(resumen['pct_juicios'], 20)

    def test_mis_fichas_cuenta_un_solo_aprobado(self):
        self._como_instructor()
        extra = self._contexto('/instructor/', 'estadisticas_extra')[self.ficha.id]
        self.assertEqual((extra['juicios_aprobados'], extra['juicios_totales'], extra['pct_juicios']), (1, 5, 20))

    def test_estadisticas_cuentan_un_solo_aprobado(self):
        self._como_instructor()
        self.assertEqual(self._contexto(f'/instructor/fichas/{self.ficha.id}/estadisticas', 'pct_global'), 20)

    def test_juicios_cuentan_un_solo_aprobado(self):
        self._como_instructor()
        estadisticas = self._contexto(f'/instructor/fichas/{self.ficha.id}/juicios', 'estadisticas')
        self.assertEqual((estadisticas['aprobados'], estadisticas['total']), (1, 5))

    def test_historial_cuenta_un_solo_aprobado(self):
        self._como_instructor()
        self.cliente.get(f'/instructor/fichas/{self.ficha.id}/aprendices/{self.aprendiz.id}/historial')
        contexto = next(c for c in reversed(self.contextos) if 'aprendiz' in c and 'ficha' in c)
        texto = repr({k: v for k, v in contexto.items() if 'juicio' in k or 'stats' in k})
        self.assertNotIn("'aprobados': 3", texto)
        self.assertNotIn("'aprobados': 4", texto)

    def test_panel_del_aprendiz_cuenta_un_solo_aprobado(self):
        with self.cliente.session_transaction() as sesion:
            sesion['aprendiz_documento'] = '777'
            sesion['aprendiz_ficha_id'] = self.ficha.id
        stats = self._contexto(f'/aprendiz/{self.ficha.id}/panel', 'stats_juicios')
        self.assertEqual((stats['aprobados'], stats['total'], stats['pct_total']), (1, 5, 20))


if __name__ == '__main__':
    unittest.main()


class FuncionesCanonicasTest(unittest.TestCase):
    def test_aprobado_y_evaluado_con_tildes_y_codigos(self):
        from app.services.emparejamiento_juicios import es_aprobado, es_evaluado
        self.assertEqual([es_aprobado(j) for j in JUICIOS], [True, False, False, False, False])
        self.assertEqual([es_evaluado(j) for j in JUICIOS + ['A', 'NA', None]],
                         [True, True, True, True, False, True, True, False])

    def test_condicion_sql_coincide_con_la_regla_en_python(self):
        from app.services.emparejamiento_juicios import condicion_aprobado_sql
        app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'SQLALCHEMY_ENGINE_OPTIONS': {}})
        with app.app_context():
            filas = db.session.query(condicion_aprobado_sql(db.literal(' aprobado ')),
                                     condicion_aprobado_sql(db.literal('NO APROBADO'))).one()
        self.assertEqual(tuple(bool(v) for v in filas), (True, False))
