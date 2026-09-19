"""Servicio de cálculo y verificación de días festivos en Colombia.

Implementa la Ley 51 de 1983 (Ley Emiliani) para trasladar días feriados
al lunes siguiente, así como los días feriados inamovibles y los dependientes
del Domingo de Resurrección (Pascua).
"""

from datetime import date, timedelta
from functools import lru_cache


def calcular_pascua(anio: int) -> date:
    """Calcula el Domingo de Resurrección (Pascua) para un año gregoriano.

    Utiliza el algoritmo de Butcher / Meeus para determinar la fecha exacta.
    """
    a = anio % 19
    b = anio // 100
    c = anio % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(anio, mes, dia)


def trasladar_lunes(fecha_origen: date) -> date:
    """Aplica la Ley Emiliani: si no es lunes, se traslada al siguiente lunes."""
    if fecha_origen.weekday() == 0:
        return fecha_origen
    dias_faltantes = 7 - fecha_origen.weekday()
    return fecha_origen + timedelta(days=dias_faltantes)


@lru_cache(maxsize=32)
def obtener_festivos_colombia(anio: int) -> dict[date, str]:
    """Retorna un diccionario {fecha: nombre_festivo} con los festivos de Colombia para el año dado."""
    festivos: dict[date, str] = {}

    # 1. Festivos con fecha fija (inamovibles)
    festivos[date(anio, 1, 1)] = 'Año Nuevo'
    festivos[date(anio, 5, 1)] = 'Día del Trabajo'
    festivos[date(anio, 7, 20)] = 'Día de la Independencia'
    festivos[date(anio, 8, 7)] = 'Batalla de Boyacá'
    festivos[date(anio, 12, 8)] = 'Inmaculada Concepción'
    festivos[date(anio, 12, 25)] = 'Navidad'

    # 2. Festivos con fecha base fija pero trasladados al siguiente lunes (Ley Emiliani)
    festivos[trasladar_lunes(date(anio, 1, 6))] = 'Reyes Magos'
    festivos[trasladar_lunes(date(anio, 3, 19))] = 'San José'
    festivos[trasladar_lunes(date(anio, 6, 29))] = 'San Pedro y San Pablo'
    festivos[trasladar_lunes(date(anio, 8, 15))] = 'Asunción de la Virgen'
    festivos[trasladar_lunes(date(anio, 10, 12))] = 'Día de la Raza'
    festivos[trasladar_lunes(date(anio, 11, 1))] = 'Todos los Santos'
    festivos[trasladar_lunes(date(anio, 11, 11))] = 'Independencia de Cartagena'

    # 3. Festivos relativos a la Pascua (Semana Santa y celebraciones católicas)
    pascua = calcular_pascua(anio)
    festivos[pascua - timedelta(days=3)] = 'Jueves Santo'
    festivos[pascua - timedelta(days=2)] = 'Viernes Santo'
    # Ascensión del Señor: Pascua + 39 días, trasladado al siguiente lunes (+43 días)
    festivos[trasladar_lunes(pascua + timedelta(days=43))] = 'Ascensión del Señor'
    # Corpus Christi: Pascua + 60 días, trasladado al siguiente lunes (+64 días)
    festivos[trasladar_lunes(pascua + timedelta(days=64))] = 'Corpus Christi'
    # Sagrado Corazón de Jesús: Pascua + 68 días, trasladado al siguiente lunes (+71 días)
    fecha_sc = trasladar_lunes(pascua + timedelta(days=71))
    if fecha_sc in festivos:
        festivos[fecha_sc] = f"{festivos[fecha_sc]} / Sagrado Corazón de Jesús"
    else:
        festivos[fecha_sc] = 'Sagrado Corazón de Jesús'

    return festivos


def es_festivo_colombia(fecha_consulta: date) -> bool:
    """Determina si una fecha específica corresponde a un día festivo en Colombia."""
    if not isinstance(fecha_consulta, date):
        return False
    festivos = obtener_festivos_colombia(fecha_consulta.year)
    return fecha_consulta in festivos


def nombre_festivo_colombia(fecha_consulta: date) -> str | None:
    """Devuelve el nombre del día festivo en Colombia si corresponde, o None."""
    if not isinstance(fecha_consulta, date):
        return None
    festivos = obtener_festivos_colombia(fecha_consulta.year)
    return festivos.get(fecha_consulta)


def es_dia_habil(fecha_consulta: date) -> bool:
    """Verifica si una fecha es un día laboral/académico (lunes a viernes y no festivo)."""
    if not isinstance(fecha_consulta, date):
        return False
    if fecha_consulta.weekday() >= 5:
        return False
    return not es_festivo_colombia(fecha_consulta)
