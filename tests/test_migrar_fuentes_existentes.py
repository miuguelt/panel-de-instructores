"""Pruebas de conciliación documental para fichas ya existentes."""

from datetime import date
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import openpyxl
from werkzeug.datastructures import FileStorage

from app import create_app, db
from app.models import Aprendiz, ArchivoFichaVersion, Ficha, Instructor, JuicioEvaluativo
from app.services.importacion_ficha import importar_archivo
from scripts.migrar_fuentes_existentes import main, migrar_fuentes_existentes
from tests.apoyo_planeacion import crear_planeacion_xlsx
from tests.apoyo_programa import crear_programa_pdf


def crear_reporte(ruta, fecha, juicio):
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.append(['Reporte de Juicios de Evaluación'])
    hoja.append(['Fecha del Reporte:', fecha])
    hoja.append(['Ficha de Caracterización:', '3336360'])
    hoja.append(['Código:', '228118'])
    hoja.append(['Denominación:', 'Tecnólogo en Analisis y Desarrollo de Software'])
    for _ in range(8):
        hoja.append([])
    hoja.append([
        'Tipo de Documento', 'Número de Documento', 'Nombre', 'Apellidos', 'Estado',
        'Competencia', 'Resultado de Aprendizaje', 'Juicio de Evaluación',
        'Fecha y Hora del Juicio Evaluativo',
        'Funcionario que registro el juicio evaluativo',
    ])
    hoja.append([
        'CC', '1001', 'Ana', 'Prueba', 'EN_FORMACION', 'Competencia 1',
        'Resultado 1', juicio, fecha, 'Instructor',
    ])
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    libro.save(ruta)
    return ruta


