"""Cache de estáticos y ausencia de consultas N+1 en las vistas de ficha."""

import tempfile
import unittest
from datetime import date, datetime, timedelta

from sqlalchemy import event

from app import create_app, db
from app.models import (
    Aprendiz,
    Entrega,
    Ficha,
    FichaInstructor,
    Instructor,
    RegistroAsistencia,
    SesionAsistencia,
    Tarea,
)
from app.models.juicio import JuicioEvaluativo


class BaseRendimiento(unittest.TestCase):
    """Monta una ficha del tamaño indicado y permite contar consultas por petición."""

    APRENDICES = 4
    SESIONES = 3
    TAREAS = 2

    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'UPLOAD_FOLDER': self.uploads.name,
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        self._sembrar()
        self.cliente = self.app.test_client()
        self.cliente.post(
            '/login',
            data={'correo': 'rendimiento@sena.edu.co', 'password': 'clave-segura'},
            follow_redirects=True,
        )

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def _sembrar(self):
        instructor = Instructor(
            nombre='Instructor Rendimiento',
            correo='rendimiento@sena.edu.co',
            rol='admin',
        )
        instructor.set_password('clave-segura')
        db.session.add(instructor)
        db.session.flush()

        self.ficha = Ficha(
            codigo='3999999',
            codigo_ficha='3999999',
            nombre_programa='Análisis y Desarrollo de Software',
            instructor_id=instructor.id,
            fecha_inicio=date(2025, 1, 1),
        )
        db.session.add(self.ficha)
        db.session.flush()
        db.session.add(
            FichaInstructor(ficha_id=self.ficha.id, instructor_id=instructor.id)
        )

        aprendices = []
        for indice in range(self.APRENDICES):
            aprendiz = Aprendiz(
                documento=f'900{indice:04d}',
                nombre=f'Nombre{indice}',
                apellidos=f'Apellido{indice:03d}',
                estado='EN_FORMACION',
                ficha_id=self.ficha.id,
            )
            db.session.add(aprendiz)
            aprendices.append(aprendiz)
        db.session.flush()
        self.documento_aprendiz = aprendices[0].documento

        for aprendiz in aprendices:
            for competencia in range(2):
                db.session.add(JuicioEvaluativo(
                    aprendiz_id=aprendiz.id,
                    ficha_id=self.ficha.id,
                    competencia=f'Competencia {competencia}',
                    resultado_aprendizaje=f'RAP {competencia}',
                    juicio='APROBADO' if competencia else 'POR EVALUAR',
                    funcionario_registro='Instructor Rendimiento',
                    fecha_juicio=date(2025, 3, 1),
                    tipo_competencia='tecnica',
                    huella=f'{aprendiz.id}-{competencia}',
                ))

        for indice in range(self.SESIONES):
            sesion = SesionAsistencia(
                ficha_id=self.ficha.id,
                fecha=date(2025, 2, 1) + timedelta(days=indice),
            )
            db.session.add(sesion)
            db.session.flush()
            for posicion, aprendiz in enumerate(aprendices):
                db.session.add(RegistroAsistencia(
                    sesion_id=sesion.id,
                    aprendiz_id=aprendiz.id,
                    estado='ASISTE' if (posicion + indice) % 4 else 'FALTA',
                ))

        for indice in range(self.TAREAS):
            tarea = Tarea(
                ficha_id=self.ficha.id,
                instructor_id=instructor.id,
                titulo=f'Tarea {indice}',
                descripcion='Evidencia de prueba',
                fecha_limite=datetime(2025, 4, 1) + timedelta(days=indice),
            )
            db.session.add(tarea)
            db.session.flush()
            for posicion, aprendiz in enumerate(aprendices):
                if posicion % 2 == 0:
                    db.session.add(Entrega(
                        tarea_id=tarea.id,
                        aprendiz_id=aprendiz.id,
                        calificada=True,
                        calificacion='4.0',
                        estado_revision='aprobada',
                    ))
        db.session.commit()

    def contar_consultas(self, url):
        """Consultas emitidas por una petición ya "calentada".

        La primera visita crea alertas, contadores de aseo y el corte de
        ranking; lo que interesa medir es la carga en régimen normal.
        """
        self.cliente.get(url)
        consultas = []

        def registrar(conn, cursor, statement, params, context, executemany):
            consultas.append(statement)

        event.listen(db.engine, 'before_cursor_execute', registrar)
        try:
            respuesta = self.cliente.get(url)
        finally:
            event.remove(db.engine, 'before_cursor_execute', registrar)
        return respuesta, consultas


