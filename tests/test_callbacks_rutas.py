"""Orden visible de la equidad de aseo a partir de historial persistido."""

from datetime import date, timedelta
from html.parser import HTMLParser

from flask import current_app, g
import pytest

from app import db
from app.models import Instructor, RegistroAsistencia, SesionAsistencia
from app.services.festivos import es_festivo_colombia
from tests.test_aseo_equidad import grupo, fechas_futuras, registrar_turno


class TablaEquidad(HTMLParser):
    """Lee las celdas que recibe la persona en la tabla de equidad."""

    def __init__(self):
        super().__init__()
        self.en_tabla = False
        self.filas = []
        self.fila = {}
        self.etiqueta = None
        self.textos = []

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if tag == 'table' and 'equity-table' in atributos.get('class', '').split():
            self.en_tabla = True
        if not self.en_tabla:
            return
        if tag == 'tr':
            self.fila = {}
        if tag == 'td':
            etiqueta = atributos.get('data-label')
            self.etiqueta = etiqueta if etiqueta in {
                'Aprendiz', 'En periodo', 'Total', 'Última vez', 'Próxima',
            } else None
            self.textos = []

    def handle_data(self, data):
        if self.en_tabla and self.etiqueta:
            self.textos.append(data)

    def handle_endtag(self, tag):
        if not self.en_tabla:
            return
        if tag == 'td' and self.etiqueta:
            self.fila[self.etiqueta] = ' '.join(''.join(self.textos).split())
            self.etiqueta = None
        if tag == 'tr' and 'Aprendiz' in self.fila:
            self.filas.append(self.fila)
        if tag == 'table':
            self.en_tabla = False


@pytest.fixture
def tablero_equidad(grupo):
    ficha, aprendices = grupo
    # Los apellidos, las cantidades y las fechas producen cinco órdenes distintos.
    for aprendiz, apellido in zip(aprendices, ('Zulu', 'Alfa', 'Omega', 'Beta', 'Delta', 'Gamma')):
        aprendiz.apellidos = apellido
    mes = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    dias_habiles = []
    fecha = mes
    while len(dias_habiles) < 2:
        if fecha.weekday() < 5 and not es_festivo_colombia(fecha):
            dias_habiles.append(fecha)
        fecha += timedelta(days=1)
    primera, segunda = dias_habiles
    antigua = mes - timedelta(days=10)
    anterior = mes - timedelta(days=5)
    historiales = [
        (antigua, (0, 4)), (anterior, (0, 1)),
        (primera, (0, 2)), (segunda, (2, 3)),
    ]
    proximas = fechas_futuras(3)
    programaciones = [(proximas[0], (2, 0)), (proximas[1], (1, 3)), (proximas[2], (4, 0))]
    for fecha, indices in historiales:
        registrar_turno(ficha, aprendices, fecha, indices, completado_1=True, completado_2=True)
    for fecha, indices in programaciones:
        registrar_turno(ficha, aprendices, fecha, indices, estado='programado')
    for fecha, _ in historiales + programaciones:
        sesion = SesionAsistencia(ficha_id=ficha.id, fecha=fecha)
        db.session.add(sesion)
        db.session.flush()
        db.session.add_all([
            RegistroAsistencia(sesion_id=sesion.id, aprendiz_id=aprendiz.id, estado='ASISTE')
            for aprendiz in aprendices
        ])
    db.session.commit()
    ultimas = [primera, anterior, segunda, segunda, antigua, None]
    siguientes = [proximas[0], proximas[1], proximas[0], proximas[1], proximas[2], None]
    periodos = [1, 0, 2, 1, 0, 0]
    totales = [3, 1, 2, 1, 1, 0]
    filas = [
        {
            'Aprendiz': aprendiz.nombre_completo,
            'En periodo': str(periodos[indice]),
            'Total': str(totales[indice]),
            'Última vez': ultimas[indice].strftime('%d/%m/%Y') if ultimas[indice] else 'Nunca',
            'Próxima': siguientes[indice].strftime('%d/%m/%Y') if siguientes[indice] else 'Sin programar',
        }
        for indice, aprendiz in enumerate(aprendices)
    ]
    return ficha, aprendices, mes, filas


@pytest.mark.parametrize('vista', ['instructor', 'gestion_aprendiz', 'transparencia'])
@pytest.mark.parametrize('criterio,indices', [
    ('nombre', [1, 3, 4, 5, 2, 0]),
    ('periodo', [5, 4, 1, 3, 0, 2]),
    ('ultima', [5, 4, 1, 0, 3, 2]),
    ('proxima', [2, 0, 1, 3, 4, 5]),
    ('veces', [5, 4, 1, 3, 2, 0]),
])
def test_equidad_ordena_filas_y_conserva_metricas_visibles(tablero_equidad, vista, criterio, indices):
    ficha, aprendices, mes, filas = tablero_equidad
    cliente = current_app.test_client()
    g.pop('_login_user', None)
    with cliente.session_transaction() as sesion:
        if vista == 'instructor':
            instructor = db.session.get(Instructor, ficha.instructor_id)
            sesion['_user_id'] = instructor.get_id()
            sesion['_fresh'] = True
        else:
            sesion['aprendiz_documento'] = aprendices[0].documento
            sesion['aprendiz_ficha_id'] = ficha.id
    if vista == 'instructor':
        ruta = f'/instructor/fichas/{ficha.id}/turnos-aseo'
    elif vista == 'gestion_aprendiz':
        ruta = f'/aprendiz/{ficha.id}/turnos-aseo/gestionar'
    else:
        ruta = f'/aprendiz/{ficha.id}/turnos-aseo'

    respuesta = cliente.get(ruta, query_string={'mes': mes.strftime('%Y-%m'), 'orden': criterio})

    assert respuesta.status_code == 200
    tabla = TablaEquidad()
    tabla.feed(respuesta.get_data(as_text=True))
    assert tabla.filas == [filas[indice] for indice in indices]
    assert len(tabla.filas) == len(aprendices)
    assert filas[5]['Última vez'] == 'Nunca'
    assert filas[5]['Próxima'] == 'Sin programar'
