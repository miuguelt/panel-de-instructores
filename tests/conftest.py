"""Aísla los servicios de prueba y registra invocaciones reales de producción."""

import json
import os
from pathlib import Path
import secrets
import sys

import pytest


# Los procesos auxiliares de la suite tampoco deben abrir la base operativa.
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['REDIS_URL'] = ''
if not (os.environ.get('SECRET_KEY') or '').strip():
    os.environ['SECRET_KEY'] = secrets.token_hex(64)


class RegistroFunciones:
    """Registra llamadas, sin copiar argumentos, resultados ni datos personales."""

    def __init__(self, raiz):
        self.raiz = Path(raiz).resolve()
        self.app = os.path.normcase(str(self.raiz / 'app')) + os.sep
        self.runtime = {os.path.normcase(str(self.raiz / nombre)) for nombre in
                        ('config.py', 'worker.py', 'wsgi.py', 'seed_admin.py', 'warmup.py')}
        self.codigos = {}
        self.funciones = {}
        self.actuales = set()
        self.pruebas = set()

    def perfilar(self, frame, evento, _argumento):
        if evento != 'call':
            return
        codigo = frame.f_code
        if codigo not in self.codigos:
            archivo = os.path.normcase(os.path.abspath(codigo.co_filename))
            if not (archivo.startswith(self.app) or archivo in self.runtime):
                self.codigos[codigo] = None
            else:
                relativa = Path(codigo.co_filename).resolve().relative_to(self.raiz).as_posix()
                posiciones = sorted({pos for pos in codigo.co_positions()
                                     if pos[2] is not None and pos[3] is not None and pos[3] > pos[2]}) if codigo.co_name == '<lambda>' else []
                clave = (relativa, codigo.co_firstlineno, codigo.co_name, tuple(posiciones))
                self.codigos[codigo] = clave
                self.funciones.setdefault(clave, {'archivo': relativa, 'linea_inicio': codigo.co_firstlineno,
                    'nombre': codigo.co_name, 'posiciones': posiciones, 'pruebas': set()})
        clave = self.codigos[codigo]
        if clave is not None:
            self.actuales.add(clave)

    def confirmar(self, identificador):
        self.pruebas.add(identificador)
        for clave in self.actuales:
            self.funciones[clave]['pruebas'].add(identificador)

    def guardar(self, destino):
        funciones = [dict(funcion, pruebas=sorted(funcion['pruebas']))
                     for funcion in self.funciones.values() if funcion['pruebas']]
        reporte = {'pruebas_aprobadas': len(self.pruebas),
                   'funciones': sorted(funciones, key=lambda f: (f['archivo'], f['linea_inicio'], f['nombre']))}
        ruta = Path(destino)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding='utf-8')


def pytest_addoption(parser):
    parser.addoption('--function-calls-json', default=None,
                     help='Registra funciones y callbacks realmente invocados por pruebas aprobadas.')


def pytest_configure(config):
    config.registro_funciones = RegistroFunciones(config.rootpath) if config.getoption('--function-calls-json') else None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    registro = item.config.registro_funciones
    if registro is None:
        yield
        return
    registro.actuales = set()
    anterior = sys.getprofile()
    sys.setprofile(registro.perfilar)
    try:
        yield
    finally:
        sys.setprofile(anterior)
    informes = getattr(item, 'informes_funciones', {})
    if informes.get('call') == 'passed' and all(resultado == 'passed' for resultado in informes.values()):
        registro.confirmar(item.nodeid)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    resultado = yield
    informe = resultado.get_result()
    if not hasattr(item, 'informes_funciones'):
        item.informes_funciones = {}
    item.informes_funciones[informe.when] = informe.outcome


def pytest_sessionfinish(session, exitstatus):
    registro = session.config.registro_funciones
    if registro is not None:
        registro.guardar(session.config.getoption('--function-calls-json'))
