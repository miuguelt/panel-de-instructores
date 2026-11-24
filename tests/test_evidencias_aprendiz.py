"""Estado y plazo de cada evidencia del aprendiz (funciones puras)."""

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.evidencias_aprendiz import (
    estado_evidencia_tarea,
    plazo_evidencia,
    saludo_por_hora,
    texto_duracion,
)

AHORA = datetime(2026, 11, 21, 12, 0)


def entrega(revision='pendiente', fecha=AHORA, instructor=False):
    return SimpleNamespace(estado_revision=revision, fecha_entrega=fecha, registrada_por_instructor=instructor)


class EstadoTest(unittest.TestCase):
    def test_estados(self):
        limite = AHORA + timedelta(days=1)
        self.assertEqual(estado_evidencia_tarea(None, limite, AHORA), 'pendiente')
        self.assertEqual(estado_evidencia_tarea(None, AHORA - timedelta(minutes=1), AHORA), 'vencida')
        self.assertEqual(estado_evidencia_tarea(None, None, AHORA), 'pendiente')
        self.assertEqual(estado_evidencia_tarea(entrega('rechazada'), limite, AHORA), 'correccion')
        self.assertEqual(estado_evidencia_tarea(entrega(), limite, AHORA), 'entregada')
        self.assertEqual(estado_evidencia_tarea(entrega(), None, AHORA), 'entregada')
        tarde = entrega(fecha=limite + timedelta(hours=1))
        self.assertEqual(estado_evidencia_tarea(tarde, limite, AHORA), 'retraso')
        tarde.registrada_por_instructor = True
        self.assertEqual(estado_evidencia_tarea(tarde, limite, AHORA), 'entregada', 'registrada por el instructor no es retraso')


class DuracionTest(unittest.TestCase):
    def test_textos(self):
        self.assertEqual(texto_duracion(86400), '1 día')
        self.assertEqual(texto_duracion(2 * 86400 + 3600), '2 días y 1 hora')
        self.assertEqual(texto_duracion(86400 + 7200), '1 día y 2 horas')
        self.assertEqual(texto_duracion(3600), '1 hora')
        self.assertEqual(texto_duracion(2 * 3600 + 60), '2 horas y 1 minuto')
        self.assertEqual(texto_duracion(3600 + 120), '1 hora y 2 minutos')
        self.assertEqual(texto_duracion(10), '1 minuto')
        self.assertEqual(texto_duracion(600), '10 minutos')


class PlazoTest(unittest.TestCase):
    def tarea(self, dias_creada=10):
        return SimpleNamespace(creada_en=AHORA - timedelta(days=dias_creada))

    def test_sin_limite(self):
        self.assertEqual(plazo_evidencia(self.tarea(), None, 'pendiente', None, AHORA), (None, None, None))

    def test_clases_por_tiempo_restante(self):
        tarea = self.tarea()
        self.assertEqual(plazo_evidencia(tarea, None, 'pendiente', AHORA + timedelta(hours=5), AHORA)[1:], ('urgent', 'Quedan 5 horas'))
        self.assertEqual(plazo_evidencia(tarea, None, 'pendiente', AHORA + timedelta(days=2), AHORA)[1], 'soon')
        progreso, clase, texto = plazo_evidencia(tarea, None, 'pendiente', AHORA + timedelta(days=10), AHORA)
        self.assertEqual((progreso, clase, texto), (50, 'normal', 'Quedan 10 días'))

    def test_vencida(self):
        progreso, clase, texto = plazo_evidencia(self.tarea(), None, 'vencida', AHORA - timedelta(days=1, hours=3), AHORA)
        self.assertEqual((progreso, clase, texto), (100, 'overdue', 'Plazo vencido hace 1 día y 3 horas'))

    def test_entregada_completa_el_plazo(self):
        resultado = plazo_evidencia(self.tarea(), entrega(), 'entregada', AHORA + timedelta(days=1), AHORA)
        self.assertEqual(resultado, (100, 'complete', 'Evidencia entregada'))

    def test_sin_fecha_de_creacion(self):
        tarea = SimpleNamespace(creada_en=None)
        self.assertEqual(plazo_evidencia(tarea, None, 'pendiente', AHORA + timedelta(days=1), AHORA), (None, 'urgent', 'Quedan 1 día'))
        self.assertEqual(plazo_evidencia(tarea, entrega(), 'retraso', AHORA + timedelta(days=1), AHORA), (None, 'complete', 'Evidencia entregada'))


class SaludoTest(unittest.TestCase):
    def test_franjas(self):
        self.assertEqual(saludo_por_hora(6), '¡Buenos días')
        self.assertEqual(saludo_por_hora(12), '¡Buenas tardes')
        self.assertEqual(saludo_por_hora(19), '¡Buenas noches')
        self.assertEqual(saludo_por_hora(3), '¡Buenas noches')


