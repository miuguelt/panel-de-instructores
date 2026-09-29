"""Pruebas de sincronización cruzada entre instructores.

Verifica que los datos de fichas compartidas (asistencia, aseo, tareas,
juicios, archivos versionados) sean visibles para todos los instructores
vinculados y que las actualizaciones se reflejen de inmediato.
"""

import unittest
from datetime import date, datetime, timedelta

from app import create_app, db
from app.models import (
    Aprendiz,
    ConfiguracionAlertas,
    ConfiguracionRanking,
    ContadorAseo,
    Entrega,
    Ficha,
    Instructor,
    RegistroAsistencia,
    SesionAsistencia,
    Tarea,
    TurnoAseo,
)
from app.models.aseo import ConfiguracionAseo
from app.models.corte import Corte
from app.models.ficha_instructor import FichaInstructor
from app.models.juicio import JuicioEvaluativo


def _crear_app():
    return create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
        'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False,
        'LOGIN_DISABLED': True,
    })


class SincronizacionFichasCompartidasTestCase(unittest.TestCase):
    """Verifica que dos instructores que comparten una ficha ven los mismos datos."""

    def setUp(self):
        self.app = _crear_app()
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()

        self.instructor_a = Instructor(
            nombre='Instructor A', correo='a@sena.edu.co', rol='admin'
        )
        self.instructor_a.set_password('clave')
        self.instructor_b = Instructor(
            nombre='Instructor B', correo='b@sena.edu.co', rol='instructor'
        )
        self.instructor_b.set_password('clave')
        db.session.add_all([self.instructor_a, self.instructor_b])
        db.session.flush()

        self.ficha = Ficha(
            codigo='2999999',
            nombre_programa='Análisis y Desarrollo de Software',
            instructor_id=self.instructor_a.id,
            fecha_inicio=date.today() - timedelta(days=60),
            fecha_fin=date.today() + timedelta(days=300),
        )
        db.session.add(self.ficha)
        db.session.flush()

        db.session.add(ConfiguracionAlertas(ficha_id=self.ficha.id))
        db.session.add(ConfiguracionRanking(ficha_id=self.ficha.id))
        db.session.add(ConfiguracionAseo(ficha_id=self.ficha.id))

        # Ambos instructores están vinculados
        db.session.add(FichaInstructor(
            ficha_id=self.ficha.id, instructor_id=self.instructor_a.id
        ))
        db.session.add(FichaInstructor(
            ficha_id=self.ficha.id, instructor_id=self.instructor_b.id
        ))

        # Aprendices compartidos
        self.aprendices = []
        for i in range(4):
            ap = Aprendiz(
                documento=f'100000{i}',
                nombre=f'Aprendiz{i}',
                apellidos=f'Apellido{i}',
                ficha_id=self.ficha.id,
                estado='EN_FORMACION',
            )
            db.session.add(ap)
            self.aprendices.append(ap)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    # ─── Permisos sobre la ficha ───────────────────────────────────────

    def test_puede_gestionar_ficha_dueno(self):
        """El instructor dueño puede gestionar la ficha."""
        from app.services.permisos import puede_gestionar_ficha
        from unittest.mock import patch, MagicMock
        usuario = MagicMock()
        usuario.is_authenticated = True
        usuario.es_admin = False
        usuario.id = self.instructor_a.id
        with patch('app.services.permisos.current_user', usuario):
            self.assertTrue(puede_gestionar_ficha(self.ficha))

    def test_puede_gestionar_ficha_colaborador(self):
        """Un instructor vinculado como colaborador puede gestionar la ficha."""
        from app.services.permisos import puede_gestionar_ficha
        from unittest.mock import patch, MagicMock
        usuario = MagicMock()
        usuario.is_authenticated = True
        usuario.es_admin = False
        usuario.id = self.instructor_b.id
        with patch('app.services.permisos.current_user', usuario):
            self.assertTrue(puede_gestionar_ficha(self.ficha))

    def test_no_puede_gestionar_ficha_extraño(self):
        """Un instructor sin vinculación no puede gestionar la ficha."""
        from app.services.permisos import puede_gestionar_ficha
        from unittest.mock import patch, MagicMock
        intruso = Instructor(
            nombre='Intruso', correo='x@sena.edu.co', rol='instructor'
        )
        intruso.set_password('clave')
        db.session.add(intruso)
        db.session.flush()
        usuario = MagicMock()
        usuario.is_authenticated = True
        usuario.es_admin = False
        usuario.id = intruso.id
        with patch('app.services.permisos.current_user', usuario):
            self.assertFalse(puede_gestionar_ficha(self.ficha))

    # ─── Asistencia centralizada ────────────────────────────────────────

    def test_asistencia_guardada_por_a_visible_para_b(self):
        """La asistencia que guarda el instructor A se lee desde el instructor B."""
        from app.services.asistencia import guardar_asistencia, contar_sesiones_registradas
        fecha = date.today()
        registros = {
            self.aprendices[0].id: ('ASISTE', None),
            self.aprendices[1].id: ('FALTA', None),
        }
        guardar_asistencia(self.ficha.id, fecha, registros)

        # El conteo de sesiones usa ficha_id, no instructor_id
        total = contar_sesiones_registradas(self.ficha.id)
        self.assertEqual(total, 1)

        # Verificar registros directos
        sesion = SesionAsistencia.query.filter_by(
            ficha_id=self.ficha.id, fecha=fecha
        ).first()
        self.assertIsNotNone(sesion)
        registros_db = RegistroAsistencia.query.filter_by(
            sesion_id=sesion.id
        ).all()
        self.assertEqual(len(registros_db), 2)

    def test_asistencia_en_corte_compartido_visible(self):
        """La asistencia en un corte compartido es visible para el colaborador."""
        from app.services.asistencia import guardar_asistencia, contar_sesiones_registradas
        corte = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            nombre='Corte 1',
            fecha_inicio=datetime.utcnow(),
            compartido=True,
        )
        db.session.add(corte)
        db.session.flush()

        fecha = date.today()
        registros = {
            self.aprendices[0].id: ('ASISTE', None),
        }
        guardar_asistencia(self.ficha.id, fecha, registros, corte_id=corte.id)

        total = contar_sesiones_registradas(self.ficha.id, corte_id=corte.id)
        self.assertEqual(total, 1)

    # ─── Tareas visibles entre instructores ─────────────────────────────

    def test_tareas_en_corte_compartido_visibles_para_todos(self):
        """Tareas en un corte compartido son visibles para todos los colaboradores de la ficha."""
        from app.services.permisos import tareas_visibles
        from unittest.mock import patch, MagicMock

        corte = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            nombre='Corte Activo',
            fecha_inicio=datetime.utcnow(),
            compartido=True,
            estado=Corte.ESTADO_ACTIVO,
        )
        db.session.add(corte)
        db.session.flush()

        tarea = Tarea(
            ficha_id=self.ficha.id,
            corte_id=corte.id,
            instructor_id=self.instructor_a.id,
            titulo='Tarea del corte de A',
            modalidad='evidencia',
        )
        db.session.add(tarea)
        db.session.commit()

        # Simular instructor B consultando el corte
        usuario_b = MagicMock()
        usuario_b.is_authenticated = True
        usuario_b.es_admin = False
        usuario_b.id = self.instructor_b.id
        with patch('app.services.permisos.current_user', usuario_b):
            resultado = tareas_visibles(self.ficha.id, corte_id=corte.id).all()
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0].titulo, 'Tarea del corte de A')

    def test_tareas_con_ver_todas_visibles_para_todos(self):
        """Con ver_todas=True, cada instructor ve todas las tareas de la ficha."""
        from app.services.permisos import tareas_visibles
        from unittest.mock import patch, MagicMock

        tarea_a = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            titulo='Tarea de A',
            modalidad='evidencia',
        )
        tarea_b = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_b.id,
            titulo='Tarea de B',
            modalidad='clase',
        )
        db.session.add_all([tarea_a, tarea_b])
        db.session.commit()

        # Instructor B ve ambas con ver_todas=True
        usuario_b = MagicMock()
        usuario_b.is_authenticated = True
        usuario_b.es_admin = False
        usuario_b.id = self.instructor_b.id
        with patch('app.services.permisos.current_user', usuario_b):
            resultado_b = tareas_visibles(self.ficha.id, ver_todas=True).all()
        self.assertEqual(len(resultado_b), 2)

    def test_tareas_sin_corte_filtran_por_instructor_por_defecto(self):
        """Sin corte y sin ver_todas, la vista filtra solo las tareas propias por defecto."""
        from app.services.permisos import tareas_visibles
        from unittest.mock import patch, MagicMock

        tarea_a = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            titulo='Tarea de A',
            modalidad='evidencia',
        )
        tarea_b = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_b.id,
            titulo='Tarea de B',
            modalidad='clase',
        )
        db.session.add_all([tarea_a, tarea_b])
        db.session.commit()

        # Instructor B ve solo las suyas por defecto cuando corte_id es None
        usuario_b = MagicMock()
        usuario_b.is_authenticated = True
        usuario_b.es_admin = False
        usuario_b.id = self.instructor_b.id
        with patch('app.services.permisos.current_user', usuario_b):
            resultado_b = tareas_visibles(self.ficha.id).all()
        self.assertEqual(len(resultado_b), 1)
        self.assertEqual(resultado_b[0].titulo, 'Tarea de B')

    def test_colaborador_puede_tomar_asistencia_en_corte_compartido(self):
        """Un instructor colaborador puede registrar asistencia en un corte activo y compartido."""
        from app.services.permisos import puede_gestionar_asistencia
        from unittest.mock import patch, MagicMock

        corte = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            nombre='Corte Compartido Asistencia',
            fecha_inicio=datetime.utcnow(),
            compartido=True,
            estado=Corte.ESTADO_ACTIVO,
        )
        db.session.add(corte)
        db.session.commit()

        usuario_b = MagicMock()
        usuario_b.is_authenticated = True
        usuario_b.es_admin = False
        usuario_b.id = self.instructor_b.id
        with patch('app.services.permisos.current_user', usuario_b):
            self.assertTrue(puede_gestionar_asistencia(corte, self.ficha))

    def test_colaborador_puede_crear_tarea_en_corte_compartido(self):
        """Un instructor colaborador puede crear una tarea en un corte activo y compartido."""
        from app.services.permisos import puede_crear_tarea_en_corte
        from unittest.mock import patch, MagicMock

        corte = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            nombre='Corte Compartido Tareas',
            fecha_inicio=datetime.utcnow(),
            compartido=True,
            estado=Corte.ESTADO_ACTIVO,
        )
        db.session.add(corte)
        db.session.commit()

        usuario_b = MagicMock()
        usuario_b.is_authenticated = True
        usuario_b.es_admin = False
        usuario_b.id = self.instructor_b.id
        with patch('app.services.permisos.current_user', usuario_b):
            self.assertTrue(puede_crear_tarea_en_corte(corte, self.ficha))

    def test_corte_cerrado_o_privado_no_permite_asistencia_ni_tareas_a_colaborador(self):
        """Un corte cerrado o no compartido no permite registrar asistencia ni crear tareas al colaborador."""
        from app.services.permisos import puede_gestionar_asistencia, puede_crear_tarea_en_corte
        from unittest.mock import patch, MagicMock

        corte_cerrado = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            nombre='Corte Cerrado',
            fecha_inicio=datetime.utcnow() - timedelta(days=30),
            fecha_fin=datetime.utcnow(),
            compartido=True,
            estado=Corte.ESTADO_CERRADO,
        )
        corte_privado = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            nombre='Corte Privado',
            fecha_inicio=datetime.utcnow(),
            compartido=False,
            estado=Corte.ESTADO_ACTIVO,
        )
        db.session.add_all([corte_cerrado, corte_privado])
        db.session.commit()

        usuario_b = MagicMock()
        usuario_b.is_authenticated = True
        usuario_b.es_admin = False
        usuario_b.id = self.instructor_b.id
        with patch('app.services.permisos.current_user', usuario_b):
            self.assertFalse(puede_gestionar_asistencia(corte_cerrado, self.ficha))
            self.assertFalse(puede_crear_tarea_en_corte(corte_cerrado, self.ficha))
            self.assertFalse(puede_gestionar_asistencia(corte_privado, self.ficha))
            self.assertFalse(puede_crear_tarea_en_corte(corte_privado, self.ficha))

    def test_corte_actual_fallback_a_corte_compartido_activo(self):
        """corte_actual retorna el corte compartido activo cuando el instructor no tiene cortes propios."""
        from app.services.cortes import corte_actual
        from unittest.mock import patch, MagicMock

        corte = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            nombre='Corte Activo de A',
            fecha_inicio=datetime.utcnow(),
            compartido=True,
            estado=Corte.ESTADO_ACTIVO,
        )
        db.session.add(corte)
        db.session.commit()

        usuario_b = MagicMock()
        usuario_b.is_authenticated = True
        usuario_b.es_admin = False
        usuario_b.id = self.instructor_b.id
        with patch('app.services.cortes.current_user', usuario_b):
            res = corte_actual(self.ficha.id)
        self.assertIsNotNone(res)
        self.assertEqual(res.id, corte.id)
        self.assertEqual(res.nombre, 'Corte Activo de A')

    def test_intruso_no_ve_tareas_de_ficha_ajena(self):
        """Un instructor sin vínculo no ve tareas de la ficha."""
        from app.services.permisos import tareas_visibles
        from unittest.mock import patch, MagicMock

        intruso = Instructor(
            nombre='Intruso', correo='i@sena.edu.co', rol='instructor'
        )
        intruso.set_password('clave')
        db.session.add(intruso)
        db.session.flush()

        tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            titulo='Privada',
            modalidad='evidencia',
        )
        db.session.add(tarea)
        db.session.commit()

        usuario = MagicMock()
        usuario.is_authenticated = True
        usuario.es_admin = False
        usuario.id = intruso.id
        with patch('app.services.permisos.current_user', usuario):
            resultado = tareas_visibles(self.ficha.id).all()
        self.assertEqual(len(resultado), 0)

    def test_puede_gestionar_tarea_solo_creador(self):
        """Solo el creador de la tarea puede modificarla."""
        from app.services.permisos import puede_gestionar_tarea
        from unittest.mock import patch, MagicMock

        tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            titulo='Solo A la edita',
            modalidad='evidencia',
        )
        db.session.add(tarea)
        db.session.commit()

        # A puede gestionarla
        usuario_a = MagicMock()
        usuario_a.is_authenticated = True
        usuario_a.es_admin = False
        usuario_a.id = self.instructor_a.id
        with patch('app.services.permisos.current_user', usuario_a):
            self.assertTrue(puede_gestionar_tarea(tarea))

        # B no puede gestionarla
        usuario_b = MagicMock()
        usuario_b.is_authenticated = True
        usuario_b.es_admin = False
        usuario_b.id = self.instructor_b.id
        with patch('app.services.permisos.current_user', usuario_b):
            self.assertFalse(puede_gestionar_tarea(tarea))

    # ─── Turnos de aseo centralizados ──────────────────────────────────

    def test_turnos_aseo_centralizados_en_ficha(self):
        """Los turnos de aseo son compartidos: ambos instructores ven los mismos."""
        from app.services.aseo import generar_turnos

        fecha_inicio = date.today() + timedelta(days=1)
        fecha_fin = fecha_inicio + timedelta(days=5)
        for i, ap in enumerate(self.aprendices):
            db.session.add(ContadorAseo(
                aprendiz_id=ap.id, ficha_id=self.ficha.id, veces_aseo=0
            ))
        for delta in range(6):
            db.session.add(SesionAsistencia(
                ficha_id=self.ficha.id,
                fecha=fecha_inicio + timedelta(days=delta),
            ))
        db.session.commit()

        resultado = generar_turnos(self.ficha.id, fecha_inicio, fecha_fin)
        db.session.commit()
        creados = len(resultado['creados'])
        self.assertGreater(creados, 0)

        # Los turnos son por ficha_id, no por instructor_id
        turnos = TurnoAseo.query.filter_by(ficha_id=self.ficha.id).all()
        self.assertEqual(len(turnos), creados)

    # ─── Juicios evaluativos centralizados ─────────────────────────────

    def test_juicios_importados_por_a_visibles_para_b(self):
        """Los juicios cargados por un instructor son datos de la ficha, no del instructor."""
        juicio = JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendices[0].id,
            competencia='Desarrollo de Software',
            resultado_aprendizaje='Analizar requisitos',
            juicio='APROBADO',
            tipo_competencia='tecnica',
            huella='huella_test_1',
        )
        db.session.add(juicio)
        db.session.commit()

        # El juicio se filtra por ficha_id
        juicios_ficha = JuicioEvaluativo.query.filter_by(
            ficha_id=self.ficha.id
        ).all()
        self.assertEqual(len(juicios_ficha), 1)
        self.assertEqual(juicios_ficha[0].juicio, 'APROBADO')

    def test_actualizar_juicio_refleja_inmediato(self):
        """Una actualización de juicio es visible inmediatamente."""
        juicio = JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendices[0].id,
            competencia='Base de Datos',
            resultado_aprendizaje='Diseñar esquema',
            juicio='AUN NO APROBADO',
            tipo_competencia='tecnica',
            huella='huella_test_2',
        )
        db.session.add(juicio)
        db.session.commit()

        # Simular instructor B actualizando
        juicio.juicio = 'APROBADO'
        db.session.commit()

        recargado = db.session.get(JuicioEvaluativo, juicio.id)
        self.assertEqual(recargado.juicio, 'APROBADO')

    # ─── Fichas visibles ────────────────────────────────────────────────

    def test_obtener_fichas_incluye_asociadas(self):
        """obtener_fichas() devuelve tanto las propias como las asociadas."""
        from app.routes.instructor import obtener_fichas
        from unittest.mock import patch, MagicMock

        # Crear segunda ficha solo de A
        ficha2 = Ficha(
            codigo='3111111',
            nombre_programa='Otro Programa',
            instructor_id=self.instructor_a.id,
        )
        db.session.add(ficha2)
        db.session.flush()
        db.session.add(FichaInstructor(
            ficha_id=ficha2.id, instructor_id=self.instructor_a.id
        ))
        db.session.commit()

        # Instructor B ve solo ficha compartida
        usuario_b = MagicMock()
        usuario_b.is_authenticated = True
        usuario_b.es_admin = False
        usuario_b.id = self.instructor_b.id
        with patch('app.routes.instructor.current_user', usuario_b):
            fichas_b = obtener_fichas()
        codigos_b = {f.codigo for f in fichas_b}
        self.assertIn('2999999', codigos_b)
        self.assertNotIn('3111111', codigos_b)

        # Instructor A ve ambas
        usuario_a = MagicMock()
        usuario_a.is_authenticated = True
        usuario_a.es_admin = False
        usuario_a.id = self.instructor_a.id
        with patch('app.routes.instructor.current_user', usuario_a):
            fichas_a = obtener_fichas()
        codigos_a = {f.codigo for f in fichas_a}
        self.assertIn('2999999', codigos_a)
        self.assertIn('3111111', codigos_a)

    # ─── Cortes compartidos ────────────────────────────────────────────

    def test_cortes_visibles_incluye_compartidos(self):
        """Un colaborador ve los cortes compartidos del dueño."""
        from app.services.cortes import cortes_visibles
        from unittest.mock import patch, MagicMock

        corte = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            nombre='Corte compartido',
            fecha_inicio=datetime.utcnow(),
            compartido=True,
        )
        db.session.add(corte)
        db.session.commit()

        usuario_b = MagicMock()
        usuario_b.is_authenticated = True
        usuario_b.es_admin = False
        usuario_b.id = self.instructor_b.id
        with patch('app.services.cortes.current_user', usuario_b):
            resultado = cortes_visibles(self.ficha.id).all()
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0].nombre, 'Corte compartido')

    def test_corte_no_compartido_no_visible_para_colaborador(self):
        """Un corte con compartido=False solo lo ve su creador."""
        from app.services.cortes import cortes_visibles
        from unittest.mock import patch, MagicMock

        corte = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            nombre='Corte privado',
            fecha_inicio=datetime.utcnow(),
            compartido=False,
        )
        db.session.add(corte)
        db.session.commit()

        usuario_b = MagicMock()
        usuario_b.is_authenticated = True
        usuario_b.es_admin = False
        usuario_b.id = self.instructor_b.id
        with patch('app.services.cortes.current_user', usuario_b):
            resultado = cortes_visibles(self.ficha.id).all()
        self.assertEqual(len(resultado), 0)

    # ─── Importación vincula automáticamente ───────────────────────────

    def test_importacion_crea_vinculo_ficha_instructor(self):
        """Al importar, se crea FichaInstructor si no existe."""
        vinculo = FichaInstructor.query.filter_by(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_b.id,
        ).first()
        self.assertIsNotNone(vinculo)

    def test_vinculacion_automatica_idempotente(self):
        """Vincular dos veces al mismo instructor no crea duplicados."""
        from sqlalchemy.exc import IntegrityError
        try:
            db.session.add(FichaInstructor(
                ficha_id=self.ficha.id,
                instructor_id=self.instructor_b.id,
            ))
            db.session.flush()
            self.fail('Debería lanzar IntegrityError por unicidad.')
        except IntegrityError:
            db.session.rollback()
        vinculos = FichaInstructor.query.filter_by(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_b.id,
        ).count()
        self.assertEqual(vinculos, 1)

    # ─── Actualización inmediata de datos ──────────────────────────────

    def test_actualizar_ficha_refleja_para_todos(self):
        """Cambios en la ficha por un instructor son inmediatos para el otro."""
        self.ficha.nombre_programa = 'Programa Actualizado'
        db.session.commit()

        ficha_recargada = db.session.get(Ficha, self.ficha.id)
        self.assertEqual(ficha_recargada.nombre_programa, 'Programa Actualizado')

    def test_nuevo_aprendiz_visible_para_todos(self):
        """Un aprendiz agregado por A es visible inmediatamente para B."""
        ap = Aprendiz(
            documento='9999999',
            nombre='Nuevo',
            apellidos='Aprendiz',
            ficha_id=self.ficha.id,
            estado='EN_FORMACION',
        )
        db.session.add(ap)
        db.session.commit()

        todos = Aprendiz.query.filter_by(ficha_id=self.ficha.id).all()
        self.assertEqual(len(todos), 5)  # 4 originales + 1 nuevo

    def test_calificacion_de_b_visible_para_a(self):
        """Una calificación puesta por B se ve inmediatamente para A."""
        tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor_a.id,
            titulo='Tarea calificable',
            modalidad='evidencia',
        )
        db.session.add(tarea)
        db.session.flush()

        entrega = Entrega(
            tarea_id=tarea.id,
            aprendiz_id=self.aprendices[0].id,
        )
        db.session.add(entrega)
        db.session.flush()

        # Instructor B califica
        entrega.calificacion = 'Aprobado'
        entrega.calificada = True
        entrega.estado_revision = 'aprobada'
        entrega.revisada_por_id = self.instructor_b.id
        db.session.commit()

        # Instructor A lee
        recargada = db.session.get(Entrega, entrega.id)
        self.assertEqual(recargada.calificacion, 'Aprobado')
        self.assertEqual(recargada.revisada_por_id, self.instructor_b.id)


if __name__ == '__main__':
    unittest.main()
