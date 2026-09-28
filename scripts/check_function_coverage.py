"""Exige que todas las funciones de la aplicación se ejecuten en las pruebas."""

import argparse
import ast
import xml.etree.ElementTree as ET
from pathlib import Path


def iterar_funciones(raiz_fuente):
    """Devuelve cada función y método con su primera línea ejecutable."""
    raiz_fuente = Path(raiz_fuente).resolve()
    raiz_proyecto = raiz_fuente.parent
    funciones = []

    for ruta in sorted(raiz_fuente.rglob('*.py')):
        arbol = ast.parse(ruta.read_text(encoding='utf-8'), filename=str(ruta))
        ruta_relativa = ruta.relative_to(raiz_proyecto).as_posix()
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            cuerpo = list(nodo.body)
            if (
                cuerpo
                and isinstance(cuerpo[0], ast.Expr)
                and isinstance(cuerpo[0].value, ast.Constant)
                and isinstance(cuerpo[0].value.value, str)
            ):
                cuerpo.pop(0)
            while cuerpo and isinstance(cuerpo[0], (ast.Global, ast.Nonlocal)):
                cuerpo.pop(0)
            if not cuerpo:
                continue

            funciones.append({
                'archivo': ruta_relativa,
                'nombre': nodo.name,
                'linea': nodo.lineno,
                'linea_cuerpo': cuerpo[0].lineno,
            })

    return sorted(funciones, key=lambda funcion: (funcion['archivo'], funcion['linea']))


def lineas_cubiertas(ruta_xml, raiz_fuente=None):
    """Lee las líneas ejecutadas en el reporte Cobertura XML de coverage.py."""
    reporte = ET.parse(ruta_xml).getroot()
    resultado = {}
    fuentes = [Path(fuente.text) for fuente in reporte.findall('./sources/source') if fuente.text]
    proyecto = Path(raiz_fuente).resolve().parent if raiz_fuente else None
    for clase in reporte.findall('.//class'):
        ruta = Path(clase.attrib['filename'])
        candidatas = [ruta] if ruta.is_absolute() else [fuente / ruta for fuente in fuentes]
        if not candidatas:
            candidatas = [ruta]
        archivo = candidatas[0].as_posix()
        if proyecto:
            for candidata in candidatas:
                try:
                    archivo = candidata.resolve().relative_to(proyecto).as_posix()
                    break
                except ValueError:
                    continue
        cubiertas = resultado.setdefault(archivo, set())
        for linea in clase.findall('./lines/line'):
            if int(linea.attrib.get('hits', '0')) > 0:
                cubiertas.add(int(linea.attrib['number']))
    return resultado


def revisar_cobertura_funciones(raiz_fuente, ruta_xml):
    """Retorna el total y las funciones cuyo cuerpo no ejecutó la suite."""
    funciones = iterar_funciones(raiz_fuente)
    cubiertas = lineas_cubiertas(ruta_xml, raiz_fuente)
    pendientes = [
        funcion for funcion in funciones
        if funcion['linea_cuerpo'] not in cubiertas.get(funcion['archivo'], set())
    ]
    return len(funciones), pendientes


def main(argumentos=None):
    parser = argparse.ArgumentParser(
        description='Rechaza funciones de la aplicación sin ejecución en la suite.'
    )
    parser.add_argument('--source', default='app', help='Carpeta de código de producción.')
    parser.add_argument(
        '--coverage-xml', default='coverage.xml', help='Reporte XML generado por pytest-cov.'
    )
    opciones = parser.parse_args(argumentos)

    total, pendientes = revisar_cobertura_funciones(
        opciones.source, opciones.coverage_xml
    )
    cubiertas = total - len(pendientes)
    porcentaje = cubiertas / total * 100 if total else 0
    porcentaje_texto = '100%' if total and cubiertas == total else f'{porcentaje:.1f}%'
    print(f'Cobertura de funciones: {cubiertas}/{total} ({porcentaje_texto}).')

    if not total:
        print('No se encontraron funciones; la compuerta no puede aprobarse.')
        return 1
    if pendientes:
        print('Funciones sin ejecución en pruebas:')
        for funcion in pendientes:
            print(
                f"- {funcion['archivo']}:{funcion['linea']} "
                f"{funcion['nombre']} (cuerpo, línea {funcion['linea_cuerpo']})"
            )
        return 1

    print('Todas las funciones de producción se ejecutaron en la suite.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