class ContarEvidenciasPendientesTest(unittest.TestCase):
    """Una sola fuente para «por entregar»: cabecera, pestaña Evidencias y pestaña Mi grupo."""

    def test_separa_individuales_y_grupales(self):
        from app.services.evidencias_aprendiz import contar_evidencias_pendientes
        individuales = [{'estado': e} for e in ('pendiente', 'correccion', 'vencida', 'entregada', 'aprobada')]
        grupales = [{'estado': 'pendiente'}, {'estado': 'retraso'}]
        self.assertEqual(contar_evidencias_pendientes(individuales, grupales),
                         {'individuales': 3, 'grupales': 1, 'total': 4})

    def test_sin_tareas(self):
        from app.services.evidencias_aprendiz import contar_evidencias_pendientes
        self.assertEqual(contar_evidencias_pendientes([], None), {'individuales': 0, 'grupales': 0, 'total': 0})


if __name__ == '__main__':
    unittest.main()


class TareasDelAprendizTest(unittest.TestCase):
    """Consulta real: prórroga, plan, entregas y exclusión de trabajos grupales."""

    def setUp(self):
        import secrets
        from app import create_app, db
        from app.models import Aprendiz, Ficha, Instructor
        self.db = db
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'SQLALCHEMY_ENGINE_OPTIONS': {}})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        instructor = Instructor(nombre='Instructor', correo='evidencias@example.com')
        instructor.set_password(secrets.token_urlsafe(16))
        db.session.add(instructor)
        db.session.flush()
        self.ficha = Ficha(codigo='5050', nombre_programa='ADSO', instructor_id=instructor.id)
        db.session.add(self.ficha)
        db.session.flush()
        self.aprendiz = Aprendiz(documento='1', nombre='Ana', apellidos='Ruiz', ficha_id=self.ficha.id)
        db.session.add(self.aprendiz)
        db.session.flush()
        self.instructor = instructor

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.ctx.pop()

    def test_prorroga_plan_entrega_y_grupales(self):
        from app.models.alertas import PlanMejoramiento
        from app.models.tarea import Entrega, ProrrogaTarea, Tarea
        from app.services.evidencias_aprendiz import tareas_del_aprendiz
        db = self.db
        comun = {'ficha_id': self.ficha.id, 'instructor_id': self.instructor.id, 'creada_en': AHORA - timedelta(days=4)}
        vencida = Tarea(titulo='Vencida con prórroga', fecha_limite=AHORA - timedelta(days=1), **comun)
        entregada = Tarea(titulo='Entregada', fecha_limite=AHORA + timedelta(days=2), **comun)
        grupal = Tarea(titulo='Grupal', fecha_limite=AHORA + timedelta(days=2), es_grupal=True, **comun)
        db.session.add_all([vencida, entregada, grupal])
        db.session.flush()
        db.session.add_all([
            ProrrogaTarea(tarea_id=vencida.id, aprendiz_id=self.aprendiz.id, instructor_id=self.instructor.id,
                          nueva_fecha_limite=AHORA + timedelta(days=5)),
            PlanMejoramiento(aprendiz_id=self.aprendiz.id, ficha_id=self.ficha.id, tarea_id=vencida.id, actividades='Repasar'),
            Entrega(tarea_id=entregada.id, aprendiz_id=self.aprendiz.id, fecha_entrega=AHORA - timedelta(hours=1)),
        ])
        db.session.commit()
        items = {i['tarea'].titulo: i for i in tareas_del_aprendiz(self.ficha.id, self.aprendiz.id, AHORA)}
        self.assertNotIn('Grupal', items)
        self.assertEqual(items['Vencida con prórroga']['estado'], 'pendiente', 'la prórroga amplía el plazo')
        self.assertEqual(items['Vencida con prórroga']['limite_efectivo'], AHORA + timedelta(days=5))
        self.assertEqual(items['Vencida con prórroga']['plan'].actividades, 'Repasar')
        self.assertEqual(items['Entregada']['estado'], 'entregada')
        self.assertEqual(items['Entregada']['clase_plazo'], 'complete')

    def test_lista_de_tareas_ya_filtrada(self):
        from app.models.tarea import Tarea
        from app.services.evidencias_aprendiz import tareas_del_aprendiz
        comun = {'ficha_id': self.ficha.id, 'instructor_id': self.instructor.id}
        propia, otra = Tarea(titulo='Propia', **comun), Tarea(titulo='Otra', **comun)
        self.db.session.add_all([propia, otra])
        self.db.session.commit()
        items = tareas_del_aprendiz(self.ficha.id, self.aprendiz.id, AHORA, tareas=[propia])
        self.assertEqual([i['tarea'].titulo for i in items], ['Propia'])

    def test_sin_tareas(self):
        from app.services.evidencias_aprendiz import tareas_del_aprendiz
        self.assertEqual(tareas_del_aprendiz(self.ficha.id, self.aprendiz.id), [])
