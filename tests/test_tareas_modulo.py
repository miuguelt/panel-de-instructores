"""Pruebas automatizadas para el módulo de tareas, agrupación por instructor y barra de tiempo."""

import tempfile
import unittest
from datetime import datetime, timedelta

from app import create_app, db
from app.models.aprendiz import Aprendiz
from app.models.corte import Corte
from app.models.ficha import Ficha
from app.models.instructor import Instructor
from app.models.tarea import Entrega, Tarea
from app.services.tareas import (
    agrupar_tareas_por_corte_e_instructor,
    agrupar_tareas_por_instructor,
    calcular_progreso_tiempo_tarea,
    formatear_tiempo_humano,
    obtener_estadisticas_entregas_tareas,
)


class TareasProgresoYTiempoTestCase(unittest.TestCase):
    """Pruebas unitarias para formateo y cálculo de tiempo restante/porcentaje."""

    def test_formatear_tiempo_humano_dias(self):
        # 1 día exacto
        self.assertEqual(formatear_tiempo_humano(86400), '1 día')
        # Varios días con horas
        self.assertEqual(formatear_tiempo_humano(176400), '2 días y 1 hora')
        # Varios días con varias horas
        self.assertEqual(formatear_tiempo_humano(180000), '2 días y 2 horas')
        # Días sin horas adicionales
        self.assertEqual(formatear_tiempo_humano(172800), '2 días')

    def test_formatear_tiempo_humano_horas(self):
        # 1 hora exacta
        self.assertEqual(formatear_tiempo_humano(3600), '1 hora')
        # Horas con minutos
        self.assertEqual(formatear_tiempo_humano(7320), '2 horas y 2 min')
        # 3 horas exactas
        self.assertEqual(formatear_tiempo_humano(10800), '3 horas')

    def test_formatear_tiempo_humano_minutos_y_segundos(self):
        # 1 minuto
        self.assertEqual(formatear_tiempo_humano(60), '1 minuto')
        # Varios minutos
        self.assertEqual(formatear_tiempo_humano(300), '5 minutos')
        # Menos de 60 segundos o valores no positivos
        self.assertEqual(formatear_tiempo_humano(45), 'menos de un minuto')
        self.assertEqual(formatear_tiempo_humano(0), 'menos de un minuto')
        self.assertEqual(formatear_tiempo_humano(-10), 'menos de un minuto')

    def test_calcular_progreso_sin_fecha_limite(self):
        tarea = Tarea(titulo='Sin límite', fecha_limite=None, creada_en=datetime(2026, 10, 1))
        progreso = calcular_progreso_tiempo_tarea(tarea, ahora=datetime(2026, 10, 2))
        self.assertEqual(progreso['porcentaje'], 0)
        self.assertEqual(progreso['porcentaje_restante'], 100)
        self.assertEqual(progreso['estado'], 'sin_limite')
        self.assertTrue(progreso['sin_limite'])
        self.assertFalse(progreso['vencida'])
        self.assertIsNone(progreso['tiempo_restante_segundos'])
        self.assertIn('Sin fecha límite', progreso['texto_tiempo'])

    def test_calcular_progreso_tarea_vencida(self):
        creada = datetime(2026, 10, 1, 8, 0)
        limite = datetime(2026, 10, 3, 18, 0)
        ahora = datetime(2026, 10, 4, 18, 0)  # 1 día después del vencimiento
        tarea = Tarea(titulo='Vencida', creada_en=creada, fecha_limite=limite)
        progreso = calcular_progreso_tiempo_tarea(tarea, ahora=ahora)
        self.assertEqual(progreso['porcentaje'], 100)
        self.assertEqual(progreso['porcentaje_restante'], 0)
        self.assertEqual(progreso['estado'], 'vencida')
        self.assertTrue(progreso['vencida'])
        self.assertIn('Vencida hace', progreso['texto_tiempo'])

    def test_calcular_progreso_creada_en_el_futuro(self):
        creada = datetime(2026, 10, 5, 8, 0)
        limite = datetime(2026, 10, 10, 18, 0)
        ahora = datetime(2026, 10, 2, 8, 0)  # Antes de creada_en
        tarea = Tarea(titulo='Futura', creada_en=creada, fecha_limite=limite)
        progreso = calcular_progreso_tiempo_tarea(tarea, ahora=ahora)
        self.assertEqual(progreso['porcentaje'], 0)
        self.assertEqual(progreso['porcentaje_restante'], 100)
        self.assertEqual(progreso['estado'], 'normal')
        self.assertFalse(progreso['vencida'])
        self.assertIn('Quedan', progreso['texto_tiempo'])

    def test_calcular_progreso_fecha_limite_inconsistente(self):
        # Límite anterior o igual a la creación
        creada = datetime(2026, 10, 5, 8, 0)
        limite = datetime(2026, 10, 5, 8, 0)
        ahora = datetime(2026, 10, 5, 7, 0)
        tarea = Tarea(titulo='Inconsistente', creada_en=creada, fecha_limite=limite)
        progreso = calcular_progreso_tiempo_tarea(tarea, ahora=ahora)
        self.assertEqual(progreso['porcentaje'], 100)
        self.assertEqual(progreso['estado'], 'vencida')
        self.assertTrue(progreso['vencida'])

    def test_calcular_progreso_estados_normal_atencion_urgente(self):
        creada = datetime(2026, 10, 1, 0, 0)
        limite = datetime(2026, 10, 11, 0, 0)  # 10 días de plazo = 240 horas

        tarea = Tarea(titulo='En curso', creada_en=creada, fecha_limite=limite)

        # 1. Estado normal: transcurridos 2 días (20%), quedan 8 días
        ahora_normal = datetime(2026, 10, 3, 0, 0)
        p_normal = calcular_progreso_tiempo_tarea(tarea, ahora=ahora_normal)
        self.assertEqual(p_normal['porcentaje'], 20)
        self.assertEqual(p_normal['porcentaje_restante'], 80)
        self.assertEqual(p_normal['estado'], 'normal')
        self.assertIn('Quedan 8 días', p_normal['texto_tiempo'])

        # 2. Estado atención: transcurridos 7 días (70%), quedan 3 días
        ahora_atencion = datetime(2026, 10, 8, 0, 0)
        p_atencion = calcular_progreso_tiempo_tarea(tarea, ahora=ahora_atencion)
        self.assertEqual(p_atencion['porcentaje'], 70)
        self.assertEqual(p_atencion['estado'], 'atencion')

        # 3. Estado urgente: transcurridos 9 días y 12 horas (95%), quedan 12 horas (< 24h)
        ahora_urgente = datetime(2026, 10, 10, 12, 0)
        p_urgente = calcular_progreso_tiempo_tarea(tarea, ahora=ahora_urgente)
        self.assertEqual(p_urgente['porcentaje'], 95)
        self.assertEqual(p_urgente['estado'], 'urgente')
        self.assertIn('12 horas', p_urgente['texto_tiempo'])


