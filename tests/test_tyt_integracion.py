import secrets
import tempfile
import unittest
from datetime import date, datetime

from app import create_app, db
from app.models import Aprendiz, Ficha, FichaInstructor, Instructor, Notificacion
from app.models.juicio import JuicioEvaluativo


class SeguimientoTyTTest(unittest.TestCase):
    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {}, 'UPLOAD_FOLDER': self.uploads.name,
            'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False,
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.usuarios = [Instructor(nombre=n, correo=f'{n}@example.com')
                         for n in ('dueno', 'colaborador', 'ajeno')]
        for usuario in self.usuarios:
            usuario.set_password(secrets.token_urlsafe(24))
        db.session.add_all(self.usuarios)
        db.session.flush()
        self.ficha = Ficha(codigo='TYT', nombre_programa='Programa de prueba',
                           instructor_id=self.usuarios[0].id,
                           fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 10, 11))
        db.session.add(self.ficha)
        db.session.flush()
        db.session.add(FichaInstructor(ficha_id=self.ficha.id, instructor_id=self.usuarios[1].id))
        self.aprendices = [Aprendiz(documento=str(n), nombre=nombre, apellidos='Prueba',
                                    ficha_id=self.ficha.id, estado=estado)
                          for n, nombre, estado in [(1, 'Ana', 'EN_FORMACION'),
                              (2, 'Luis', 'CONDICIONADO'), (3, 'Retirado', 'RETIRADO')]]
        db.session.add_all(self.aprendices)
        db.session.flush()
        for n in range(10):
            db.session.add(JuicioEvaluativo(
                ficha_id=self.ficha.id, aprendiz_id=self.aprendices[0].id,
                competencia='C1', resultado_aprendizaje=f'R{n}',
                juicio='APROBADO' if n < 6 else 'POR EVALUAR', huella=secrets.token_hex(32),
            ))
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.uploads.cleanup()

    def login(self, indice):
        from flask import g
        g.pop('_login_user', None)
        with self.client.session_transaction() as s:
            s['_user_id'] = str(self.usuarios[indice].id)
            s['_fresh'] = True

    def test_avisos_para_vinculados_y_activos_sin_duplicados(self):
        from app.tyt.avisos import actualizar_avisos
        for _ in range(2):
            actualizar_avisos(self.ficha, ahora=datetime(2026, 3, 11, 12))
            db.session.commit()
        mensajes = Notificacion.query.filter_by(tipo='tyt').all()
        assert len(mensajes) == 4
        ana = next(n for n in mensajes if n.destinatario_tipo == 'aprendiz'
                   and n.destinatario_id == self.aprendices[0].id)
        assert '1 resultado' in ana.mensaje
        assert 'Luis' not in ana.mensaje
        assert 'documento=' not in ana.url

    def test_no_notifica_antes_del_hito(self):
        from app.tyt.avisos import actualizar_avisos
        actualizar_avisos(self.ficha, ahora=datetime(2026, 3, 10, 12))
        db.session.commit()
        assert Notificacion.query.count() == 0

    def test_hito_lectivo_no_espera_el_setenta_del_total(self):
        from app.tyt.consulta import obtener_seguimiento
        r = obtener_seguimiento(self.ficha, date(2026, 3, 11))
        assert r['tiempo']['fecha_hito'] == date(2026, 3, 11)
        assert r['tiempo']['porcentaje'] == 70
        assert r['tiempo']['alcanzado']
        assert r['calendario']['fin_lectiva'] == date(2026, 4, 10)

    def test_productiva_se_muestra_aparte_y_sin_porcentaje(self):
        from flask import render_template_string
        from flask_login import login_user
        from app.services.cronograma import obtener_cronograma
        with self.app.test_request_context('/instructor/'):
            login_user(self.usuarios[0])
            html = render_template_string("{% include '_cronograma.html' %}", ficha=self.ficha,
                                          cronograma=obtener_cronograma(self.ficha))
        assert 'Tiempo transcurrido de la etapa lectiva' in html
        assert 'Desde la inducción hasta el final de la etapa lectiva' in html
        assert 'Inicio etapa lectiva' in html
        assert 'Inicio etapa productiva' in html
        assert 'Fin de la ficha' in html
        assert 'data-etapa="productiva"' in html
        fase = html.split('data-etapa="productiva"', 1)[1].split('</section>', 1)[0]
        assert '6 meses' in fase
        assert '%' not in fase
        assert 'progressbar' not in fase

    def test_lectura_se_actualiza_y_excluye_retirados(self):
        from app.tyt.consulta import obtener_seguimiento
        previo = obtener_seguimiento(self.ficha)
        assert previo['total_aprendices'] == 2
        assert previo['promedio_aprobados'] == 30
        JuicioEvaluativo.query.update({'juicio': 'APROBADO'})
        db.session.commit()
        assert obtener_seguimiento(self.ficha)['promedio_aprobados'] == 50

    def test_revision_periodica_publica_sin_visitar_el_panel(self):
        from datetime import timezone
        from unittest.mock import patch
        from app.tyt.revision import revisar_hitos
        with patch('app.tyt.revision.datetime') as reloj:
            reloj.now.return_value = datetime(2026, 3, 11, 12, tzinfo=timezone.utc)
            revisar_hitos()
            revisar_hitos()
        assert Notificacion.query.filter_by(tipo='tyt').count() == 4

    def test_primera_carga_muestra_la_campana_actualizada(self):
        from unittest.mock import patch
        from app.tyt.consulta import obtener_seguimiento
        real = obtener_seguimiento
        self.login(0)
        with patch('app.tyt.avisos.obtener_seguimiento',
                   side_effect=lambda ficha, hoy: real(ficha, date(2026, 3, 11))):
            respuesta = self.client.get('/instructor/')
        assert respuesta.status_code == 200
        assert 'Notificaciones: 1 sin leer' in respuesta.get_data(as_text=True)

    def test_instructor_vinculado_ve_brecha_individual(self):
        self.login(1)
        r = self.client.get(f'/instructor/fichas/{self.ficha.id}/seguimiento-tyt')
        assert r.status_code == 200
        assert 'Luis Prueba' in r.get_data(as_text=True)
        assert 'Faltan por evaluar' in r.get_data(as_text=True)

    def test_ajeno_y_no_autenticado_no_ven_grupo(self):
        ruta = f'/instructor/fichas/{self.ficha.id}/seguimiento-tyt'
        assert self.client.get(ruta).status_code == 302
        self.login(2)
        assert self.client.get(ruta).status_code == 403
        assert self.client.get('/instructor/fichas/999/seguimiento-tyt').status_code == 404

    def test_tarjeta_personal_no_filtra_datos_de_companeros(self):
        from flask import render_template_string, session
        with self.app.test_request_context('/aprendiz/panel'):
            session['aprendiz_documento'] = self.aprendices[0].documento
            session['aprendiz_ficha_id'] = self.ficha.id
            html = render_template_string(
                "{% set tyt = progreso_tyt(ficha, aprendiz) %}{% include 'tyt/_tarjeta.html' %}",
                ficha=self.ficha, aprendiz=self.aprendices[0],
            )
            assert 'Te falta' in html
            assert 'Luis' not in html
            assert f'/instructor/fichas/{self.ficha.id}/seguimiento-tyt' not in html
