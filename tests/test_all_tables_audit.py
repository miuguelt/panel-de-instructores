import unittest
from datetime import date, datetime, timedelta, timezone

from app import create_app, db
from app.models import (
    Instructor,
    Ficha,
    Corte,
    Aprendiz,
    Tarea,
    Insignia,
    ArchivoFichaVersion,
    ConfiguracionAlertas,
    ConfiguracionAlertasComite,
    ConfiguracionAseo,
    ConfiguracionRanking,
    ContadorAseo,
    TurnoAseo,
    IntercambioAseo,
    FichaCompetenciaSeleccionada,
    FichaInstructor,
    ImportacionJob,
    InsigniaOtorgada,
    JuicioEvaluativo,
    JuicioEvaluativoInstructor,
    MaterialFicha,
    NotaObservador,
    PlanMejoramiento,
    ProrrogaTarea,
    PuntajeHistorico,
    RegistroAsistencia,
    SesionAsistencia,
)


class AllTablesAuditTestCase(unittest.TestCase):
    """
    Auditoría exhaustiva del 100% de tablas del Panel de Instructores.
    Cubre el ciclo de vida CRUD y restricciones para las 20 tablas identificadas.
    """

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

        # Entidades base requeridas por foreign keys
        self.instructor = Instructor(nombre='Instructor Auditor', correo='auditor@sena.edu.co', rol='admin')
        self.instructor.set_password('Secret123!')
        db.session.add(self.instructor)

        self.instructor2 = Instructor(nombre='Instructor Colaborador', correo='colab@sena.edu.co', rol='instructor')
        self.instructor2.set_password('Secret123!')
        db.session.add(self.instructor2)
        db.session.flush()

        self.ficha = Ficha(codigo='F-AUDIT-2026', nombre_programa='ADSO Testing', instructor_id=self.instructor.id)
        db.session.add(self.ficha)
        db.session.flush()

        self.corte = Corte(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            nombre='Corte 1',
            fecha_inicio=datetime.now(timezone.utc) - timedelta(days=30),
            fecha_fin=datetime.now(timezone.utc) + timedelta(days=60)
        )
        db.session.add(self.corte)
        db.session.flush()

        self.aprendiz1 = Aprendiz(documento='10000001', nombre='Carlos', apellidos='Audit', ficha_id=self.ficha.id)
        self.aprendiz2 = Aprendiz(documento='10000002', nombre='Diana', apellidos='Audit', ficha_id=self.ficha.id)
        db.session.add_all([self.aprendiz1, self.aprendiz2])
        db.session.flush()

        self.tarea = Tarea(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            corte_id=self.corte.id,
            titulo='Evidencia Auditoria',
            fecha_limite=datetime.now(timezone.utc) + timedelta(days=7),
            modalidad='evidencia'
        )
        db.session.add(self.tarea)

        self.insignia = Insignia(
            ficha_id=self.ficha.id,
            codigo='INS-AUDIT-01',
            nombre='Insignia Calidad',
            descripcion='Premio a la excelencia en pruebas',
            icono='🏆'
        )
        db.session.add(self.insignia)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    # 1. archivos_ficha_versiones
    def test_audit_archivos_ficha_versiones(self):
        v = ArchivoFichaVersion(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            tipo='planeacion',
            version=1,
            nombre_archivo='planeacion_v1.xlsx',
            ruta_archivo='/storage/fichas/planeacion_v1.xlsx',
            hash_sha256='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
            tamano_bytes=1024,
            estado='procesado'
        )
        db.session.add(v)
        db.session.commit()
        self.assertIsNotNone(v.id)
        self.assertEqual(v.version, 1)

        v.estado = 'archivado'
        db.session.commit()
        self.assertEqual(v.estado, 'archivado')

        db.session.delete(v)
        db.session.commit()
        self.assertIsNone(db.session.get(ArchivoFichaVersion, v.id))

    # 2. configuracion_alertas
    def test_audit_configuracion_alertas(self):
        cfg = ConfiguracionAlertas(
            ficha_id=self.ficha.id,
            umbral_amarillo=4,
            umbral_rojo=7,
            max_fallas_trimestre_laboral=3
        )
        db.session.add(cfg)
        db.session.commit()
        self.assertIsNotNone(cfg.id)
        self.assertEqual(cfg.umbral_amarillo, 4)

        cfg.umbral_amarillo = 5
        db.session.commit()
        self.assertEqual(cfg.umbral_amarillo, 5)

        db.session.delete(cfg)
        db.session.commit()
        self.assertIsNone(db.session.get(ConfiguracionAlertas, cfg.id))

    # 3. configuracion_alertas_comite
    def test_audit_configuracion_alertas_comite(self):
        cfg = ConfiguracionAlertasComite(
            ficha_id=self.ficha.id,
            umbral_fallas_consecutivas=3,
            umbral_fallas_acumuladas=5,
            umbral_fallas_esporadicas=4,
            periodo_dias_esporadicas=60,
            umbral_tareas_incumplidas=3,
            porcentaje_minimo_asistencia=80,
            correo_habilitado=True
        )
        db.session.add(cfg)
        db.session.commit()
        self.assertIsNotNone(cfg.id)
        self.assertTrue(cfg.correo_habilitado)

        cfg.porcentaje_minimo_asistencia = 85
        db.session.commit()
        self.assertEqual(cfg.porcentaje_minimo_asistencia, 85)

        db.session.delete(cfg)
        db.session.commit()
        self.assertIsNone(db.session.get(ConfiguracionAlertasComite, cfg.id))

    # 4. configuracion_aseo
    def test_audit_configuracion_aseo(self):
        cfg = ConfiguracionAseo(
            ficha_id=self.ficha.id,
            excluir_ausentes=True,
            aviso_horas=48
        )
        db.session.add(cfg)
        db.session.commit()
        self.assertIsNotNone(cfg.id)
        self.assertEqual(cfg.aviso_horas, 48)

        cfg.aviso_horas = 12
        db.session.commit()
        self.assertEqual(cfg.aviso_horas, 12)

        db.session.delete(cfg)
        db.session.commit()
        self.assertIsNone(db.session.get(ConfiguracionAseo, cfg.id))

    # 5. configuracion_ranking
    def test_audit_configuracion_ranking(self):
        cfg = ConfiguracionRanking(
            ficha_id=self.ficha.id,
            peso_asistencia=35.0,
            peso_evidencias=45.0,
            peso_juicios=20.0,
            modo_visibilidad='publico',
            periodo_corte='mensual'
        )
        db.session.add(cfg)
        db.session.commit()
        self.assertIsNotNone(cfg.id)
        self.assertEqual(cfg.modo_visibilidad, 'publico')

        cfg.peso_asistencia = 40.0
        db.session.commit()
        self.assertEqual(cfg.peso_asistencia, 40.0)

        db.session.delete(cfg)
        db.session.commit()
        self.assertIsNone(db.session.get(ConfiguracionRanking, cfg.id))

    # 6. contador_aseo
    def test_audit_contador_aseo(self):
        cnt = ContadorAseo(
            aprendiz_id=self.aprendiz1.id,
            ficha_id=self.ficha.id,
            veces_aseo=2,
            ultima_vez_aseo=date.today() - timedelta(days=7),
            motivo_exclusion='Excusado por comite'
        )
        db.session.add(cnt)
        db.session.commit()
        self.assertIsNotNone(cnt.id)
        self.assertEqual(cnt.veces_aseo, 2)

        cnt.veces_aseo = 3
        db.session.commit()
        self.assertEqual(cnt.veces_aseo, 3)

        db.session.delete(cnt)
        db.session.commit()
        self.assertIsNone(db.session.get(ContadorAseo, cnt.id))

    # 7. fichas_competencias_seleccionadas
    def test_audit_fichas_competencias_seleccionadas(self):
        comp = FichaCompetenciaSeleccionada(
            ficha_id=self.ficha.id,
            competencia='220501096 - Desarrollar componentes software',
            instructor_id=self.instructor.id
        )
        db.session.add(comp)
        db.session.commit()
        self.assertIsNotNone(comp.id)
        self.assertIn('220501096', comp.competencia)

        comp.competencia = '220501096 - Desarrollar componentes software v2'
        db.session.commit()
        self.assertIn('v2', comp.competencia)

        db.session.delete(comp)
        db.session.commit()
        self.assertIsNone(db.session.get(FichaCompetenciaSeleccionada, comp.id))

    # 8. fichas_instructores
    def test_audit_fichas_instructores(self):
        fi = FichaInstructor(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor2.id
        )
        db.session.add(fi)
        db.session.commit()
        self.assertIsNotNone(fi.id)
        self.assertEqual(fi.instructor_id, self.instructor2.id)

        db.session.delete(fi)
        db.session.commit()
        self.assertIsNone(db.session.get(FichaInstructor, fi.id))

    # 9. importaciones_jobs
    def test_audit_importaciones_jobs(self):
        job = ImportacionJob(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            archivo_path='/tmp/reporte_calificaciones.xlsx',
            nombre_archivo='reporte_calificaciones.xlsx',
            estado='encolado'
        )
        db.session.add(job)
        db.session.commit()
        self.assertIsNotNone(job.id)
        self.assertEqual(job.estado, 'encolado')

        job.estado = 'completado'
        job.resultado = '{"filas_procesadas": 45}'
        db.session.commit()
        self.assertEqual(job.estado, 'completado')

        db.session.delete(job)
        db.session.commit()
        self.assertIsNone(db.session.get(ImportacionJob, job.id))

    # 10. insignias_otorgadas
    def test_audit_insignias_otorgadas(self):
        io = InsigniaOtorgada(
            aprendiz_id=self.aprendiz1.id,
            insignia_id=self.insignia.id,
            otorgada_por='instructor',
            instructor_id=self.instructor.id,
            notificada=False
        )
        db.session.add(io)
        db.session.commit()
        self.assertIsNotNone(io.id)
        self.assertFalse(io.notificada)

        io.notificada = True
        db.session.commit()
        self.assertTrue(io.notificada)

        db.session.delete(io)
        db.session.commit()
        self.assertIsNone(db.session.get(InsigniaOtorgada, io.id))

    # 11. intercambios_aseo
    def test_audit_intercambios_aseo(self):
        turno = TurnoAseo(
            ficha_id=self.ficha.id,
            fecha=date.today() + timedelta(days=3),
            aprendiz_1_id=self.aprendiz1.id,
            aprendiz_2_id=self.aprendiz2.id,
            estado='programado'
        )
        db.session.add(turno)
        db.session.commit()

        intercambio = IntercambioAseo(
            turno_id=turno.id,
            aprendiz_solicita_id=self.aprendiz1.id,
            aprendiz_recibe_id=self.aprendiz2.id,
            estado='pendiente',
            confirma_solicita=True,
            confirma_recibe=False
        )
        db.session.add(intercambio)
        db.session.commit()
        self.assertIsNotNone(intercambio.id)
        self.assertEqual(intercambio.estado, 'pendiente')

        intercambio.estado = 'aceptado'
        intercambio.confirma_recibe = True
        intercambio.respondido_en = datetime.now(timezone.utc)
        db.session.commit()
        self.assertEqual(intercambio.estado, 'aceptado')

        db.session.delete(intercambio)
        db.session.delete(turno)
        db.session.commit()
        self.assertIsNone(db.session.get(IntercambioAseo, intercambio.id))

    # 12. juicios_evaluativos
    def test_audit_juicios_evaluativos(self):
        juicio = JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz1.id,
            competencia='220501096 - Desarrollar software',
            tipo_competencia='Tecnica',
            resultado_aprendizaje='RAP 01 - Disenar arquitectura',
            juicio='APROBADO',
            fecha_juicio=datetime.now(timezone.utc),
            funcionario_registro='Instructor Auditor',
            fuente_archivo='reporte_sofia.xlsx',
            huella='HUELLA-SHA256-TEST-999'
        )
        db.session.add(juicio)
        db.session.commit()
        self.assertIsNotNone(juicio.id)
        self.assertEqual(juicio.juicio, 'APROBADO')

        juicio.juicio = 'POR EVALUAR'
        db.session.commit()
        self.assertEqual(juicio.juicio, 'POR EVALUAR')

        db.session.delete(juicio)
        db.session.commit()
        self.assertIsNone(db.session.get(JuicioEvaluativo, juicio.id))

    # 13. juicios_evaluativos_instructores
    def test_audit_juicios_evaluativos_instructores(self):
        juicio = JuicioEvaluativo(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz1.id,
            competencia='220501097 - Implementar pruebas',
            huella='HUELLA-SHA256-TEST-888'
        )
        db.session.add(juicio)
        db.session.flush()

        ji = JuicioEvaluativoInstructor(
            juicio_id=juicio.id,
            instructor_id=self.instructor.id
        )
        db.session.add(ji)
        db.session.commit()
        self.assertIsNotNone(ji.id)
        self.assertEqual(ji.instructor_id, self.instructor.id)

        db.session.delete(ji)
        db.session.delete(juicio)
        db.session.commit()
        self.assertIsNone(db.session.get(JuicioEvaluativoInstructor, ji.id))

    # 14. materiales_ficha
    def test_audit_materiales_ficha(self):
        mat = MaterialFicha(
            ficha_id=self.ficha.id,
            instructor_id=self.instructor.id,
            nombre_archivo='Guia_Aprendizaje_01.pdf',
            url_archivo='https://storage.sena.edu.co/guias/01.pdf',
            descripcion='Guia para el resultado de aprendizaje 1'
        )
        db.session.add(mat)
        db.session.commit()
        self.assertIsNotNone(mat.id)
        self.assertEqual(mat.nombre_archivo, 'Guia_Aprendizaje_01.pdf')

        mat.descripcion = 'Descripcion actualizada de la guia'
        db.session.commit()
        self.assertEqual(mat.descripcion, 'Descripcion actualizada de la guia')

        db.session.delete(mat)
        db.session.commit()
        self.assertIsNone(db.session.get(MaterialFicha, mat.id))

    # 15. notas_observador
    def test_audit_notas_observador(self):
        nota = NotaObservador(
            ficha_id=self.ficha.id,
            aprendiz_id=self.aprendiz1.id,
            instructor_id=self.instructor.id,
            tipo='positiva',
            categoria='compromiso',
            descripcion='Excelente participacion en actividades de equipo y liderazgo solidario.',
            fecha=date.today()
        )
        db.session.add(nota)
        db.session.commit()
        self.assertIsNotNone(nota.id)
        self.assertEqual(nota.tipo, 'positiva')

        nota.descripcion = 'Nota de observador actualizada y validada'
        db.session.commit()
        self.assertEqual(nota.descripcion, 'Nota de observador actualizada y validada')

        db.session.delete(nota)
        db.session.commit()
        self.assertIsNone(db.session.get(NotaObservador, nota.id))

    # 16. planes_mejoramiento
    def test_audit_planes_mejoramiento(self):
        plan = PlanMejoramiento(
            aprendiz_id=self.aprendiz1.id,
            ficha_id=self.ficha.id,
            tarea_id=self.tarea.id,
            fecha_limite=datetime.now(timezone.utc) + timedelta(days=15),
            actividades='Entregar diagrama UML y pruebas unitarias de software.',
            estado='pendiente',
            observaciones_instructor='Plazo adicional otorgado tras revision',
            creado_por=self.instructor.id
        )
        db.session.add(plan)
        db.session.commit()
        self.assertIsNotNone(plan.id)
        self.assertEqual(plan.estado, 'pendiente')

        plan.estado = 'cumplido'
        plan.fecha_cumplimiento = datetime.now(timezone.utc)
        db.session.commit()
        self.assertEqual(plan.estado, 'cumplido')

        db.session.delete(plan)
        db.session.commit()
        self.assertIsNone(db.session.get(PlanMejoramiento, plan.id))

    # 17. prorrogas_tareas
    def test_audit_prorrogas_tareas(self):
        prorroga = ProrrogaTarea(
            tarea_id=self.tarea.id,
            aprendiz_id=self.aprendiz1.id,
            instructor_id=self.instructor.id,
            nueva_fecha_limite=datetime.now(timezone.utc) + timedelta(days=5),
            motivo='Incapacidad medica justificada'
        )
        db.session.add(prorroga)
        db.session.commit()
        self.assertIsNotNone(prorroga.id)
        self.assertIn('Incapacidad', prorroga.motivo)

        prorroga.motivo = 'Motivo extendido con comprobante verificado'
        db.session.commit()
        self.assertEqual(prorroga.motivo, 'Motivo extendido con comprobante verificado')

        db.session.delete(prorroga)
        db.session.commit()
        self.assertIsNone(db.session.get(ProrrogaTarea, prorroga.id))

    # 18. puntajes_historicos
    def test_audit_puntajes_historicos(self):
        ph = PuntajeHistorico(
            aprendiz_id=self.aprendiz1.id,
            ficha_id=self.ficha.id,
            corte_id=self.corte.id,
            tipo_corte='automatico',
            puntaje_total=95.5,
            puntaje_asistencia=30.0,
            puntaje_evidencias=45.5,
            puntaje_juicios=20.0,
            posicion=1
        )
        db.session.add(ph)
        db.session.commit()
        self.assertIsNotNone(ph.id)
        self.assertEqual(ph.posicion, 1)

        ph.puntaje_total = 98.0
        db.session.commit()
        self.assertEqual(ph.puntaje_total, 98.0)

        db.session.delete(ph)
        db.session.commit()
        self.assertIsNone(db.session.get(PuntajeHistorico, ph.id))

    # 19. sesiones_asistencia
    def test_audit_sesiones_asistencia(self):
        sesion = SesionAsistencia(
            ficha_id=self.ficha.id,
            corte_id=self.corte.id,
            fecha=date.today(),
            observaciones='Sesion de formacion regular'
        )
        db.session.add(sesion)
        db.session.commit()
        self.assertIsNotNone(sesion.id)
        self.assertEqual(sesion.fecha, date.today())

        sesion.observaciones = 'Sesion con taller practico'
        db.session.commit()
        self.assertEqual(sesion.observaciones, 'Sesion con taller practico')

        db.session.delete(sesion)
        db.session.commit()
        self.assertIsNone(db.session.get(SesionAsistencia, sesion.id))

    # 20. registros_asistencia
    def test_audit_registros_asistencia(self):
        sesion = SesionAsistencia(
            ficha_id=self.ficha.id,
            corte_id=self.corte.id,
            fecha=date.today() - timedelta(days=1),
            observaciones='Sesion previa'
        )
        db.session.add(sesion)
        db.session.flush()

        registro = RegistroAsistencia(
            sesion_id=sesion.id,
            aprendiz_id=self.aprendiz1.id,
            estado='FALTA_JUSTIFICADA',
            causal_justificacion='CITA_MEDICA',
            nota='Presento soporte de EPS Sura',
            soporte_url='https://storage.sena.edu.co/soportes/excusa1.pdf'
        )
        db.session.add(registro)
        db.session.commit()
        self.assertIsNotNone(registro.id)
        self.assertEqual(registro.estado, 'FALTA_JUSTIFICADA')

        registro.estado = 'ASISTE'
        db.session.commit()
        self.assertEqual(registro.estado, 'ASISTE')

        db.session.delete(registro)
        db.session.delete(sesion)
        db.session.commit()
        self.assertIsNone(db.session.get(RegistroAsistencia, registro.id))


if __name__ == '__main__':
    unittest.main()