class TareasAgrupacionTestCase(unittest.TestCase):
    """Pruebas de agrupación por instructor y corte."""

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

        self.instructor_1 = Instructor(nombre='Carlos Pérez', correo='carlos@sena.edu.co')
        self.instructor_1.set_password('clave123')
        self.instructor_2 = Instructor(nombre='Beatriz Gómez', correo='beatriz@sena.edu.co')
        self.instructor_2.set_password('clave123')
        self.ficha = Ficha(
            codigo='9876543',
            codigo_ficha='9876543',
            nombre_programa='ADSO Tareas',
            instructor=self.instructor_1,
        )
        db.session.add_all([self.instructor_1, self.instructor_2, self.ficha])
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def test_obtener_estadisticas_entregas_tareas_vacia_y_con_datos(self):
        # Vacía
        self.assertEqual(obtener_estadisticas_entregas_tareas([]), {})

        # Con tareas y entregas
        aprendiz = Aprendiz(
            ficha_id=self.ficha.id,
            nombre='Ana',
            apellidos='Silva',
            documento='111222',
        )
        db.session.add(aprendiz)
        db.session.flush()

        tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_1.id,
            titulo='Tarea con entregas',
        )
        db.session.add(tarea)
        db.session.flush()

        entrega_calificada = Entrega(
            tarea_id=tarea.id,
            aprendiz_id=aprendiz.id,
            calificada=True,
            calificacion='4.5',
        )
        db.session.add(entrega_calificada)
        db.session.commit()

        stats = obtener_estadisticas_entregas_tareas([tarea.id])
        self.assertIn(tarea.id, stats)
        self.assertEqual(stats[tarea.id]['total'], 1)
        self.assertEqual(stats[tarea.id]['calificadas'], 1)
        self.assertEqual(stats[tarea.id]['pendientes'], 0)

    def test_agrupar_tareas_por_instructor_ordena_actual_primero(self):
        t1 = Tarea(
            ficha_id=self.ficha.id,
            creador=self.instructor_2,
            titulo='Tarea de Beatriz',
            creada_en=datetime(2026, 10, 1),
            fecha_limite=datetime(2026, 10, 10),
        )
        t2 = Tarea(
            ficha_id=self.ficha.id,
            creador=self.instructor_1,
            titulo='Tarea de Carlos',
            creada_en=datetime(2026, 10, 1),
            fecha_limite=datetime(2026, 10, 5),
        )
        db.session.add_all([t1, t2])
        db.session.commit()

        # Si el usuario actual es Carlos (instructor_1), Carlos debe aparecer primero
        grupos = agrupar_tareas_por_instructor(
            [t1, t2],
            current_user_id=self.instructor_1.id,
            ahora=datetime(2026, 10, 2),
        )
        self.assertEqual(len(grupos), 2)
        self.assertEqual(grupos[0]['instructor'].id, self.instructor_1.id)
        self.assertTrue(grupos[0]['es_actual'])
        self.assertEqual(grupos[0]['total_tareas'], 1)
        self.assertEqual(grupos[1]['instructor'].id, self.instructor_2.id)
        self.assertFalse(grupos[1]['es_actual'])

    def test_modelo_tarea_propiedad_progreso_tiempo_y_resumen_entregas(self):
        tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_1.id,
            titulo='Tarea Modelo Test',
            creada_en=datetime(2026, 10, 1),
            fecha_limite=datetime(2026, 10, 8),
        )
        db.session.add(tarea)
        db.session.commit()

        # Evaluar propiedad calculada
        progreso = tarea.progreso_tiempo
        self.assertIn('porcentaje', progreso)
        self.assertIn('estado', progreso)

        # Evaluar resumen entregas inyectado
        tarea.stats_entregas = {'total': 5, 'calificadas': 3, 'pendientes': 2}
        self.assertEqual(tarea.resumen_entregas['total'], 5)

        # Evaluar fallback sin stats inyectadas
        delattr(tarea, 'stats_entregas')
        self.assertEqual(tarea.resumen_entregas['total'], 0)


