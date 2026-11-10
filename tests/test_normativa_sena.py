import unittest
from pathlib import Path
from unittest.mock import patch

from flask import g

from app import create_app, db
from app.models import Instructor
from app.services import normativa_sena as ns


class CatalogoNormativoTest(unittest.TestCase):
    def test_catalogo_real_es_consistente(self):
        self.assertEqual(ns.validar_catalogo(), [])

    def test_archivo_oficial_existe_y_hash_coincide(self):
        ruta = ns.ruta_archivo(ns.ACUERDO_009)
        self.assertTrue(ruta.is_file())
        self.assertEqual(ns.sha256_archivo(ruta), ns.CATALOGO_NORMAS[ns.ACUERDO_009]['sha256'])

    def test_paginas_verificadas_de_las_causales_clave(self):
        esperadas = {
            'productiva_vencida': ('Artículo 30', 31),
            'procedimiento_desercion_productiva': ('Artículo 31', 31),
            'cancelacion_un_anio': ('Artículo 47', 39),
            'aplazamiento': ('Artículo 18', 22),
            'aplazamiento_vencido': ('Artículo 30', 31),
            'consecutivas_injustificadas': ('Artículo 30', 30),
            'tareas_incumplidas': ('Artículo 46', 37),
            'procedimiento_comite': ('Artículo 51', 43),
            'debido_proceso': ('Artículo 50', 42),
        }
        for clave, (articulo, pagina) in esperadas.items():
            with self.subTest(clave=clave):
                fundamento = ns.FUNDAMENTOS[clave]
                self.assertEqual(fundamento['articulo'], articulo)
                self.assertEqual(fundamento['pagina'], pagina)
                self.assertTrue(fundamento['verificado'])

    def test_obtener_fundamento_arma_referencia_y_url(self):
        f = ns.obtener_fundamento('productiva_vencida')
        self.assertEqual(f['clave'], 'productiva_vencida')
        self.assertEqual(f['url'], '/instructor/normativa/acuerdo-009-2024#page=31')
        self.assertIn('Acuerdo 009 de 2024', f['norma'])
        self.assertEqual(
            f['referencia'],
            'Acuerdo 009 de 2024 — Artículo 30, numeral 2 — Deserción por incumplimiento '
            'de la etapa productiva (pág. 31)',
        )

    def test_referencia_con_rango_de_paginas(self):
        self.assertTrue(ns.obtener_fundamento('tareas_incumplidas')['referencia'].endswith('(págs. 37-38)'))

    def test_fundamento_sin_norma_no_tiene_url_y_lo_declara(self):
        f = ns.obtener_fundamento('porcentaje_asistencia')
        self.assertIsNone(f['url'])
        self.assertIsNone(f['norma'])
        self.assertFalse(f['verificado'])
        self.assertIn('sin respaldo normativo explícito', f['referencia'])

    def test_clave_inexistente_lanza_error(self):
        with self.assertRaises(KeyError):
            ns.obtener_fundamento('no_existe')

    def test_fundamentos_de_respeta_el_orden(self):
        claves = [f['clave'] for f in ns.fundamentos_de('aplazamiento', 'productiva_vencida')]
        self.assertEqual(claves, ['aplazamiento', 'productiva_vencida'])

    def test_url_descarga_y_norma_desconocida(self):
        self.assertEqual(ns.url_descarga(ns.ACUERDO_009), '/instructor/normativa/acuerdo-009-2024')
        self.assertIsNone(ns.url_descarga('otra'))
        self.assertIsNone(ns.ruta_archivo('otra'))
        self.assertIsNone(ns.obtener_norma('otra'))

    def test_validar_catalogo_detecta_cada_problema(self):
        catalogo = {
            'sin-archivo': dict(ns.CATALOGO_NORMAS[ns.ACUERDO_009], archivo='no_existe.pdf'),
            'hash-malo': dict(ns.CATALOGO_NORMAS[ns.ACUERDO_009], sha256='0' * 64),
        }
        fundamentos = {
            'pagina_fuera': dict(ns.FUNDAMENTOS['productiva_vencida'], norma_id='hash-malo', pagina=99),
            'norma_desconocida': dict(ns.FUNDAMENTOS['productiva_vencida'], norma_id='x'),
            'sin_norma_verificado': dict(ns.FUNDAMENTOS['porcentaje_asistencia'], verificado=True),
        }
        with patch.object(ns, 'CATALOGO_NORMAS', catalogo), patch.object(ns, 'FUNDAMENTOS', fundamentos):
            problemas = '\n'.join(ns.validar_catalogo())
        self.assertIn('sin-archivo: falta el archivo', problemas)
        self.assertIn('hash-malo: el hash SHA-256 no coincide', problemas)
        self.assertIn('pagina_fuera: página fuera del documento', problemas)
        self.assertIn('norma_desconocida: norma desconocida x', problemas)
        self.assertIn('sin_norma_verificado: sin norma no puede marcarse', problemas)


class RutasNormativaTest(unittest.TestCase):
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
        self.instructor = Instructor(nombre='Instructor', correo='n@sena.edu.co', rol='admin')
        self.instructor.set_password('clave-segura')
        db.session.add(self.instructor)
        db.session.commit()
        self.cliente = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.contexto.pop()

    def _autenticar(self):
        g.pop('_login_user', None)
        with self.cliente.session_transaction() as sesion:
            sesion['_user_id'] = str(self.instructor.id)
            sesion['_fresh'] = True

    def test_sin_sesion_redirige_al_login(self):
        for ruta in ('/instructor/normativa', '/instructor/normativa/acuerdo-009-2024'):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.cliente.get(ruta).status_code, 302)

    def test_pagina_de_normativa_lista_norma_y_paginas(self):
        self._autenticar()
        html = self.cliente.get('/instructor/normativa').get_data(as_text=True)
        self.assertIn('Acuerdo 009 de 2024', html)
        self.assertIn('#page=31', html)
        self.assertIn('Página 39', html)

    def test_pdf_se_sirve_en_linea_y_como_descarga(self):
        self._autenticar()
        respuesta = self.cliente.get('/instructor/normativa/acuerdo-009-2024')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.mimetype, 'application/pdf')
        self.assertTrue(respuesta.get_data().startswith(b'%PDF'))
        self.assertNotIn('attachment', respuesta.headers.get('Content-Disposition', ''))
        respuesta.close()
        descarga = self.cliente.get('/instructor/normativa/acuerdo-009-2024?descargar=1')
        self.assertIn('attachment', descarga.headers['Content-Disposition'])
        descarga.close()

    def test_norma_inexistente_responde_404(self):
        self._autenticar()
        self.assertEqual(self.cliente.get('/instructor/normativa/otra').status_code, 404)

    def test_archivo_faltante_responde_404(self):
        self._autenticar()
        with patch('app.routes.comite.ruta_archivo', return_value=Path('no/existe.pdf')):
            self.assertEqual(self.cliente.get('/instructor/normativa/acuerdo-009-2024').status_code, 404)


if __name__ == '__main__':
    unittest.main()
