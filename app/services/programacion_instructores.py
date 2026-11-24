"""Programación de instructores por coordinación: asignaciones, choques, ocupación y alertas.

Una asignación ubica a un instructor en una competencia de una ficha durante un rango de
fechas, ciertos días de la semana y una jornada. La ocupación cuenta los días hábiles
(lunes a viernes sin festivos) que tienen al menos una asignación; el sábado se muestra,
pero no entra en el porcentaje porque no es un día de formación obligatorio.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy.orm import joinedload

from app import db
from app.models.ficha import Ficha
from app.models.instructor import Instructor
from app.models.juicio import FichaCompetenciaProgramacion, JuicioEvaluativo
from app.models.programacion import (
    DIAS_SEMANA, JORNADAS, MASCARA_MAXIMA, AsignacionProgramacion,
)
from app.services.festivos import es_dia_habil, es_festivo_colombia, nombre_festivo_colombia
from app.services.importacion_ficha import clasificar_competencia
from app.services.programacion_competencias import guardar_programacion_competencia

MAX_DIAS_ASIGNACION = 366

NIVEL_SIN_PROGRAMACION = 'sin_programacion'
NIVEL_PARCIAL = 'parcial'
NIVEL_COMPLETO = 'completo'
NIVEL_SIN_DIAS_HABILES = 'sin_dias_habiles'

ETIQUETAS_NIVEL = {
    NIVEL_SIN_PROGRAMACION: 'Sin programación',
    NIVEL_PARCIAL: 'Días libres',
    NIVEL_COMPLETO: 'Programado',
    NIVEL_SIN_DIAS_HABILES: 'Sin días hábiles',
}


# --- Utilidades de fecha y máscara ---

def lunes_de(fecha: date) -> date:
    return fecha - timedelta(days=fecha.weekday())


def parsear_fecha(valor: Any) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = (valor or '').strip() if isinstance(valor, str) else ''
    if not texto:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def mascara_desde_dias(valores: Iterable[Any]) -> int:
    """Convierte índices de día (0=lunes ... 5=sábado) en máscara; ignora valores inválidos."""
    mascara = 0
    for valor in valores or ():
        try:
            dia = int(valor)
        except (TypeError, ValueError):
            continue
        if 0 <= dia <= 5:
            mascara |= 1 << dia
    return mascara


def dias_desde_mascara(mascara: int) -> list[int]:
    return [bit for bit, _, _ in DIAS_SEMANA if mascara & (1 << bit)]


def es_dia_laborable(fecha: date) -> bool:
    """Lunes a viernes sin festivos: base del porcentaje de ocupación."""
    return fecha.weekday() < 5 and es_dia_habil(fecha)


def fechas_de_asignacion(asignacion, desde: date | None = None, hasta: date | None = None) -> list[date]:
    """Fechas concretas en que se dicta la asignación (sin domingos ni festivos)."""
    inicio = max(asignacion.fecha_inicio, desde) if desde else asignacion.fecha_inicio
    fin = min(asignacion.fecha_fin, hasta) if hasta else asignacion.fecha_fin
    fechas = []
    actual = inicio
    while actual <= fin:
        dia = actual.weekday()
        if dia <= 5 and asignacion.dias_semana & (1 << dia) and not es_festivo_colombia(actual):
            fechas.append(actual)
        actual += timedelta(days=1)
    return fechas


# --- Validación y persistencia ---

class ErrorProgramacion(ValueError):
    """Error de validación con un mensaje listo para mostrar."""


# --- Equipos ejecutores y competencias transversales ---

TIPO_TECNICA = 'tecnica'
TIPO_TRANSVERSAL = 'transversal'
TIPO_INGLES = 'ingles'
# Inglés lo orientan instructores de bilingüismo de otras áreas: cuenta como transversal.
TIPOS_ENTRE_EQUIPOS = {TIPO_TRANSVERSAL, TIPO_INGLES}


def tipo_de_competencia(ficha_id: int, competencia: str) -> str:
    """Tipo registrado en los juicios de la ficha; si no hay, se clasifica por el nombre."""
    registrado = (db.session.query(JuicioEvaluativo.tipo_competencia)
                  .filter(JuicioEvaluativo.ficha_id == ficha_id,
                          JuicioEvaluativo.competencia == competencia,
                          JuicioEvaluativo.tipo_competencia.isnot(None))
                  .limit(1).scalar())
    tipo = registrado or clasificar_competencia(competencia)
    return tipo if tipo in (TIPO_TECNICA, TIPO_TRANSVERSAL, TIPO_INGLES) else TIPO_TECNICA


def es_transversal(ficha_id: int, competencia: str) -> bool:
    return tipo_de_competencia(ficha_id, competencia) in TIPOS_ENTRE_EQUIPOS


def es_cruce_de_equipo(instructor: Instructor, ficha: Ficha) -> bool:
    """La ficha tiene equipo ejecutor y el instructor no pertenece a él."""
    return bool(ficha.equipo_id) and instructor.equipo_id != ficha.equipo_id


def validar_cruce_de_equipo(instructor: Instructor, ficha: Ficha, competencia: str) -> None:
    """Entre equipos ejecutores distintos solo se programan competencias transversales."""
    if not es_cruce_de_equipo(instructor, ficha) or es_transversal(ficha.id, competencia):
        return
    equipo = ficha.equipo.nombre if ficha.equipo else 'de la ficha'
    raise ErrorProgramacion(
        f'{instructor.nombre} no pertenece al equipo ejecutor {equipo}: entre equipos solo se '
        'programan competencias transversales. Programa a alguien de ese equipo o pide a '
        'coordinación que traslade al instructor.')


def validar_datos(datos: dict[str, Any]) -> dict[str, Any]:
    """Normaliza y valida los datos del formulario; lanza ErrorProgramacion si algo falla."""
    try:
        instructor_id = int(datos.get('instructor_id') or 0)
        ficha_id = int(datos.get('ficha_id') or 0)
    except (TypeError, ValueError):
        instructor_id = ficha_id = 0
    competencia = ' '.join(str(datos.get('competencia') or '').split())
    fecha_inicio = parsear_fecha(datos.get('fecha_inicio'))
    modo = datos.get('modo') or 'semanas'
    fecha_fin = fecha_inicio if modo == 'dia' else parsear_fecha(datos.get('fecha_fin'))
    jornada = datos.get('jornada') or ''
    observacion = ' '.join(str(datos.get('observacion') or '').split())[:300] or None

    instructor = db.session.get(Instructor, instructor_id) if instructor_id else None
    ficha = db.session.get(Ficha, ficha_id) if ficha_id else None
    if not instructor:
        raise ErrorProgramacion('Elige el instructor que vas a programar.')
    if not ficha:
        raise ErrorProgramacion('Elige la ficha donde se orienta la competencia.')
    if not competencia:
        raise ErrorProgramacion('Escribe o elige la competencia.')
    if len(competencia) > 300:
        raise ErrorProgramacion('El nombre de la competencia no puede superar 300 caracteres.')
    if not fecha_inicio:
        raise ErrorProgramacion('Indica la fecha de inicio.')
    if not fecha_fin:
        raise ErrorProgramacion('Indica la fecha de finalización.')
    if fecha_fin < fecha_inicio:
        raise ErrorProgramacion('La fecha de finalización no puede ser anterior a la de inicio.')
    if (fecha_fin - fecha_inicio).days + 1 > MAX_DIAS_ASIGNACION:
        raise ErrorProgramacion('Una asignación no puede superar un año; divídela en varias.')
    if jornada not in JORNADAS:
        raise ErrorProgramacion('Elige la jornada: mañana, tarde o noche.')

    if modo == 'dia':
        if fecha_inicio.weekday() == 6:
            raise ErrorProgramacion('El domingo no se programa formación.')
        dias_semana = 1 << fecha_inicio.weekday()
    else:
        valores = datos.get('dias_semana')
        if isinstance(valores, (str, int)):
            valores = [valores]
        dias_semana = mascara_desde_dias(valores)
        if not dias_semana:
            raise ErrorProgramacion('Marca al menos un día de la semana.')
    dias_semana &= MASCARA_MAXIMA
    validar_cruce_de_equipo(instructor, ficha, competencia)

    return {
        'instructor_id': instructor_id, 'ficha_id': ficha_id, 'competencia': competencia,
        'fecha_inicio': fecha_inicio, 'fecha_fin': fecha_fin, 'dias_semana': dias_semana,
        'jornada': jornada, 'observacion': observacion,
    }


def detectar_choques(datos: dict[str, Any], excluir_id: int | None = None) -> list[tuple[date, AsignacionProgramacion]]:
    """Fechas en que el instructor ya tiene otra asignación en la misma jornada."""
    consulta = AsignacionProgramacion.query.filter(
        AsignacionProgramacion.instructor_id == datos['instructor_id'],
        AsignacionProgramacion.jornada == datos['jornada'],
        AsignacionProgramacion.fecha_inicio <= datos['fecha_fin'],
        AsignacionProgramacion.fecha_fin >= datos['fecha_inicio'],
    )
    if excluir_id:
        consulta = consulta.filter(AsignacionProgramacion.id != excluir_id)
    existentes = consulta.options(joinedload(AsignacionProgramacion.ficha)).all()
    if not existentes:
        return []
    nuevas = set(fechas_de_asignacion(_Rango(datos)))
    choques = []
    for otra in existentes:
        for fecha in fechas_de_asignacion(otra, datos['fecha_inicio'], datos['fecha_fin']):
            if fecha in nuevas:
                choques.append((fecha, otra))
    return sorted(choques, key=lambda par: par[0])


def mensaje_choque(choques: list[tuple[date, AsignacionProgramacion]]) -> str:
    fecha, otra = choques[0]
    ficha = otra.ficha.codigo if otra.ficha else 'otra ficha'
    extra = f' y {len(choques) - 1} día(s) más' if len(choques) > 1 else ''
    return (f'El instructor ya está programado el {fecha.strftime("%d/%m/%Y")} en la jornada de la '
            f'{otra.jornada_etiqueta.lower()} (ficha {ficha}, {otra.competencia[:60]}){extra}. '
            'Cambia la jornada, los días o las fechas.')


def guardar_asignacion(datos: dict[str, Any], creado_por_id: int | None,
                       asignacion: AsignacionProgramacion | None = None) -> AsignacionProgramacion:
    """Valida, comprueba choques, guarda y sincroniza la competencia en Planeación."""
    limpio = validar_datos(datos)
    choques = detectar_choques(limpio, excluir_id=asignacion.id if asignacion else None)
    if choques:
        raise ErrorProgramacion(mensaje_choque(choques))
    if not fechas_de_asignacion(_Rango(limpio)):
        raise ErrorProgramacion('Las fechas y días elegidos no incluyen ningún día hábil.')

    anterior = (asignacion.ficha_id, asignacion.competencia) if asignacion else None
    if asignacion is None:
        asignacion = AsignacionProgramacion(creado_por_id=creado_por_id)
        db.session.add(asignacion)
    for campo, valor in limpio.items():
        setattr(asignacion, campo, valor)
    db.session.commit()

    sincronizar_competencia(asignacion.ficha_id, asignacion.competencia)
    if anterior and anterior != (asignacion.ficha_id, asignacion.competencia):
        sincronizar_competencia(*anterior)
    return asignacion


def eliminar_asignacion(asignacion: AsignacionProgramacion) -> None:
    ficha_id, competencia = asignacion.ficha_id, asignacion.competencia
    db.session.delete(asignacion)
    db.session.commit()
    sincronizar_competencia(ficha_id, competencia)


def sincronizar_competencia(ficha_id: int, competencia: str) -> FichaCompetenciaProgramacion | None:
    """Lleva el rango completo de las asignaciones a la programación de la competencia.

    Si ya no quedan asignaciones, se conserva la programación manual que exista.
    """
    asignaciones = (AsignacionProgramacion.query
                    .filter_by(ficha_id=ficha_id, competencia=competencia)
                    .order_by(AsignacionProgramacion.fecha_inicio, AsignacionProgramacion.id).all())
    if not asignaciones:
        return None
    return guardar_programacion_competencia(
        ficha_id, competencia,
        min(a.fecha_inicio for a in asignaciones),
        max(a.fecha_fin for a in asignaciones),
        instructor_id=asignaciones[0].instructor_id,
    )


class _Rango:
    """Vista mínima de unos datos validados con la forma de una asignación."""

    def __init__(self, datos):
        self.fecha_inicio = datos['fecha_inicio']
        self.fecha_fin = datos['fecha_fin']
        self.dias_semana = datos['dias_semana']


# --- Consultas para el calendario ---

def competencias_de_ficha(ficha_id: int) -> list[dict[str, Any]]:
    """Competencias conocidas de la ficha (juicios, planeación y asignaciones) con su tipo.

    `transversal` indica si se puede programar a un instructor de otro equipo ejecutor.
    """
    nombres = set()
    for modelo in (JuicioEvaluativo, FichaCompetenciaProgramacion, AsignacionProgramacion):
        filas = db.session.query(modelo.competencia).filter(modelo.ficha_id == ficha_id).distinct()
        nombres.update(c for (c,) in filas if c)
    resultado = []
    for nombre in sorted(nombres):
        tipo = tipo_de_competencia(ficha_id, nombre)
        resultado.append({'nombre': nombre, 'tipo': tipo, 'transversal': tipo in TIPOS_ENTRE_EQUIPOS})
    return resultado


def asignaciones_en_rango(instructor_ids: Iterable[int], desde: date, hasta: date) -> list[AsignacionProgramacion]:
    ids = list(instructor_ids)
    if not ids:
        return []
    return (AsignacionProgramacion.query
            .options(joinedload(AsignacionProgramacion.ficha))
            .filter(AsignacionProgramacion.instructor_id.in_(ids),
                    AsignacionProgramacion.fecha_inicio <= hasta,
                    AsignacionProgramacion.fecha_fin >= desde)
            .order_by(AsignacionProgramacion.fecha_inicio, AsignacionProgramacion.jornada).all())


def dias_del_rango(desde: date, hasta: date, incluir_sabado: bool = True) -> list[dict[str, Any]]:
    dias = []
    actual = desde
    while actual <= hasta:
        if actual.weekday() < 5 or (incluir_sabado and actual.weekday() == 5):
            festivo = nombre_festivo_colombia(actual)
            dias.append({
                'fecha': actual, 'festivo': festivo,
                'laborable': es_dia_laborable(actual),
                'nombre': DIAS_SEMANA[actual.weekday()][2],
            })
        actual += timedelta(days=1)
    return dias


def nivel_ocupacion(dias_laborables: int, dias_programados: int) -> str:
    if dias_laborables <= 0:
        return NIVEL_SIN_DIAS_HABILES
    if dias_programados <= 0:
        return NIVEL_SIN_PROGRAMACION
    if dias_programados < dias_laborables:
        return NIVEL_PARCIAL
    return NIVEL_COMPLETO


def porcentaje(parte: int, total: int) -> int | None:
    """Porcentaje entero; None cuando no hay base (se muestra «Sin datos», no 0 %)."""
    if total <= 0:
        return None
    return round(100 * min(parte, total) / total)


def ocupacion(instructores: Iterable[Instructor], desde: date, hasta: date) -> list[dict[str, Any]]:
    """Fila de calendario por instructor con sus asignaciones por día y su nivel de alerta."""
    instructores = list(instructores)
    por_instructor: dict[int, list[AsignacionProgramacion]] = {i.id: [] for i in instructores}
    for asignacion in asignaciones_en_rango(por_instructor, desde, hasta):
        por_instructor[asignacion.instructor_id].append(asignacion)

    laborables = [d['fecha'] for d in dias_del_rango(desde, hasta) if d['laborable']]
    filas = []
    for instructor in instructores:
        celdas: dict[date, list[AsignacionProgramacion]] = {}
        for asignacion in por_instructor[instructor.id]:
            for fecha in fechas_de_asignacion(asignacion, desde, hasta):
                celdas.setdefault(fecha, []).append(asignacion)
        for lista in celdas.values():
            lista.sort(key=lambda a: list(JORNADAS).index(a.jornada))
        programados = sum(1 for fecha in laborables if fecha in celdas)
        libres = [fecha for fecha in laborables if fecha not in celdas]
        nivel = nivel_ocupacion(len(laborables), programados)
        filas.append({
            'instructor': instructor,
            'celdas': celdas,
            'dias_laborables': len(laborables),
            'dias_programados': programados,
            'dias_libres': libres,
            'porcentaje': porcentaje(programados, len(laborables)),
            'nivel': nivel,
            'etiqueta_nivel': ETIQUETAS_NIVEL[nivel],
            'asignaciones': por_instructor[instructor.id],
        })
    return filas


def agrupar_por_equipo(filas: list[dict[str, Any]], equipos_visibles: set[int] | None = None) -> list[dict[str, Any]]:
    """Agrupa las filas por equipo ejecutor con la ocupación media del equipo.

    `equipos_visibles` marca como «de otro equipo» a quien no pertenece a los equipos del líder.
    """
    grupos: OrderedDict[Any, dict[str, Any]] = OrderedDict()
    for fila in sorted(filas, key=lambda f: ((f['instructor'].equipo.nombre if f['instructor'].equipo else '~'),
                                              f['instructor'].nombre)):
        equipo = fila['instructor'].equipo
        clave = equipo.id if equipo else None
        fila['externo'] = equipos_visibles is not None and clave not in equipos_visibles
        grupo = grupos.setdefault(clave, {
            'equipo': equipo, 'nombre': equipo.nombre if equipo else 'Sin equipo asignado',
            'filas': [], 'laborables': 0, 'programados': 0, 'alertas': 0,
        })
        grupo['filas'].append(fila)
        grupo['laborables'] += fila['dias_laborables']
        grupo['programados'] += fila['dias_programados']
        if fila['nivel'] in (NIVEL_SIN_PROGRAMACION, NIVEL_PARCIAL):
            grupo['alertas'] += 1
    resultado = list(grupos.values())
    for grupo in resultado:
        grupo['porcentaje'] = porcentaje(grupo['programados'], grupo['laborables'])
    return resultado


def alertas(filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Instructores sin programación primero, luego con días libres."""
    orden = {NIVEL_SIN_PROGRAMACION: 0, NIVEL_PARCIAL: 1}
    pendientes = [f for f in filas if f['nivel'] in orden]
    return sorted(pendientes, key=lambda f: (orden[f['nivel']], f['instructor'].nombre))


