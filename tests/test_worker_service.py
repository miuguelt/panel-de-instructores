"""Pruebas unitarias para utilidades y ciclo de vida de worker.py."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app import create_app, db
from app.models import Ficha, ImportacionJob, Instructor
from worker import (
    _conectar_redis,
    _entero_positivo_entorno,
    _procesar,
    _resultado_resumido,
)


class WorkerServiceTestCase(unittest.TestCase):
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

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.uploads.cleanup()

    def test_entero_positivo_entorno_valores(self):
        with patch.dict(os.environ, {'TEST_VAR': '42'}):
            self.assertEqual(_entero_positivo_entorno('TEST_VAR', 10), 42)

        with patch.dict(os.environ, {'TEST_VAR': '0'}):
            self.assertEqual(_entero_positivo_entorno('TEST_VAR', 10), 10)

        with patch.dict(os.environ, {'TEST_VAR': '-5'}):
            self.assertEqual(_entero_positivo_entorno('TEST_VAR', 10), 10)

        with patch.dict(os.environ, {'TEST_VAR': 'no_es_numero'}):
            self.assertEqual(_entero_positivo_entorno('TEST_VAR', 10), 10)

        with patch.dict(os.environ, {'TEST_VAR': '   '}):
            self.assertEqual(_entero_positivo_entorno('TEST_VAR', 10), 10)

        self.assertEqual(_entero_positivo_entorno('VARIABLE_INEXISTENTE', 15), 15)

    def test_resultado_resumido_campos(self):
        resultado = {
            'nuevos': 5,
            'actualizados': 2,
            'juicios_nuevos': 10,
            'juicios_actualizados': 1,
            'juicios_repetidos': 0,
            'sesiones_creadas': 3,
            'errores': ['Error fila 1', 'Error fila 2'],
            'campo_extra_no_relevante': 'ignorado',
        }
        resumido = _resultado_resumido(resultado)
        self.assertEqual(resumido['nuevos'], 5)
        self.assertEqual(resumido['actualizados'], 2)
        self.assertEqual(resumido['juicios_nuevos'], 10)
        self.assertEqual(resumido['errores'], 2)
        self.assertNotIn('campo_extra_no_relevante', resumido)

    def test_conectar_redis_exito_crea_testigo(self):
        mock_cliente = MagicMock()
        with tempfile.TemporaryDirectory() as temp_dir:
            testigo = os.path.join(temp_dir, 'worker-ready')
            with patch('worker.WORKER_READY_FILE', testigo), \
                 patch('worker._cliente_redis', return_value=mock_cliente), \
                 patch.dict(os.environ, {'WORKER_REDIS_RETRIES': '2', 'WORKER_REDIS_RETRY_DELAY': '0.01'}):
                cliente = _conectar_redis()
                self.assertIs(cliente, mock_cliente)
                self.assertTrue(os.path.exists(testigo))
                with open(testigo, 'r', encoding='utf-8') as f:
                    contenido = f.read()
                self.assertIn('pid=', contenido)

    def test_conectar_redis_falla_tras_reintentos(self):
        with patch('worker._cliente_redis', side_effect=Exception('Fallo de red')), \
             patch('time.sleep'), \
             patch.dict(os.environ, {'WORKER_REDIS_RETRIES': '2', 'WORKER_REDIS_RETRY_DELAY': '0.01'}):
            with self.assertRaises(RuntimeError) as ctx:
                _conectar_redis()
            self.assertIn('El worker no pudo conectar con Redis después de 2 intentos', str(ctx.exception))

    def test_procesar_ignora_job_inexistente_o_no_encolado(self):
        with patch('worker.app', self.app):
            # No debe lanzar excepción con ID inexistente
            _procesar(999999)

            instructor = Instructor(nombre='Instructor', correo='inst_worker@sena.edu.co')
            instructor.set_password('x')
            db.session.add(instructor)
            db.session.flush()

            ficha = Ficha(
                codigo='123456', codigo_ficha='123456', codigo_programa='228118',
                nombre_programa='Programa', instructor_id=instructor.id,
            )
            db.session.add(ficha)
            db.session.flush()

            job = ImportacionJob(
                ficha_id=ficha.id,
                instructor_id=instructor.id,
                estado='completado',
                archivo_path='dummy.xlsx',
                nombre_archivo='dummy.xlsx',
            )
            db.session.add(job)
            db.session.commit()

            # Estado no es 'encolado', no debe procesarlo
            _procesar(job.id)
            db.session.expire_all()
            job_actual = db.session.get(ImportacionJob, job.id)
            self.assertEqual(job_actual.estado, 'completado')


if __name__ == '__main__':
    unittest.main()
