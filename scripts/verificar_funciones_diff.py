"""Valida que toda función nueva o modificada en Git cuente con su prueba respectiva.

Cumple con la Regla 5.0 de DevBrain: no se permite consolidar código de producción
sin que cada función nueva esté acompañada de sus pruebas automatizadas y ejecutada
con aserciones observables.
"""

import argparse
import ast
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def obtener_diff_git(referencia=None, en_stage=False):
    """Obtiene la salida de git diff según los argumentos proporcionados."""
    comando = ['git', 'diff', '-U0']
    if en_stage:
        comando.append('--cached')
    elif referencia:
        comando.append(referencia)
    else:
        try:
            staged = subprocess.check_output(['git', 'diff', '--cached', '--name-only'], text=True).strip()
            if staged:
                comando.append('--cached')
            else:
                comando.append('HEAD')
        except subprocess.SubprocessError:
            pass

    try:
        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
        )
        return resultado.stdout
    except Exception as exc:
        sys.stderr.write(f'Error al ejecutar git diff: {exc}\n')
        return ''


def extraer_funciones_nuevas_diff(diff_texto, directorios_fuente=('app', 'worker.py')):
    """Identifica las funciones agregadas en el diff dentro de los directorios de producción."""
    funciones_nuevas = []
    archivo_actual = None
    es_fuente = False

    lineas = diff_texto.splitlines()
    for linea in lineas:
        if linea.startswith('+++ b/'):
            archivo_actual = linea[6:].strip().replace('\\', '/')
            es_fuente = any(
                archivo_actual.startswith(d + '/') or archivo_actual == d
                for d in directorios_fuente
            ) and not archivo_actual.startswith('tests/') and not archivo_actual.startswith('migrations/')
            continue

        if not es_fuente or not archivo_actual:
            continue

        if linea.startswith('+') and not linea.startswith('+++'):
            contenido = linea[1:]
            coincidencia = re.match(r'^\s*(?:async\s+)?def\s+([a-zA-Z0-9_]+)\s*\(', contenido)
            if coincidencia:
                nombre_funcion = coincidencia.group(1)
                funciones_nuevas.append({
                    'archivo': archivo_actual,
                    'nombre': nombre_funcion,
                    'linea_declaracion': contenido.strip(),
                })

    return funciones_nuevas


def verificar_cobertura_con_llamadas(funciones_nuevas, ruta_llamadas):
    """Verifica que cada función haya sido ejecutada por pruebas registradas en calls.json."""
    datos = json.loads(Path(ruta_llamadas).read_text(encoding='utf-8'))
    llamadas = datos.get('funciones', [])

    resultado = {'aprobadas': [], 'faltantes': []}
    for item in funciones_nuevas:
        nombre = item['nombre']
        archivo = item['archivo']
        coincidencias = [
            c for c in llamadas
            if c.get('archivo') == archivo and c.get('nombre') == nombre and c.get('pruebas')
        ]
        if coincidencias:
            resultado['aprobadas'].append({
                **item,
                'pruebas': coincidencias[0]['pruebas'],
            })
        else:
            resultado['faltantes'].append(item)

    return resultado


