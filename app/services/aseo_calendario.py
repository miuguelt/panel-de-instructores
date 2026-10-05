"""Selección de días permitidos al generar turnos del calendario de aseo."""

DIAS_LABORALES = (0, 1, 2, 3, 4)
OPCIONES_DIAS_SEMANA = (
    (0, 'Lunes'),
    (1, 'Martes'),
    (2, 'Miércoles'),
    (3, 'Jueves'),
    (4, 'Viernes'),
    (5, 'Sábado'),
    (6, 'Domingo'),
)


def normalizar_dias_semana(valores=None):
    """Valida y ordena los días seleccionados; usa lunes a viernes por defecto."""
    if valores is None:
        return DIAS_LABORALES

    seleccionados = set()
    for valor in valores:
        if isinstance(valor, bool):
            raise ValueError('Elige días de la semana válidos entre lunes y domingo.')
        if isinstance(valor, int):
            dia = valor
        elif isinstance(valor, str) and valor.isascii() and valor.isdigit():
            dia = int(valor)
        else:
            raise ValueError('Elige días de la semana válidos entre lunes y domingo.')
        if dia < 0 or dia > 6:
            raise ValueError('Elige días de la semana válidos entre lunes y domingo.')
        seleccionados.add(dia)

    if not seleccionados:
        raise ValueError('Selecciona al menos un día de la semana para programar aseos.')
    return tuple(sorted(seleccionados))
