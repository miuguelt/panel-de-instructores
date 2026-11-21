"""Cálculos puros para las ayudas visuales de la interfaz.

Toda la app usa estos umbrales y formatos para que un mismo dato tenga el mismo
color y la misma lectura en cualquier pantalla. Las macros de
``components/_viz.html`` consumen estas funciones mediante el context processor
que registra :func:`registrar`.

Umbrales canónicos (porcentaje donde más es mejor):
- ``UMBRAL_VERDE`` (80): asistencia, entregas o RAPs en buen nivel.
- ``UMBRAL_AMARILLO`` (60): requiere seguimiento; por debajo es riesgo.
"""

import math

UMBRAL_VERDE = 80
UMBRAL_AMARILLO = 60
META_TYT = 70
RADIO_DONA = 40
# Diferencia entre RAPs aprobados y tiempo transcurrido (en puntos).
BRECHA_TOLERADA = 2
BRECHA_CRITICA = 10
# Días para resaltar un hito de inicio o cierre de la ficha.
DIAS_INICIO_AVISO = 30
DIAS_CIERRE_RIESGO = 15
DIAS_CIERRE_AVISO = 45


def _numero(valor):
    """Convierte a float; None si el valor no es numérico."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(numero) else numero


def estado_por_umbral(pct, verde=UMBRAL_VERDE, amarillo=UMBRAL_AMARILLO, invertido=False):
    """Estado semántico de un valor: success, warning, danger o neutral (sin dato).

    Con ``invertido`` los valores bajos son buenos (por ejemplo, faltas).
    """
    valor = _numero(pct)
    if valor is None:
        return 'neutral'
    if invertido:
        if valor <= verde:
            return 'success'
        return 'warning' if valor <= amarillo else 'danger'
    if valor >= verde:
        return 'success'
    return 'warning' if valor >= amarillo else 'danger'


def acotar_pct(pct):
    """Porcentaje entre 0 y 100 con un decimal (entero si no tiene fracción).

    Devuelve None si no hay dato.
    """
    valor = _numero(pct)
    if valor is None:
        return None
    acotado = round(min(max(valor, 0.0), 100.0), 1)
    return int(acotado) if acotado.is_integer() else acotado


def porcentaje(parte, total):
    """Porcentaje con un decimal; None si el total es cero o falta un dato."""
    p, t = _numero(parte), _numero(total)
    if p is None or not t:
        return None
    return round(p / t * 100, 1)


def segmentos(items):
    """Segmentos de una barra apilada a partir de ``(etiqueta, valor[, estado])``.

    Omite valores nulos o negativos y reparte el redondeo para que los
    porcentajes sumen exactamente 100 (método del resto mayor).
    """
    validos = []
    for item in items or []:
        etiqueta, valor = item[0], _numero(item[1])
        estado = item[2] if len(item) > 2 else 'neutral'
        if valor and valor > 0:
            validos.append((etiqueta, item[1], valor, estado))
    total = sum(v[2] for v in validos)
    if not total:
        return []
    crudos = [v[2] / total * 100 for v in validos]
    enteros = [math.floor(c) for c in crudos]
    faltante = 100 - sum(enteros)
    orden = sorted(range(len(crudos)), key=lambda i: crudos[i] - enteros[i], reverse=True)
    for i in orden[:faltante]:
        enteros[i] += 1
    return [{'etiqueta': e, 'valor': original, 'estado': estado, 'pct': enteros[i]}
            for i, (e, original, _, estado) in enumerate(validos)]


def puntos_sparkline(serie, ancho=120, alto=32, minimo=None, maximo=None):
    """Coordenadas de una polilínea; None si hay menos de dos valores numéricos."""
    valores = [v for v in (_numero(x) for x in (serie or [])) if v is not None]
    if len(valores) < 2:
        return None
    bajo = min(valores) if minimo is None else minimo
    alto_v = max(valores) if maximo is None else maximo
    rango = alto_v - bajo
    paso = ancho / (len(valores) - 1)
    puntos = []
    for i, v in enumerate(valores):
        y = alto / 2 if rango == 0 else alto - (v - bajo) / rango * alto
        puntos.append((round(i * paso, 1), round(y, 1)))
    ultimo_original = [x for x in serie if _numero(x) is not None][-1]
    return {
        'puntos': ' '.join(f'{x},{y}' for x, y in puntos),
        'ultimo': {'x': puntos[-1][0], 'y': puntos[-1][1], 'valor': ultimo_original},
        'primero': [x for x in serie if _numero(x) is not None][0],
        'n': len(valores), 'ancho': ancho, 'alto': alto,
    }


def arco_dona(pct):
    """Longitud del trazo de un anillo SVG de radio ``RADIO_DONA``."""
    circunferencia = round(2 * math.pi * RADIO_DONA, 2)
    valor = acotar_pct(pct) or 0
    return {'circunferencia': circunferencia, 'longitud': round(circunferencia * valor / 100, 2)}


def _dias(n):
    return '1 día' if n == 1 else f'{n} días'


def hito_urgente(cronograma):
    """El hito de calendario más relevante de la ficha (inicio o cierre).

    Devuelve un solo aviso para no repetir la cuenta regresiva en varios
    bloques, o None si no hay fechas o la ficha terminó.
    """
    if not cronograma or not cronograma.get('configurado'):
        return None
    if cronograma.get('fase') == 'finalizada' or cronograma.get('ficha_cerrada'):
        return None
    inicio = cronograma.get('dias_para_iniciar_lectiva')
    if cronograma.get('fase') == 'por_iniciar' and inicio is not None:
        estado = 'warning' if inicio <= DIAS_INICIO_AVISO else 'neutral'
        texto = 'Inicia hoy' if inicio == 0 else f'Inicia en {_dias(inicio)}'
        return {'tipo': 'inicio', 'dias': inicio, 'estado': estado, 'texto': texto}
    cierre = cronograma.get('dias_cierre_ficha')
    if cierre is None:
        return None
    if cierre <= DIAS_CIERRE_RIESGO:
        estado = 'danger'
    elif cierre <= DIAS_CIERRE_AVISO:
        estado = 'warning'
    else:
        estado = 'neutral'
    texto = 'Cierra hoy' if cierre == 0 else f'Cierra en {_dias(cierre)}'
    return {'tipo': 'cierre', 'dias': cierre, 'estado': estado, 'texto': texto}


def brecha_texto(pct_raps, pct_tiempo):
    """Compara RAPs aprobados con el tiempo transcurrido en una frase corta."""
    raps, tiempo = _numero(pct_raps), _numero(pct_tiempo)
    if raps is None or tiempo is None:
        return None
    delta = round(raps - tiempo, 1)
    if delta >= -BRECHA_TOLERADA:
        estado = 'success'
    elif delta >= -BRECHA_CRITICA:
        estado = 'warning'
    else:
        estado = 'danger'
    if abs(delta) < 1:
        texto = 'RAPs al ritmo del tiempo'
    elif delta < 0:
        texto = f'RAPs {abs(delta):.1f} pts por debajo del tiempo'
    else:
        texto = f'RAPs {delta:.1f} pts por delante del tiempo'
    return {'delta': delta, 'estado': estado, 'texto': texto}


# Estado del aprendiz en SOFIA Plus → (etiqueta legible, tono).
ESTADOS_APRENDIZ = {
    'EN_FORMACION': ('En formación', 'info'),
    'POR_CERTIFICAR': ('Por certificar', 'success'),
    'CERTIFICADO': ('Certificados', 'success'),
    'CONDICIONADO': ('Condicionados', 'warning'),
    'RETIRO_VOLUNTARIO': ('Retiro voluntario', 'warning'),
    'CANCELADO': ('Cancelados', 'danger'),
}


def items_estados_aprendiz(estados):
    """Convierte ``{estado: conteo}`` en segmentos legibles para ``apilada``."""
    estados = estados or {}
    items = [(etiqueta, estados[clave], tono)
             for clave, (etiqueta, tono) in ESTADOS_APRENDIZ.items() if estados.get(clave)]
    for clave, valor in estados.items():
        if clave not in ESTADOS_APRENDIZ and valor:
            items.append((str(clave).replace('_', ' ').capitalize(), valor, 'neutral'))
    return items


def registrar(app):
    """Expone las funciones a Jinja como globales ``viz_*``.

    Se registran como globales (no con un context processor) para que las
    macros importadas sin ``with context`` también las encuentren.
    """
    from app.services.prioridad_fichas import pendientes_de_hoy

    app.jinja_env.globals.update({
        'viz_pendientes': pendientes_de_hoy,
        'viz_estado': estado_por_umbral,
        'viz_pct': acotar_pct,
        'viz_porcentaje': porcentaje,
        'viz_segmentos': segmentos,
        'viz_sparkline': puntos_sparkline,
        'viz_arco': arco_dona,
        'viz_hito': hito_urgente,
        'viz_brecha': brecha_texto,
        'viz_estados_aprendiz': items_estados_aprendiz,
        'VIZ_META_TYT': META_TYT,
    })