def resumen(filas: list[dict[str, Any]]) -> dict[str, Any]:
    laborables = sum(f['dias_laborables'] for f in filas)
    programados = sum(f['dias_programados'] for f in filas)
    return {
        'instructores': len(filas),
        'sin_programacion': sum(1 for f in filas if f['nivel'] == NIVEL_SIN_PROGRAMACION),
        'con_dias_libres': sum(1 for f in filas if f['nivel'] == NIVEL_PARCIAL),
        'completos': sum(1 for f in filas if f['nivel'] == NIVEL_COMPLETO),
        'porcentaje': porcentaje(programados, laborables),
    }


def instructores_visibles(usuario, desde: date, hasta: date, equipo_id: int | None = None) -> tuple[list[Instructor], set[int] | None]:
    """Instructores que el usuario ve en el calendario y los equipos que le son propios.

    Coordinación ve a todos (o al equipo filtrado). Un líder ve a su equipo y, además, a los
    instructores de otros equipos programados en fichas cuyo responsable es de su equipo.
    El segundo valor es None para coordinación (nadie es «externo»).
    """
    # Quien tiene el perfil de coordinación programa, pero no recibe formación que programar.
    activos = Instructor.query.filter(Instructor.activo.is_(True), Instructor.rol != 'coordinacion')
    if usuario.es_coordinacion:
        if equipo_id:
            activos = activos.filter(Instructor.equipo_id == equipo_id)
        return activos.order_by(Instructor.nombre).all(), None

    propios = {e.id for e in usuario.equipos_liderados}
    if equipo_id and equipo_id in propios:
        propios_filtro = {equipo_id}
    else:
        propios_filtro = propios
    miembros = activos.filter(Instructor.equipo_id.in_(propios_filtro)).all() if propios_filtro else []
    return _con_externos(miembros, propios_filtro, desde, hasta), propios