class MigrarFuentesExistentesTestCase(unittest.TestCase):
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
        self.instructor = Instructor(
            nombre='Instructor de prueba', correo='migracion@sena.edu.co', rol='admin'
        )
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.flush()
        self.ficha = Ficha(
            codigo='3336360', codigo_ficha='3336360', codigo_programa='228118',
            nombre_programa='Tecnólogo en Analisis y Desarrollo de Software',
            instructor_id=self.instructor.id, fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 12, 31),
        )
        db.session.add(self.ficha)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()
        self.archivos.cleanup()

    def test_migra_tres_fuentes_una_vez_y_aplica_el_reporte_mas_reciente(self):
        raiz = Path(self.archivos.name)
        ficha_heredada = raiz / 'fichas' / '999'
        crear_reporte(
            ficha_heredada / 'reporte_juicios' / 'reporte_antiguo.xlsx',
            '01/06/2026', 'POR EVALUAR',
        )
        reciente = crear_reporte(
            ficha_heredada / 'reporte_juicios' / 'reporte_reciente.xlsx',
            '12/09/2026', 'APROBADO',
        )
        crear_reporte(
            raiz / 'fichas' / '888' / 'reporte_juicios' / 'copia.xlsx',
            '12/09/2026', 'APROBADO',
        )
        (ficha_heredada / 'planeacion').mkdir(parents=True)
        (ficha_heredada / 'programa_formacion').mkdir(parents=True)
        crear_planeacion_xlsx(str(ficha_heredada / 'planeacion'))
        crear_programa_pdf(str(ficha_heredada / 'programa_formacion'))
        (raiz / 'entregas').mkdir()
        (raiz / 'entregas' / 'ignorar.pdf').write_bytes(b'no se procesa')

        primera = migrar_fuentes_existentes(self.app, raiz, aplicar=True)

        self.assertEqual(primera['registrados'], 4)
        self.assertEqual(primera['reportes_reaplicados'], 1)
        self.assertEqual(primera['duplicados'], 1)
        self.assertEqual(primera['sin_ficha'], 0)
        self.assertEqual(ArchivoFichaVersion.query.count(), 4)
        self.assertEqual(ArchivoFichaVersion.query.filter_by(tipo='planeacion').one().contenido_extraido_version, 'planeacion-v1')
        self.assertEqual(ArchivoFichaVersion.query.filter_by(tipo='programa_formacion').one().contenido_extraido_version, 'programa-v1')
        self.assertEqual(Aprendiz.query.count(), 1)
        self.assertEqual(JuicioEvaluativo.query.one().juicio, 'APROBADO')
        self.assertIn(
            'fichas/999/reporte_juicios',
            ArchivoFichaVersion.query.filter_by(tipo='reporte_juicios').first().ruta_archivo,
        )

        with patch(
            'scripts.migrar_fuentes_existentes.parsear_planeacion',
            side_effect=AssertionError('La planeación ya debe leerse desde PostgreSQL'),
        ), patch(
            'scripts.migrar_fuentes_existentes.parsear_programa',
            side_effect=AssertionError('El PDF ya debe leerse desde PostgreSQL'),
        ), patch(
            'scripts.migrar_fuentes_existentes.leer_metadata_archivo',
            side_effect=AssertionError('El Excel ya debe leerse desde PostgreSQL'),
        ):
            segunda = migrar_fuentes_existentes(self.app, raiz, aplicar=True)

        self.assertEqual(segunda['registrados'], 0)
        self.assertEqual(segunda['reportes_reaplicados'], 0)
        self.assertEqual(segunda['ya_existian'], 5)
        self.assertEqual(ArchivoFichaVersion.query.count(), 4)
        self.assertEqual(JuicioEvaluativo.query.count(), 1)
        self.assertEqual(JuicioEvaluativo.query.one().juicio, 'APROBADO')
        self.assertTrue(reciente.is_file())

    def test_no_crea_ficha_para_un_reporte_sin_coincidencia(self):
        ruta = Path(self.archivos.name) / 'fichas' / '999' / 'reporte_juicios' / 'otra.xlsx'
        crear_reporte(ruta, '12/09/2026', 'APROBADO')
        libro = openpyxl.load_workbook(ruta)
        libro.active['B3'] = '9999999'
        libro.save(ruta)

        resultado = migrar_fuentes_existentes(self.app, Path(self.archivos.name), aplicar=True)

        self.assertEqual(resultado['sin_ficha'], 1)
        self.assertEqual(Ficha.query.count(), 1)
        self.assertEqual(ArchivoFichaVersion.query.count(), 0)

    def test_repara_estado_historico_aunque_no_haya_versiones_nuevas(self):
        raiz = Path(self.archivos.name)
        carpeta = raiz / 'fichas' / str(self.ficha.id) / 'reporte_juicios'
        antiguo = crear_reporte(carpeta / 'antiguo.xlsx', '01/06/2026', 'POR EVALUAR')
        reciente = crear_reporte(carpeta / 'reciente.xlsx', '12/09/2026', 'APROBADO')

        with antiguo.open('rb') as stream:
            importar_archivo(
                FileStorage(stream=stream, filename=antiguo.name),
                self.ficha,
                self.instructor.id,
            )
        db.session.commit()
        # Simula que versiones históricas entraron después del reporte vigente.
        for numero, ruta, fecha in (
            (1, reciente, '2026-09-12'),
            (2, antiguo, '2026-06-01'),
        ):
            db.session.add(ArchivoFichaVersion(
                ficha_id=self.ficha.id,
                instructor_id=self.instructor.id,
                tipo='reporte_juicios',
                version=numero,
                nombre_archivo=ruta.name,
                ruta_archivo=ruta.relative_to(raiz).as_posix(),
                hash_sha256=hashlib.sha256(ruta.read_bytes()).hexdigest(),
                tamano_bytes=ruta.stat().st_size,
                estado='procesado',
                metadata_json=json.dumps({'fecha_reporte': fecha}),
            ))
        db.session.commit()

        reparacion = migrar_fuentes_existentes(self.app, raiz, aplicar=True)

        self.assertEqual(reparacion['registrados'], 0)
        self.assertEqual(reparacion['reportes_reaplicados'], 1)
        self.assertEqual(JuicioEvaluativo.query.one().juicio, 'APROBADO')
        self.assertEqual(
            json.loads(ArchivoFichaVersion.query.filter_by(version=1).one().metadata_json)
            ['_conciliado_hasta_version'],
            2,
        )

        repeticion = migrar_fuentes_existentes(self.app, raiz, aplicar=True)

        self.assertEqual(repeticion['reportes_reaplicados'], 0)
        self.assertEqual(JuicioEvaluativo.query.one().juicio, 'APROBADO')

    def test_modo_revision_no_escribe_en_la_base(self):
        raiz = Path(self.archivos.name)
        (raiz / 'fichas' / '999' / 'planeacion').mkdir(parents=True)
        crear_planeacion_xlsx(str(raiz / 'fichas' / '999' / 'planeacion'))

        resultado = migrar_fuentes_existentes(self.app, raiz, aplicar=False)

        self.assertEqual(resultado['elegibles'], 1)
        self.assertEqual(resultado['registrados'], 0)
        self.assertEqual(ArchivoFichaVersion.query.count(), 0)

    def test_rechaza_reportes_ambiguos_sin_crear_fichas(self):
        db.session.add(Ficha(
            codigo='3336360', codigo_programa='228118',
            nombre_programa='Tecnólogo en Analisis y Desarrollo de Software',
            instructor_id=self.instructor.id,
        ))
        db.session.commit()
        ruta = Path(self.archivos.name) / 'fichas' / '999' / 'reporte_juicios' / 'ambiguo.xlsx'
        crear_reporte(ruta, '12/09/2026', 'APROBADO')

        resultado = migrar_fuentes_existentes(self.app, Path(self.archivos.name), aplicar=True)

        self.assertEqual(resultado['ambiguas'], 1)
        self.assertEqual(Ficha.query.count(), 2)
        self.assertEqual(ArchivoFichaVersion.query.count(), 0)

    def test_completa_extraccion_existente_y_ejecuta_revision(self):
        raiz = Path(self.archivos.name)
        carpeta = raiz / 'fichas' / '999' / 'planeacion'
        carpeta.mkdir(parents=True)
        archivo = crear_planeacion_xlsx(str(carpeta))
        import hashlib
        digest = hashlib.sha256(archivo.read_bytes()).hexdigest()
        db.session.add(ArchivoFichaVersion(
            ficha_id=self.ficha.id, instructor_id=self.instructor.id,
            tipo='planeacion', version=1, nombre_archivo=archivo.name,
            ruta_archivo=archivo.relative_to(raiz).as_posix(), hash_sha256=digest,
            tamano_bytes=archivo.stat().st_size, estado='procesado',
        ))
        db.session.commit()

        resultado = migrar_fuentes_existentes(self.app, raiz, aplicar=True)

        self.assertEqual(resultado['extracciones_actualizadas'], 1)
        self.assertEqual(ArchivoFichaVersion.query.count(), 1)
        self.assertTrue(ArchivoFichaVersion.query.one().contenido_extraido_json)

        import wsgi
        with patch.object(wsgi, 'app', self.app), redirect_stdout(StringIO()):
            self.assertEqual(main([]), 0)


if __name__ == '__main__':
    unittest.main()
