"""Títulos de página consistentes: un solo h1, ícono del sistema y mayúscula inicial.

Los emojis se ven distinto en cada sistema operativo y los lectores de
pantalla los leen en voz alta antes del título; los íconos Lucide son
decorativos (`aria-hidden`) y comparten tamaño y color con el resto de la
interfaz.
"""

import re
import unittest
from pathlib import Path

PLANTILLAS = Path(__file__).resolve().parents[1] / 'app' / 'templates'
EMOJI = re.compile('[\U0001F300-\U0001FAFF☀-➿⬀-⯿]')
H1 = re.compile(r'<h1\b[^>]*>(.*?)</h1>', re.S)
# Palabras que pueden ir con mayúscula dentro de un título (siglas y nombres propios).
PERMITIDAS = {'SENA', 'TyT', 'RAP', 'RAPs', 'SOFIA', 'Plus', 'GFPI-F-134', 'GitHub', 'Notion', 'Saber'}
# Nombre del producto: se escribe como marca.
NOMBRE_PRODUCTO = 'SENA Control Académico'


def titulos():
    for ruta in PLANTILLAS.rglob('*.html'):
        texto = ruta.read_text(encoding='utf-8')
        for contenido in H1.findall(texto):
            yield ruta.relative_to(PLANTILLAS).as_posix(), contenido


class TitulosPaginasTest(unittest.TestCase):
    def test_un_solo_h1_por_plantilla(self):
        repetidos = {ruta.relative_to(PLANTILLAS).as_posix(): n for ruta in PLANTILLAS.rglob('*.html')
                     if (n := len(H1.findall(ruta.read_text(encoding='utf-8')))) > 1}
        self.assertEqual(repetidos, {})

    def test_titulos_sin_emoji(self):
        con_emoji = [f'{ruta}: {texto.strip()[:50]}' for ruta, texto in titulos() if EMOJI.search(texto)]
        self.assertEqual(con_emoji, [], 'Use <i data-lucide="..." aria-hidden="true"> en lugar de emojis.')

    def test_titulos_en_mayuscula_inicial(self):
        incorrectos = []
        for ruta, contenido in titulos():
            # Cada rama de un título condicional se evalúa por separado.
            for rama in re.split(r'\{[{%].*?[%}]\}', re.sub(r'<[^>]+>', ' ', contenido)):
                visible = rama.replace(NOMBRE_PRODUCTO, '')
                palabras = re.findall(r'[A-Za-zÁÉÍÓÚÑáéíóúñ][\wÁÉÍÓÚÑáéíóúñ-]*', visible)
                capitalizadas = [p for p in palabras[1:] if p[0].isupper() and p not in PERMITIDAS]
                if capitalizadas:
                    incorrectos.append(f'{ruta}: {" ".join(visible.split())[:60]}')
        self.assertEqual(incorrectos, [], 'En español solo va mayúscula la primera palabra y los nombres propios.')


class TitulosPestanaTest(unittest.TestCase):
    def test_titulos_de_pestana_en_mayuscula_inicial(self):
        bloque = re.compile(r'\{% block title %\}(.*?)\{% endblock %\}')
        incorrectos = []
        for ruta in PLANTILLAS.rglob('*.html'):
            for titulo in bloque.findall(ruta.read_text(encoding='utf-8')):
                # Cada segmento separado por guion o punto medio es un título propio.
                for segmento in re.split(r'\s[-·]\s|\{\{.*?\}\}', titulo.replace('SENA Control', '').replace(NOMBRE_PRODUCTO, '')):
                    palabras = re.findall(r'[A-Za-zÁÉÍÓÚÑáéíóúñ][\wÁÉÍÓÚÑáéíóúñ-]*', segmento)
                    if any(p[0].isupper() and p not in PERMITIDAS for p in palabras[1:]):
                        incorrectos.append(f'{ruta.relative_to(PLANTILLAS).as_posix()}: {titulo}')
        self.assertEqual(incorrectos, [])


if __name__ == '__main__':
    unittest.main()