def _con_externos(miembros: list[Instructor], equipos: set[int], desde: date, hasta: date) -> list[Instructor]:
    """Miembros más los instructores de otros equipos programados en fichas de `equipos`."""
    externos_ids = {
        instructor_id for (instructor_id,) in db.session.query(AsignacionProgramacion.instructor_id)
        .join(Ficha, Ficha.id == AsignacionProgramacion.ficha_id)
        .filter(Ficha.equipo_id.in_(equipos),
                AsignacionProgramacion.fecha_inicio <= hasta,
                AsignacionProgramacion.fecha_fin >= desde)
    } if equipos else set()
    ids_miembros = {i.id for i in miembros}
    externos = [i for i in (db.session.get(Instructor, x) for x in externos_ids - ids_miembros)
                if i and i.activo]
    return sorted(miembros + externos, key=lambda i: i.nombre)


def instructores_del_equipo(equipo_id: int, desde: date, hasta: date) -> list[Instructor]:
    """Vista del equipo en solo lectura: compañeros activos y quienes vienen de otros equipos
    a orientar transversales en las fichas del equipo."""
    miembros = (Instructor.query
                .filter(Instructor.activo.is_(True), Instructor.rol != 'coordinacion',
                        Instructor.equipo_id == equipo_id)
                .order_by(Instructor.nombre).all())
    return _con_externos(miembros, {equipo_id}, desde, hasta)


def asignaciones_fuera_de_equipo(instructor: Instructor, desde: date | None = None) -> list[AsignacionProgramacion]:
    """Asignaciones vigentes o futuras de competencias no transversales en fichas de otro equipo.

    Sirve para avisar a coordinación cuando traslada a un instructor de equipo.
    """
    desde = desde or date.today()
    vigentes = (AsignacionProgramacion.query
                .options(joinedload(AsignacionProgramacion.ficha))
                .filter(AsignacionProgramacion.instructor_id == instructor.id,
                        AsignacionProgramacion.fecha_fin >= desde)
                .order_by(AsignacionProgramacion.fecha_inicio).all())
    return [a for a in vigentes
            if es_cruce_de_equipo(instructor, a.ficha) and not es_transversal(a.ficha_id, a.competencia)]


def contar_alertas_semana(usuario, hoy: date | None = None) -> int:
    """Instructores visibles con días laborables sin programar en la semana actual."""
    lunes = lunes_de(hoy or date.today())
    sabado = lunes + timedelta(days=5)
    instructores, _ = instructores_visibles(usuario, lunes, sabado)
    return len(alertas(ocupacion(instructores, lunes, sabado)))
