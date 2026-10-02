"""Regresión de almacenamiento documental y resultados calculados en PostgreSQL."""

import json
import os
import secrets
import unittest
from datetime import date, datetime
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask, url_for

from app import _registrar_cache_estaticos, create_app, db
from app.models import (
    Aprendiz,
    ArchivoFichaVersion,
    Ficha,
    ImportacionJob,
    Instructor,
    JuicioEvaluativo,
)
from app.models.resultado_calculado import ResultadoCalculadoFicha
from app.services.resultados_persistidos import (
    obtener_resultado_persistido,
    guardar_contenido_documento,
    obtener_contenido_documento,
    fecha_corte_bogota,
    invalidar_resultados_ficha,
    precargar_resultados_ficha,
)
from app.services.importacion_jobs import (
    ColaImportacionesNoDisponible,
    encolar_recalculo_resumen,
)


class ResultadosPersistidosTestCase(unittest.TestCase):
    def setUp(self):
        self.archivos = TemporaryDirectory()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {},
            'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False,
            'UPLOAD_FOLDER': self.archivos.name,
        })
        self.contexto = self.app.app_context()
        self.contexto.push()
        db.create_all()
        instructor = Instructor(nombre='Instructor', correo='cache@example.com')
        instructor.set_password(secrets.token_urlsafe(24))
        db.session.add(instructor)
        db.session.flush()
        self.ficha = Ficha(
            codigo='700100', codigo_ficha='700100', codigo_programa='228118',
            nombre_programa='Tecnología de prueba', instructor_id=instructor.id,
            fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31),
        )
        db.session.add(self.ficha)
        db.session.flush()
        self.version = ArchivoFichaVersion(
            ficha_id=self.ficha.id, instructor_id=instructor.id, tipo='planeacion',
            version=1, nombre_archivo='planeacion.xlsx', ruta_archivo='planeacion.xlsx',
            hash_sha256='a' * 64, tamano_bytes=10, estado='procesado',
        )
        db.session.add(self.version)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.archivos.cleanup()

    def test_extraido_se_persiste_y_se_lee_sin_abrir_archivo(self):
        contenido = {
            'metadata': {'fecha_elaboracion': date(2026, 2, 3)},
            'unidades': [{'rap': '601390 - Resultado', 'horas_total': 8}],
        }
        guardar_contenido_documento(self.version, contenido, parser_version='planeacion-v1')
        db.session.commit()

        with patch('pathlib.Path.is_file', side_effect=AssertionError('No debe consultar el archivo')):
            leido = obtener_contenido_documento(
                self.version, lambda _ruta: self.fail('No debe ejecutar el parser'),
                parser_version='planeacion-v1',
            )

        self.assertEqual(leido, contenido)
        self.assertIsInstance(leido['metadata']['fecha_elaboracion'], date)

    def test_documento_legacy_se_parsea_una_vez_y_se_migra_al_leerlo(self):
        contenido = {'metadata': {'codigo_programa': '228118'}, 'unidades': []}
        ruta = self.archivos.name + '/planeacion.xlsx'
        with open(ruta, 'wb') as archivo:
            archivo.write(b'original')
        llamadas = []

        def parser(ruta_recibida):
            llamadas.append(str(ruta_recibida))
            return contenido

        primera = obtener_contenido_documento(
            self.version, parser, parser_version='planeacion-v1'
        )
        segunda = obtener_contenido_documento(
            self.version, lambda _ruta: self.fail('El contenido debe salir de PostgreSQL'),
            parser_version='planeacion-v1',
        )

        self.assertEqual(primera, contenido)
        self.assertEqual(segunda, contenido)
        self.assertEqual(len(llamadas), 1)
        self.assertEqual(self.version.contenido_extraido_version, 'planeacion-v1')

    def test_cache_persistente_reutiliza_resultado_e_invalida_por_revision_y_fecha(self):
        hoy = date(2026, 6, 1)
        versiones = [self.version]
        llamadas = []

        def construir():
            llamadas.append(True)
            return {'conteo': len(llamadas), 'fecha': hoy, 'version': self.version}

        primero = obtener_resultado_persistido(
            self.ficha, 'panorama', hoy, versiones, construir
        )
        segundo = obtener_resultado_persistido(
            self.ficha, 'panorama', hoy, versiones,
            lambda: self.fail('El cálculo debe salir de la tabla de resultados'),
        )
        self.assertEqual(primero, segundo)
        self.assertEqual(segundo['fecha'], hoy)
        self.assertIsInstance(segundo['version'], ArchivoFichaVersion)
        self.assertEqual(ResultadoCalculadoFicha.query.count(), 1)

        self.ficha.revision_calculos += 1
        db.session.commit()
        obtener_resultado_persistido(
            self.ficha, 'panorama', hoy, versiones,
            lambda: {'conteo': 2},
        )
        obtener_resultado_persistido(
            self.ficha, 'panorama', date(2026, 6, 2), versiones,
            lambda: {'conteo': 3},
        )
        self.assertEqual(ResultadoCalculadoFicha.query.count(), 3)
        self.assertEqual(len(llamadas), 1)

    def test_cambios_academicos_incrementan_revision_de_resultados(self):
        revision_inicial = self.ficha.revision_calculos
        aprendiz = Aprendiz(
            ficha_id=self.ficha.id, documento='101', nombre='Ana', apellidos='Prueba',
            estado='EN_FORMACION',
        )
        db.session.add(aprendiz)
        db.session.commit()
        self.assertGreater(self.ficha.revision_calculos, revision_inicial)

        revision_aprendiz = self.ficha.revision_calculos
        db.session.add(JuicioEvaluativo(
            ficha_id=self.ficha.id, aprendiz_id=aprendiz.id,
            resultado_aprendizaje='601390 - Resultado', juicio='APROBADO',
            funcionario_registro='Instructora', fecha_juicio=datetime(2026, 5, 1),
        ))
        db.session.commit()
        self.assertGreater(self.ficha.revision_calculos, revision_aprendiz)

        revision_juicio = self.ficha.revision_calculos
        self.ficha.fecha_fin = date(2027, 1, 1)
        db.session.commit()
        self.assertGreater(self.ficha.revision_calculos, revision_juicio)

    def test_invalidacion_explicita_cubre_inserciones_masivas(self):
        revision_inicial = self.ficha.revision_calculos
        invalidar_resultados_ficha(self.ficha.id)
        db.session.commit()
        self.assertEqual(self.ficha.revision_calculos, revision_inicial + 1)

    def test_cache_serializa_respuestas_json_validas(self):
        resultado = obtener_resultado_persistido(
            self.ficha, 'fases', date(2026, 6, 1), [self.version],
            lambda: {'total': 4, 'fases': ['ANÁLISIS']},
        )
        fila = ResultadoCalculadoFicha.query.one()
        self.assertEqual(fila.payload_json, resultado)

    def test_fecha_de_snapshot_usa_huso_horario_de_bogota(self):
        self.assertIsInstance(fecha_corte_bogota(), date)

    def test_precarga_calcula_fases_en_la_tabla_persistente(self):
        self.version.estado = 'pendiente'
        db.session.commit()
        resumen = precargar_resultados_ficha(self.ficha.id, hoy=date(2026, 6, 1))
        self.assertEqual(resumen['ficha_id'], self.ficha.id)
        self.assertFalse(resumen['panorama'])
        self.assertTrue(resumen['fases'])
        self.assertEqual(ResultadoCalculadoFicha.query.filter_by(tipo='fases').count(), 1)

    def test_serializador_rechaza_objetos_no_soportados(self):
        from app.services.resultados_persistidos import _json_default

        with self.assertRaises(TypeError):
            _json_default(object())

    def test_version_estatica_cambia_con_el_contenido_aunque_no_cambie_mtime(self):
        from app import _registrar_cache_estaticos

        with TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, 'modulo.js')
            with open(ruta, 'wb') as archivo:
                archivo.write(b'const valor = 1;')
            marca = os.stat(ruta).st_mtime
            app = Flask('static-fingerprint', static_folder=carpeta, static_url_path='/static')
            _registrar_cache_estaticos(app)
            with app.test_request_context():
                primera = url_for('static', filename='modulo.js')
                with open(ruta, 'wb') as archivo:
                    archivo.write(b'const valor = 2;')
                os.utime(ruta, (marca, marca))
                segunda = url_for('static', filename='modulo.js')
            self.assertNotEqual(primera, segunda)
            self.assertIn('immutable', app.test_client().get(segunda).headers['Cache-Control'])

    def test_version_estatica_ausente_no_rompe_la_generacion_de_url(self):
        app = Flask('static-missing', static_folder=self.archivos.name, static_url_path='/static')
        _registrar_cache_estaticos(app)
        with app.test_request_context():
            url = url_for('static', filename='no-existe.js')
        self.assertTrue(url.endswith('/static/no-existe.js'))

    def test_documento_sin_version_devuelve_none_y_archivo_ausente_falla_claro(self):
        self.assertIsNone(obtener_contenido_documento(None, Mock(), 'v1'))
        with self.assertRaisesRegex(FileNotFoundError, 'planeacion.xlsx'):
            obtener_contenido_documento(self.version, Mock(), 'planeacion-v1')

    def test_bloqueo_de_calculo_se_activa_en_postgresql(self):
        from app.services.resultados_persistidos import _adquirir_bloqueo

        with patch.object(
            db.session, 'get_bind', return_value=SimpleNamespace(
                dialect=SimpleNamespace(name='postgresql')
            ),
        ), patch.object(db.session, 'execute') as ejecutar:
            _adquirir_bloqueo(self.ficha.id)
        ejecutar.assert_called_once()
        self.assertIn('pg_advisory_xact_lock', str(ejecutar.call_args.args[0]))

    def test_encola_recalculo_y_registra_fallo_de_redis_sin_fallar_la_carga(self):
        with patch('app.services.importacion_jobs.encolar_importacion') as encolar:
            trabajo = encolar_recalculo_resumen(self.ficha.id, self.version.instructor_id)
        self.assertEqual(trabajo.estado, 'encolado')
        self.assertEqual(trabajo.tipo_trabajo, 'resumen_ficha')
        encolar.assert_called_once_with(trabajo.id, self.app.config['IMPORT_QUEUE_NAME'])

        with patch(
            'app.services.importacion_jobs.encolar_importacion',
            side_effect=ColaImportacionesNoDisponible('Redis sin conexión'),
        ):
            fallido = encolar_recalculo_resumen(self.ficha.id, self.version.instructor_id)
        self.assertEqual(fallido.estado, 'error')
        self.assertIn('Redis sin conexión', fallido.error)

    def test_worker_completa_trabajos_de_snapshot_y_registra_errores(self):
        from worker import _procesar

        trabajo = ImportacionJob(
            ficha_id=self.ficha.id, instructor_id=self.version.instructor_id,
            tipo_trabajo='resumen_ficha', archivo_path='',
            nombre_archivo='resumen calculado', estado='encolado',
        )
        db.session.add(trabajo)
        db.session.commit()
        with patch('worker.app', self.app), patch(
            'app.services.resultados_persistidos.precargar_resultados_ficha',
            return_value={'ficha_id': self.ficha.id, 'panorama': True, 'fases': True},
        ):
            _procesar(trabajo.id)
        db.session.expire_all()
        completado = db.session.get(ImportacionJob, trabajo.id)
        self.assertEqual(completado.estado, 'completado')
        self.assertIn('"panorama": true', completado.resultado)

        fallido = ImportacionJob(
            ficha_id=self.ficha.id, instructor_id=self.version.instructor_id,
            tipo_trabajo='resumen_ficha', archivo_path='',
            nombre_archivo='resumen calculado', estado='encolado',
        )
        db.session.add(fallido)
        db.session.commit()
        with patch('worker.app', self.app), patch(
            'app.services.resultados_persistidos.precargar_resultados_ficha',
            side_effect=ValueError('fuente ilegible'),
        ):
            _procesar(fallido.id)
        db.session.expire_all()
        fallido_db = db.session.get(ImportacionJob, fallido.id)
        self.assertEqual(fallido_db.estado, 'error')
        self.assertIn('fuente ilegible', fallido_db.error)


if __name__ == '__main__':
    unittest.main()