class CacheEstaticosTestCase(BaseRendimiento):
    APRENDICES = 1
    SESIONES = 0
    TAREAS = 0

    def test_estaticos_se_sirven_con_caducidad_larga(self):
        respuesta = self.cliente.get('/static/css/styles.css')
        self.assertEqual(respuesta.status_code, 200)
        cache_control = respuesta.headers.get('Cache-Control', '')
        self.assertIn('public', cache_control)
        self.assertIn('max-age=31536000', cache_control)
        self.assertIn('immutable', cache_control)

    def test_las_plantillas_versionan_la_url_del_estatico(self):
        html = self.cliente.get('/instructor/fichas').get_data(as_text=True)
        self.assertIn('/static/css/styles.css?v=', html)
        self.assertIn('/static/js/table-filters.js?v=', html)

    def test_las_descargas_no_heredan_la_caducidad_larga(self):
        # Solo el endpoint 'static' se cachea: los reportes generados y los
        # archivos subidos deben seguir revalidando en cada descarga.
        respuesta = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/plantilla-excel')
        self.assertNotIn('max-age=31536000', respuesta.headers.get('Cache-Control', ''))


class SinConsultasNMasUnoTestCase(BaseRendimiento):
    """El número de consultas de cada vista no debe crecer con el tamaño de la ficha."""

    APRENDICES = 4
    SESIONES = 3
    TAREAS = 2

    RUTAS = (
        '/instructor/fichas/{f}/aprendices',
        '/instructor/fichas/{f}/juicios',
        '/instructor/fichas/{f}/estadisticas',
        '/instructor/fichas/{f}/asistencia',
        '/instructor/fichas/{f}/alertas',
        '/instructor/fichas/{f}/casos-seguimiento',
        '/instructor/fichas/{f}/ranking',
        '/instructor/fichas/{f}/turnos-aseo',
    )

    def test_las_vistas_de_ficha_no_escalan_con_los_aprendices(self):
        pequena = {}
        for plantilla in self.RUTAS:
            respuesta, consultas = self.contar_consultas(
                plantilla.format(f=self.ficha.id)
            )
            self.assertEqual(respuesta.status_code, 200, plantilla)
            pequena[plantilla] = len(consultas)

        # Se cuadruplica la ficha en el mismo escenario y se vuelve a medir.
        self.tearDown()
        type(self).APRENDICES = 16
        type(self).SESIONES = 12
        type(self).TAREAS = 8
        try:
            self.setUp()
            for plantilla in self.RUTAS:
                respuesta, consultas = self.contar_consultas(
                    plantilla.format(f=self.ficha.id)
                )
                self.assertEqual(respuesta.status_code, 200, plantilla)
                self.assertLessEqual(
                    len(consultas),
                    pequena[plantilla] + 4,
                    f'{plantilla} pasó de {pequena[plantilla]} a {len(consultas)} '
                    'consultas al agrandar la ficha: hay un N+1.',
                )
        finally:
            type(self).APRENDICES = 4
            type(self).SESIONES = 3
            type(self).TAREAS = 2

    def test_el_panel_del_aprendiz_no_escala_con_la_ficha(self):
        url = f'/aprendiz/{self.ficha.id}/panel'
        self.cliente.get(f'{url}?documento={self.documento_aprendiz}',
                         follow_redirects=True)
        _respuesta, consultas = self.contar_consultas(url)
        pequena = len(consultas)

        self.tearDown()
        type(self).APRENDICES = 16
        type(self).SESIONES = 12
        type(self).TAREAS = 8
        try:
            self.setUp()
            url = f'/aprendiz/{self.ficha.id}/panel'
            self.cliente.get(f'{url}?documento={self.documento_aprendiz}',
                             follow_redirects=True)
            respuesta, consultas = self.contar_consultas(url)
            self.assertEqual(respuesta.status_code, 200)
            self.assertLessEqual(
                len(consultas),
                pequena + 4,
                f'El panel pasó de {pequena} a {len(consultas)} consultas: hay un N+1.',
            )
        finally:
            type(self).APRENDICES = 4
            type(self).SESIONES = 3
            type(self).TAREAS = 2


if __name__ == '__main__':
    unittest.main()
