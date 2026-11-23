"""Ayudantes puros de las páginas de aseo.

El instructor, el aprendiz delegado y la vista de transparencia muestran el
mismo calendario y la misma tabla de equidad. Estas funciones concentran el
orden de esa tabla, su resumen, el mensaje tras calcular turnos y la lectura
de fechas y casillas del formulario, para que las tres páginas no diverjan.
"""

from datetime import date, datetime

MESES = ('', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
         'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre')
VALORES_MARCADOS = ('on', 'true', '1')


def _ultima_vez(fila):
    return fila['contador'].ultima_vez_aseo or date.min


CLAVES_ORDEN = {
    'nombre': lambda f: (f['aprendiz'].apellidos.lower(), f['aprendiz'].nombre.lower()),
    'periodo': lambda f: (f['veces_periodo'], f['veces_total'], _ultima_vez(f)),
    'ultima': _ultima_vez,
    'proxima': lambda f: f['proxima'] or date.max,
    'veces': lambda f: (f['veces_total'], _ultima_vez(f)),
}


def ordenar_equidad(filas, orden):
    """Ordena en su lugar la tabla de equidad; un orden desconocido usa «veces»."""
    filas.sort(key=CLAVES_ORDEN.get(orden, CLAVES_ORDEN['veces']))
    return filas


def resumen_cargas(totales):
    """Diferencia, mínimo, máximo y promedio de turnos comprometidos por aprendiz."""
    if not totales:
        return {'delta': 0, 'minimo': 0, 'maximo': 0, 'promedio': 0}
    minimo, maximo = min(totales), max(totales)
    return {'delta': maximo - minimo, 'minimo': minimo, 'maximo': maximo,
            'promedio': sum(totales) / len(totales)}


def mensaje_generacion(resultado, equilibrados, resumen):
    """(mensaje, categoría) que resume un cálculo de turnos."""
    creados = len(resultado['creados'])
    recalculados = len(resultado.get('recalculados', []))
    eliminados = resultado.get('eliminados', 0)
    partes = [texto for cantidad, texto in (
        (eliminados, f'{eliminados} pendiente(s) eliminado(s)'),
        (creados, f'{creados} nuevo(s)'),
        (recalculados, f'{recalculados} pendiente(s) recalculado(s)'),
        (len(equilibrados), f'{len(equilibrados)} equilibrado(s) fuera del rango'),
        (resultado.get('cumplidos_conservados', 0),
         f'{resultado.get("cumplidos_conservados", 0)} cumplido(s) conservado(s)'),
        (resultado.get('omitidos_manuales', 0), f'{resultado.get("omitidos_manuales", 0)} manual(es) conservado(s)'),
    ) if cantidad]

    sesiones = resultado['sesiones']
    if partes:
        mensaje = f'Cálculo de turnos completado ({", ".join(partes)}) para {sesiones} sesión(es).'
    else:
        mensaje = f'No se requirieron cambios en las {sesiones} sesiones evaluadas.'
    mensaje += (
        f' Equidad resultante: cada aprendiz tiene entre {resumen["minimo"]} y '
        f'{resumen["maximo"]} turnos en total (diferencia de {resumen["delta"]}).'
    )
    sin_candidatos = resultado.get('sin_candidatos')
    if sin_candidatos:
        mensaje += f' {len(sin_candidatos)} sesión(es) no tenían dos aprendices elegibles.'
    return mensaje, 'success' if (creados or recalculados or eliminados) else 'info'


def casilla_marcada(formulario, campo, defecto=None):
    """True si la casilla llega marcada; ``defecto`` se usa cuando el campo no viene."""
    return formulario.get(campo, defecto) in VALORES_MARCADOS


def completados_del_formulario(formulario):
    """Cumplimiento de cada integrante, o (None, None) si el formulario no lo indica."""
    if 'completado_1' not in formulario and 'completado_2' not in formulario:
        return None, None
    return casilla_marcada(formulario, 'completado_1'), casilla_marcada(formulario, 'completado_2')


def fecha_formulario(valor, nombre):
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise ValueError(f'La {nombre} no es válida.')


def mes_consulta(valor, hoy=None):
    """Primer día del mes pedido (AAAA-MM); si no es válido, el mes actual."""
    try:
        return datetime.strptime(valor, '%Y-%m').date().replace(day=1)
    except (TypeError, ValueError):
        return (hoy or date.today()).replace(day=1)


def mover_mes(fecha, delta):
    indice = fecha.year * 12 + fecha.month - 1 + delta
    return date(indice // 12, indice % 12 + 1, 1)


def nombre_mes(mes):
    return f'{MESES[mes.month]} {mes.year}'