class TareasWebRutaTestCase(unittest.TestCase):
    """Pruebas de la ruta web /instructor/fichas/<id>/tareas con la interfaz mejorada."""

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

        self.cliente = self.app.test_client()
        self.instructor = Instructor(
            nombre='Instructor Docente',
            correo='docente@sena.edu.co',
        )
        self.instructor.set_password('clave123')
        self.colaborador = Instructor(
            nombre='Instructor Auxiliar',
            correo='auxiliar@sena.edu.co',
        )
        self.colaborador.set_password('clave123')

        self.ficha = Ficha(
            codigo='777888',
            codigo_ficha='777888',
            nombre_programa='Tecnología en Desarrollo',
            instructor=self.instructor,
        )
        db.session.add_all([self.instructor, self.colaborador, self.ficha])
        db.session.commit()

        # Tarea 1 asignada por el titular
        self.t1 = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            titulo='Arquitectura Hexagonal',
            descripcion='Diseñar las capas del servicio.',
            creada_en=datetime.utcnow() - timedelta(days=2),
            fecha_limite=datetime.utcnow() + timedelta(days=4),
            modalidad='evidencia',
        )
        # Tarea 2 asignada por el colaborador
        self.t2 = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.colaborador.id,
            titulo='Pruebas Unitarias Automatizadas',
            descripcion='Escribir suites de integración.',
            creada_en=datetime.utcnow() - timedelta(days=1),
            fecha_limite=datetime.utcnow() + timedelta(days=2),
            modalidad='clase',
        )
        db.session.add_all([self.t1, self.t2])
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def _login(self, instructor):
        with self.cliente.session_transaction() as sess:
            sess['_user_id'] = str(instructor.id)
            sess['_fresh'] = True

    def test_ruta_tareas_muestra_metricas_bento_y_barra_de_tiempo(self):
        self._login(self.instructor)
        respuesta = self.cliente.get(f'/instructor/fichas/{self.ficha.id}/tareas?filtro_instructor=todas')
        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.get_data(as_text=True)

        # 1. Comprobar métricas Bento
        self.assertIn('metricas-bento-grid', cuerpo)
        self.assertIn('Total Tareas', cuerpo)
        self.assertIn('En Plazo', cuerpo)

        # 2. Comprobar agrupación por instructor
        self.assertIn('Instructor Docente', cuerpo)
        self.assertIn('Instructor Auxiliar', cuerpo)
        self.assertIn('instructores-tablero', cuerpo)

        # 3. Comprobar barra de porcentaje de tiempo y accesibilidad
        self.assertIn('role="progressbar"', cuerpo)
        self.assertIn('aria-valuenow=', cuerpo)
        self.assertIn('transcurrido', cuerpo)
        self.assertIn('barra-tiempo-track', cuerpo)
        self.assertIn('barra-tiempo-fill', cuerpo)

        # 4. Comprobar buscador interactivo
        self.assertIn('busqueda-tareas', cuerpo)


if __name__ == '__main__':
    unittest.main()
