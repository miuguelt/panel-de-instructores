"""Verifica que los archivos subidos sobrevivan a una reconstrucción.

No requiere Docker: comprueba por inspección estática que `docker-compose.yml`
y el `Dockerfile` declaren un volumen nombrado, compartido por web y worker, en
la misma ruta que usa la aplicación. Un bind al repositorio, un volumen anónimo
o un `tmpfs` harían que cada `docker compose up --build` de Coolify borrara las
evidencias y los materiales.
"""

import os
import re
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPOSE = os.path.join(RAIZ, 'docker-compose.yml')
DOCKERFILE = os.path.join(RAIZ, 'Dockerfile')

PUNTO_DE_MONTAJE = '/app/uploads'
NOMBRE_VOLUMEN = 'adso_uploads'


def _leer(ruta):
    with open(ruta, encoding='utf-8') as handle:
        return handle.read()


def _bloques_de_servicio(compose):
    """Devuelve {nombre_servicio: texto} usando la indentación del YAML."""
    servicios = {}
    dentro = False
    actual = None
    lineas = []
    for linea in compose.splitlines():
        if re.match(r'^services:\s*$', linea):
            dentro = True
            continue
        if dentro and re.match(r'^\S', linea):  # otra clave de primer nivel
            break
        if not dentro:
            continue
        encabezado = re.match(r'^  (\w[\w.-]*):\s*$', linea)
        if encabezado:
            if actual:
                servicios[actual] = '\n'.join(lineas)
            actual = encabezado.group(1)
            lineas = []
            continue
        if actual:
            lineas.append(linea)
    if actual:
        servicios[actual] = '\n'.join(lineas)
    return servicios


class PersistenciaDespliegueTestCase(unittest.TestCase):
    def setUp(self):
        self.compose = _leer(COMPOSE)
        self.servicios = _bloques_de_servicio(self.compose)

    def test_web_y_worker_montan_el_mismo_volumen_de_uploads(self):
        for servicio in ('app', 'worker'):
            self.assertIn(servicio, self.servicios, f'Falta el servicio {servicio}.')
            self.assertIn(
                f'- uploads:{PUNTO_DE_MONTAJE}',
                self.servicios[servicio],
                f'El servicio {servicio} no monta el volumen de subidas.',
            )

    def test_el_volumen_es_nombrado_y_estable(self):
        declaracion = self.compose.split('\nvolumes:', 1)
        self.assertEqual(len(declaracion), 2, 'No hay bloque de volúmenes de primer nivel.')
        bloque = declaracion[1]
        self.assertRegex(
            bloque,
            r'(?m)^\s+uploads:\s*$',
            'El volumen `uploads` no está declarado.',
        )
        self.assertIn(
            f'name: {NOMBRE_VOLUMEN}',
            bloque,
            'El volumen debe tener nombre fijo para sobrevivir a un redeploy.',
        )

    def test_no_se_usa_almacenamiento_efimero_para_las_subidas(self):
        # Un bind al repo (./uploads) se perdería al reconstruir la imagen en
        # el servidor, y tmpfs vive solo en memoria.
        self.assertNotIn(f'./uploads:{PUNTO_DE_MONTAJE}', self.compose)
        self.assertNotIn('tmpfs', self.compose)

    def test_la_ruta_de_la_app_coincide_con_el_punto_de_montaje(self):
        for servicio in ('app', 'worker'):
            self.assertIn(
                f'UPLOAD_FOLDER=${{UPLOAD_FOLDER:-{PUNTO_DE_MONTAJE}}}',
                self.servicios[servicio],
                f'UPLOAD_FOLDER de {servicio} no apunta al volumen montado.',
            )
        dockerfile = _leer(DOCKERFILE)
        self.assertIn(f'UPLOAD_FOLDER={PUNTO_DE_MONTAJE}', dockerfile)

    def test_la_imagen_crea_la_carpeta_con_el_usuario_de_la_app(self):
        dockerfile = _leer(DOCKERFILE)
        self.assertIn(f'mkdir -p {PUNTO_DE_MONTAJE}', dockerfile)
        self.assertIn(f'chown -R adso:adso {PUNTO_DE_MONTAJE}', dockerfile)

    def test_solo_el_servicio_web_aplica_migraciones_antes_de_arrancar(self):
        entrypoint = _leer(os.path.join(RAIZ, 'docker-entrypoint.sh'))
        dockerfile = _leer(DOCKERFILE)
        self.assertIn('RUN_MIGRATIONS="${RUN_MIGRATIONS:-true}"', entrypoint)
        self.assertIn('python3 -m flask db upgrade', entrypoint)
        self.assertIn('- RUN_MIGRATIONS=true', self.servicios['app'])
        self.assertIn('- RUN_MIGRATIONS=false', self.servicios['worker'])
        self.assertIn('FLASK_APP=wsgi.py', dockerfile)
        self.assertIn('COPY --chown=adso:adso . .', dockerfile)


if __name__ == '__main__':
    unittest.main()
