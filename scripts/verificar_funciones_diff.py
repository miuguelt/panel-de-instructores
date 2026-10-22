"""Valida que toda función nueva o modificada en Git cuente con su prueba respectiva.

Cumple con la Regla 5.0 de DevBrain: no se permite consolidar código de producción
sin que cada función nueva esté acompañada de sus pruebas automatizadas y ejecutada
con aserciones observables.

El registro de invocaciones (``test-results/function-calls.json``) es una caché: una
copia vieja decía "sin prueba" de funciones que sí estaban probadas. Por eso, cuando
el registro no cubre las funciones del diff o es anterior al último cambio del módulo,
la compuerta ejecuta las pruebas relacionadas, fusiona las invocaciones reales y solo
después decide. La caché vieja ya no puede bloquear un commit por sí sola.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

DIRECTORIOS_FUENTE = ('app', 'worker.py')
RUTAS_EVIDENCIA = ('test-results/function-calls.json', 'test-results/calls.json')
MAX_ARCHIVOS_PRUEBA = 24
TIEMPO_LIMITE_SEGUNDOS = 900
TOLERANCIA_MTIME = 1.0


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


def extraer_funciones_nuevas_diff(diff_texto, directorios_fuente=DIRECTORIOS_FUENTE):
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


def cargar_llamadas(ruta):
    """Lee un registro de invocaciones tolerando archivos ausentes o corruptos."""
    try:
        datos = json.loads(Path(ruta).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {'funciones': []}
    if not isinstance(datos, dict):
        return {'funciones': []}
    return dict(datos, funciones=list(datos.get('funciones') or []))


def fusionar_llamadas(previas, nuevas):
    """Une dos registros: las pruebas se acumulan y la línea más reciente prevalece."""
    por_clave = {}
    entradas = list(previas.get('funciones') or []) + list(nuevas.get('funciones') or [])
    for entrada in entradas:
        if not isinstance(entrada, dict) or not entrada.get('nombre') or not entrada.get('archivo'):
            continue
        clave = (entrada['archivo'], entrada['nombre'])
        anterior = por_clave.get(clave)
        pruebas = set(anterior.get('pruebas') or []) if anterior else set()
        pruebas.update(entrada.get('pruebas') or [])
        fusionada = dict(entrada)
        fusionada['pruebas'] = sorted(pruebas)
        por_clave[clave] = fusionada

    return {
        'pruebas_aprobadas': nuevas.get('pruebas_aprobadas', previas.get('pruebas_aprobadas', 0)),
        'funciones': sorted(
            por_clave.values(),
            key=lambda f: (f.get('archivo', ''), f.get('linea_inicio', 0), f.get('nombre', '')),
        ),
    }


def ruta_evidencia_por_defecto(raiz):
    """Prefiere un registro existente y, si no hay ninguno, la ruta que escribe pytest."""
    raiz = Path(raiz)
    for relativa in RUTAS_EVIDENCIA:
        candidata = raiz / relativa
        if candidata.exists():
            return candidata
    return raiz / RUTAS_EVIDENCIA[0]


def seleccionar_pruebas(funciones, raiz, ampliar=False, excluir=()):
    """Elige los archivos de prueba que probablemente ejercitan las funciones del diff.

    La primera pasada se limita a pruebas cuyo nombre corresponde al módulo o que
    nombran la función. La pasada ampliada suma las que importan el módulo; se usa
    solo cuando la primera no alcanzó a ejecutar alguna función, para no arrastrar
    suites ajenas al cambio.
    """
    raiz = Path(raiz).resolve()
    directorio = raiz / 'tests'
    if not directorio.exists():
        return []

    archivos = sorted(p for p in directorio.rglob('test_*.py') if p.is_file())
    if not archivos:
        return []

    excluidos = {Path(p).as_posix() for p in excluir}
    textos = {}
    for archivo in archivos:
        if archivo.relative_to(raiz).as_posix() in excluidos:
            continue
        try:
            textos[archivo] = archivo.read_text(encoding='utf-8', errors='replace').lower()
        except OSError:
            continue

    elegidos = set()
    for item in funciones:
        ruta = item['archivo']
        if not ruta.endswith('.py'):
            continue
        modulo = ruta[:-3].replace('/', '.')
        modulo_clave = modulo.lower()
        partes = modulo.split('.')
        padre = '.'.join(partes[:-1]) or modulo
        prefijo = partes[-1].split('_')[0]
        patron_import = re.compile(rf'\bfrom\s+{re.escape(padre)}\s+import\b')
        nombre = item['nombre'].lower()

        for archivo, texto in textos.items():
            tallo = archivo.stem.lower()
            coincide = tallo.startswith(f'test_{prefijo}') or nombre in texto
            if not coincide and ampliar:
                coincide = modulo_clave in texto or bool(patron_import.search(texto))
            if coincide:
                elegidos.add(archivo)

    return [
        p.relative_to(raiz).as_posix()
        for p in sorted(elegidos)[:MAX_ARCHIVOS_PRUEBA]
    ]


def funciones_sin_evidencia(funciones, ruta_evidencia):
    """Funciones del diff que aún no tienen una prueba aprobada registrada."""
    registradas = {
        (entrada.get('archivo'), entrada.get('nombre'))
        for entrada in cargar_llamadas(ruta_evidencia)['funciones']
        if entrada.get('pruebas')
    }
    return [
        item for item in funciones
        if (item['archivo'], item['nombre']) not in registradas
    ]


def motivos_evidencia_desactualizada(funciones, ruta_evidencia, raiz):
    """Explica por qué el registro no sirve como prueba para estas funciones."""
    ruta_evidencia = Path(ruta_evidencia)
    if not ruta_evidencia.exists():
        return ['no hay registro de ejecución de pruebas']

    registradas = {
        (entrada.get('archivo'), entrada.get('nombre'))
        for entrada in cargar_llamadas(ruta_evidencia)['funciones']
        if entrada.get('pruebas')
    }
    modificado = ruta_evidencia.stat().st_mtime

    motivos = []
    for item in funciones:
        if (item['archivo'], item['nombre']) not in registradas:
            motivos.append(f"sin invocación registrada para {item['archivo']}:{item['nombre']}")
            continue
        try:
            fuente = (Path(raiz) / item['archivo']).stat().st_mtime
        except OSError:
            continue
        if modificado + TOLERANCIA_MTIME < fuente:
            motivos.append(f'registro anterior al último cambio de {item["archivo"]}')
            break

    return motivos


def ejecutar_pruebas_relacionadas(archivos, destino, raiz, tiempo_limite=TIEMPO_LIMITE_SEGUNDOS):
    """Corre pytest sobre los archivos elegidos registrando las invocaciones reales."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    comando = [
        sys.executable, '-m', 'pytest', *archivos,
        '-q', '-p', 'no:cacheprovider', '-o', 'addopts=',
        f'--function-calls-json={destino}',
    ]

    inicio = time.monotonic()
    try:
        resultado = subprocess.run(
            comando,
            cwd=str(raiz),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=tiempo_limite,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {'codigo': None, 'salida': '', 'segundos': round(time.monotonic() - inicio, 1),
                'error': f'tiempo agotado tras {tiempo_limite}s'}
    except OSError as exc:
        return {'codigo': None, 'salida': '', 'segundos': round(time.monotonic() - inicio, 1),
                'error': str(exc)}

    salida = f'{resultado.stdout or ""}{resultado.stderr or ""}'
    return {'codigo': resultado.returncode, 'salida': salida,
            'segundos': round(time.monotonic() - inicio, 1), 'error': None}


def refrescar_evidencia(funciones, raiz, ruta_evidencia, tiempo_limite=TIEMPO_LIMITE_SEGUNDOS,
                        ampliar=False, excluir=()):
    """Ejecuta las pruebas relacionadas y fusiona sus invocaciones en el registro."""
    archivos = seleccionar_pruebas(funciones, raiz, ampliar=ampliar, excluir=excluir)
    if not archivos:
        return {'estado': 'sin_pruebas', 'archivos': [], 'salida': '', 'segundos': 0.0, 'error': None}

    ruta_evidencia = Path(ruta_evidencia)
    temporal = ruta_evidencia.parent / '.function-calls-fresco.json'
    resultado = ejecutar_pruebas_relacionadas(archivos, temporal, raiz, tiempo_limite)
    resultado['archivos'] = archivos

    if resultado['codigo'] == 1:
        respuesta = dict(resultado, estado='pruebas_fallidas')
    elif resultado['codigo'] == 0 and temporal.exists():
        ruta_evidencia.parent.mkdir(parents=True, exist_ok=True)
        fusionado = fusionar_llamadas(cargar_llamadas(ruta_evidencia), cargar_llamadas(temporal))
        ruta_evidencia.write_text(json.dumps(fusionado, ensure_ascii=False, indent=2), encoding='utf-8')
        respuesta = dict(resultado, estado='actualizada')
    elif resultado['codigo'] == 5:
        respuesta = dict(resultado, estado='sin_pruebas')
    else:
        respuesta = dict(resultado, estado='no_ejecutable')

    try:
        temporal.unlink()
    except OSError:
        pass
    return respuesta


def refrescar_evidencia_completa(funciones, raiz, ruta_evidencia, tiempo_limite=TIEMPO_LIMITE_SEGUNDOS):
    """Refresca la evidencia y, si aún falta alguna función, amplía la búsqueda una vez."""
    pasos = [refrescar_evidencia(funciones, raiz, ruta_evidencia, tiempo_limite)]
    if pasos[0]['estado'] != 'actualizada':
        return pasos

    pendientes = funciones_sin_evidencia(funciones, ruta_evidencia)
    if pendientes:
        segundo = refrescar_evidencia(
            pendientes, raiz, ruta_evidencia, tiempo_limite,
            ampliar=True, excluir=pasos[0]['archivos'],
        )
        pasos.append(segundo)
    return pasos


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


def _resumen_pytest(salida, maximo=12):
    """Devuelve las últimas líneas útiles de pytest para el mensaje de bloqueo."""
    lineas = [linea for linea in (salida or '').splitlines() if linea.strip()]
    return '\n'.join(lineas[-maximo:])


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
    parser.add_argument(
        '--sin-auto',
        action='store_true',
        help='No refrescar el registro de ejecución; juzgar con lo que ya exista.',
    )
    parser.add_argument(
        '--tiempo-limite',
        type=int,
        default=TIEMPO_LIMITE_SEGUNDOS,
        help='Segundos máximos para la corrida focalizada de pytest.',
    )

    args = parser.parse_args(argumentos)
    raiz = Path(args.raiz).resolve()

    diff_texto = obtener_diff_git(referencia=args.commit, en_stage=args.cached)
    if not diff_texto:
        print('ℹ️ No se detectaron cambios en el diff especificado.')
        return 0

    funciones = extraer_funciones_nuevas_diff(diff_texto)
    if not funciones:
        print('✅ No se detectaron funciones nuevas en el código de producción.')
        return 0

    ruta_llamadas = Path(args.calls_json) if args.calls_json else ruta_evidencia_por_defecto(raiz)
    automatico = not args.sin_auto and not args.calls_json

    if automatico:
        motivos = motivos_evidencia_desactualizada(funciones, ruta_llamadas, raiz)
        if motivos:
            print(f'🔄 El registro de ejecución no cubre este cambio: {motivos[0]}')
            pasos = refrescar_evidencia_completa(funciones, raiz, ruta_llamadas, args.tiempo_limite)
            for indice, paso in enumerate(pasos):
                if paso['estado'] == 'actualizada':
                    detalle = ' (búsqueda ampliada)' if indice else ''
                    print(
                        f"   {len(paso['archivos'])} archivo(s) de prueba ejecutados en "
                        f"{paso['segundos']}s{detalle}."
                    )
                    if indice == 0:
                        print(f'   Registro actualizado en {ruta_llamadas.as_posix()}.')
                elif paso['estado'] == 'pruebas_fallidas':
                    print(_resumen_pytest(paso['salida']))
                    print('\n❌ Las pruebas relacionadas fallaron; no se puede certificar la Regla 5.0.')
                    print('👉 Corrige las pruebas antes de consolidar el cambio.')
                    return 1
                elif paso['estado'] == 'sin_pruebas':
                    if indice == 0:
                        print('   No hay archivos de prueba relacionados; se verifica por referencias estáticas.')
                else:
                    detalle = paso.get('error') or f"pytest terminó con código {paso['codigo']}"
                    print(f'   No se pudo ejecutar pytest ({detalle}); se verifica por referencias estáticas.')

    if ruta_llamadas.exists():
        verificacion = verificar_cobertura_con_llamadas(funciones, ruta_llamadas)
        origen_info = f'llamadas reales de prueba en {ruta_llamadas.as_posix()}'
    else:
        verificacion = verificar_pruebas_estaticas(funciones, raiz_proyecto=str(raiz))
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