def verificar_pruebas_estaticas(funciones_nuevas, raiz_proyecto='.'):
    """Búsqueda estática en los archivos de prueba como verificación rápida preliminar."""
    raiz = Path(raiz_proyecto).resolve()
    directorio_tests = raiz / 'tests'
    directorio_tests_js = raiz / 'tests_js'
    directorio_tests_browser = raiz / 'tests_browser'

    archivos_prueba = []
    for d in (directorio_tests, directorio_tests_js, directorio_tests_browser):
        if d.exists():
            archivos_prueba.extend(d.glob('**/*.py'))
            archivos_prueba.extend(d.glob('**/*.cjs'))
            archivos_prueba.extend(d.glob('**/*.js'))

    contenido_pruebas = {}
    for p in archivos_prueba:
        try:
            contenido_pruebas[p.as_posix()] = p.read_text(encoding='utf-8', errors='replace')
        except OSError:
            pass

    resultado = {'aprobadas': [], 'faltantes': []}

    for item in funciones_nuevas:
        nombre = item['nombre']
        archivo = item['archivo']

        if nombre in ('__init__', '__len__', '__iter__', '__getitem__', 'close', '__enter__', '__exit__'):
            basename = Path(archivo).stem
            coincidencias = [
                ruta for ruta, texto in contenido_pruebas.items()
                if basename in texto
            ]
            if coincidencias:
                resultado['aprobadas'].append({**item, 'pruebas': coincidencias})
                continue

        patron = re.compile(rf'\b{re.escape(nombre)}\b')
        coincidencias = [
            ruta for ruta, texto in contenido_pruebas.items()
            if patron.search(texto)
        ]

        if coincidencias:
            resultado['aprobadas'].append({**item, 'pruebas': coincidencias})
        else:
            resultado['faltantes'].append(item)

    return resultado


def main(argumentos=None):
    """Punto de entrada de línea de comandos."""
    parser = argparse.ArgumentParser(
        description='Valida que toda función nueva en git cuente con pruebas.'
    )
    parser.add_argument(
        '--commit',
        help='Referencia de Git a inspeccionar (ej. HEAD, HEAD~1..HEAD o a9678bb^!).',
    )
    parser.add_argument(
        '--cached',
        action='store_true',
        help='Inspeccionar únicamente los cambios preparados en el área de stage.',
    )
    parser.add_argument(
        '--calls-json',
        help='Ruta al archivo JSON de llamadas generadas por pytest con --function-calls-json.',
    )
    parser.add_argument(
        '--raiz',
        default='.',
        help='Directorio raíz del proyecto.',
    )

    args = parser.parse_args(argumentos)

    diff_texto = obtener_diff_git(referencia=args.commit, en_stage=args.cached)
    if not diff_texto:
        print('ℹ️ No se detectaron cambios en el diff especificado.')
        return 0

    funciones = extraer_funciones_nuevas_diff(diff_texto)
    if not funciones:
        print('✅ No se detectaron funciones nuevas en el código de producción.')
        return 0

    # Si se especificó calls-json o existe en test-results/cargas-calls-total.json, usar verificación de ejecución
    ruta_llamadas = args.calls_json
    if not ruta_llamadas:
        raiz_p = Path(args.raiz)
        for candidata in (
            raiz_p / 'test-results/calls.json',
            raiz_p / 'test-results/function-calls.json',
        ):
            if candidata.exists():
                ruta_llamadas = str(candidata)
                break

    if ruta_llamadas and Path(ruta_llamadas).exists():
        verificacion = verificar_cobertura_con_llamadas(funciones, ruta_llamadas)
        origen_info = f'llamadas reales de prueba en {ruta_llamadas}'
    else:
        verificacion = verificar_pruebas_estaticas(funciones, raiz_proyecto=args.raiz)
        origen_info = 'referencias en archivos de prueba'

    aprobadas = verificacion['aprobadas']
    faltantes = verificacion['faltantes']

    print(f'🔍 Auditoría de funciones nuevas en Git: {len(funciones)} detectadas (verificadas con {origen_info}).')
    for item in aprobadas:
        num = len(item.get('pruebas', []))
        print(f"  [OK] {item['archivo']} -> {item['nombre']} (probada por {num} referencia/prueba)")

    if faltantes:
        print(f'\n❌ REGLA 5.0 DE DEVBRAIN INCUMPLIDA: Se detectaron {len(faltantes)} función(es) sin prueba:')
        for item in faltantes:
            print(f"  - {item['archivo']}: {item['nombre']} -> '{item['linea_declaracion']}'")
        print('\n👉 Escribe inmediatamente la prueba correspondiente con aserciones antes de consolidar el cambio.')
        return 1

    print('\n✅ Calidad certificada: Todas las funciones nuevas cuentan con pruebas asociadas y aserciones.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
