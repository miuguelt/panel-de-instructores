"""Ubica la planeación en el calendario de la ficha y mide el desfase real.

Cada resultado de aprendizaje se ancla al trimestre declarado en la planeación
GFPI-F-134. Cuando la columna viene vacía se estima con el orden de las
actividades del proyecto formativo, y siempre queda marcado como estimado para
que nadie confunda una inferencia con un dato del documento.

La fecha real de ejecución se toma del Reporte de Juicios Evaluativos: los
registros ``POR EVALUAR`` no traen fecha, así que la única marca de tiempo
confiable es la de las aprobaciones.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date

from app.services.calendario_formacion import bloque_de


UMBRAL_CIERRE = 0.8
DIAS_ATRASO_CRITICO = 90

# Solo las competencias técnicas atan el cronograma. Las transversales y el
# inglés se pueden dictar completas al final de la etapa lectiva sin que eso
# signifique retraso, así que su trimestre es una recomendación y no entra en
# los porcentajes de desfase ni en la proyección de cierre.
TIPOS_EXIGIBLES = ('tecnica',)

ESTADOS_TIEMPO = {
    'a_tiempo': ('Cerrado a tiempo', 'success'),
    'cerrado_tarde': ('Cerrado tarde', 'warning'),
    'en_curso': ('En curso', 'info'),
    'programado': ('Programado', 'neutral'),
    'recomendado': ('Sugerido', 'neutral'),
    'atrasado': ('Atrasado', 'warning'),
    'critico': ('Crítico', 'danger'),
}

# Orden de atención: lo que exige acción primero encabeza la lista.
_PRIORIDAD = ['critico', 'atrasado', 'en_curso', 'programado', 'recomendado',
              'cerrado_tarde', 'a_tiempo']


def _clave(valor):
    texto = unicodedata.normalize('NFKD', str(valor or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c)).lower()
    return re.sub(r'[^a-z0-9]+', ' ', texto).strip()


def _numeros_trimestre(valores):
    numeros = set()
    for valor in valores or []:
        for encontrado in re.findall(r'\d+', str(valor)):
            numeros.add(int(encontrado))
    return sorted(numeros)


def _es_etapa_productiva(item):
    texto = _clave(f"{item.get('competencia')} {item.get('rap')}")
    return 'etapa practica' in texto or 'etapa productiva' in texto


def _orden_actividades(items):
    orden = []
    for item in items:
        nombre = item.get('actividad') or 'Sin actividad'
        if nombre not in orden:
            orden.append(nombre)
    return orden


def _rangos_declarados(items, actividades):
    rangos = {}
    for nombre in actividades:
        numeros = _numeros_trimestre(
            [trimestre for item in items if (item.get('actividad') or 'Sin actividad') == nombre
             for trimestre in (item.get('trimestres') or [])]
        )
        rangos[nombre] = (min(numeros), max(numeros)) if numeros else None
    return rangos


def _estimar_faltantes(actividades, rangos, ultimo_lectivo):
    """Rellena las actividades sin trimestre respetando el orden del documento."""
    pendientes = []
    previo = 1
    for nombre in actividades:
        rango = rangos.get(nombre)
        if rango:
            for pendiente in pendientes:
                rangos[pendiente] = (previo, max(previo, rango[0]))
            pendientes = []
            previo = rango[1]
            continue
        pendientes.append(nombre)
    if not pendientes:
        return
    # Cola sin declarar: va después de la última actividad ubicada y se reparte
    # sobre lo que queda de etapa lectiva conservando el orden del documento.
    arranque = min(previo + 1, ultimo_lectivo)
    disponibles = max(ultimo_lectivo - arranque + 1, 1)
    paso = disponibles / len(pendientes)
    for posicion, nombre in enumerate(pendientes):
        numero = min(arranque + int(posicion * paso), ultimo_lectivo)
        rangos[nombre] = (numero, numero)


def _fechas_por_aprendiz(item):
    fechas = []
    for valor in item.get('fechas_aprobacion') or []:
        fechas.append(valor.date() if hasattr(valor, 'date') else valor)
    return sorted(fecha for fecha in fechas if fecha)


def _cierre_real(item, aprendices_meta):
    fechas = _fechas_por_aprendiz(item)
    if not fechas:
        return None, None
    meta = max(math.ceil((aprendices_meta or len(fechas)) * UMBRAL_CIERRE), 1)
    cierre = fechas[meta - 1] if len(fechas) >= meta else None
    return fechas[0], cierre


def es_exigible(item):
    """Indica si el trimestre planeado obliga; en transversales solo sugiere."""
    if _es_etapa_productiva(item):
        return False
    return (item.get('competencia_tipo') or 'tecnica') in TIPOS_EXIGIBLES


def _estado_tiempo(item, hoy, exigible):
    inicio_plan = item['fecha_plan_inicio']
    fin_plan = item['fecha_plan_fin']
    if item['fecha_cierre_real']:
        if not exigible or item['fecha_cierre_real'] <= fin_plan:
            return 'a_tiempo'
        return 'cerrado_tarde'
    if not exigible:
        return 'recomendado'
    if hoy < inicio_plan:
        return 'programado'
    if hoy <= fin_plan:
        return 'en_curso'
    return 'critico' if (hoy - fin_plan).days > DIAS_ATRASO_CRITICO else 'atrasado'


def _etiqueta_rango(inicio, fin, lectivos):
    """Rotula el tramo con la nomenclatura del SENA: T1..Tn y etapa productiva."""
    nombre = lambda numero: 'EP' if numero > lectivos else f'T{numero}'
    return nombre(inicio) if inicio == fin else f'{nombre(inicio)}–{nombre(fin)}'


def _peor_estado(estados):
    for estado in _PRIORIDAD:
        if estado in estados:
            return estado
    return 'programado'


def _bloque_fecha(calendario, fecha):
    """Encuentra en qué número de bloque cae una fecha dada."""
    if not fecha or not calendario.get('bloques'):
        return None
    for b in calendario['bloques']:
        if b['inicio'] <= fecha <= b['fin']:
            return b['numero']
    if fecha < calendario['bloques'][0]['inicio']:
        return 1
    return len(calendario['bloques'])


def _ubicar(item, rangos, calendario, aprendices_meta, hoy):
    ubicado = dict(item)
    lectivos = calendario.get('trimestres_lectivos') or 1
    declarados = _numeros_trimestre(item.get('trimestres'))
    if _es_etapa_productiva(item):
        inicio = fin = lectivos + 1
        origen = 'etapa productiva'
    elif declarados:
        inicio, fin = min(declarados), max(declarados)
        origen = 'declarado'
    else:
        inicio, fin = rangos.get(item.get('actividad') or 'Sin actividad') or (1, 1)
        origen = 'estimado'
    inicio = min(max(inicio, 1), lectivos + 1)
    fin = min(max(fin, inicio), lectivos + 1)
    bloque_inicio = bloque_de(calendario, inicio)
    bloque_fin = bloque_de(calendario, fin)
    
    # Horas y duración pedagógica realista
    horas_tot = float(item.get('horas_total') or (float(item.get('horas_directas') or 0) + float(item.get('horas_independientes') or 0)) or 0)
    semanas_estimadas = max(round(horas_tot / 30.0, 1), 0.5) if horas_tot > 0 else 1.0

    ubicado.update({
        'trimestre_inicio': inicio,
        'trimestre_fin': fin,
        'trimestre_origen': origen,
        'trimestre_declarado': bool(declarados),
        'etapa': bloque_fin['etapa'] if bloque_fin else 'lectiva',
        'fecha_plan_inicio': bloque_inicio['inicio'] if bloque_inicio else hoy,
        'fecha_plan_fin': bloque_fin['fin'] if bloque_fin else hoy,
        'horas_total': horas_tot,
        'semanas_estimadas': semanas_estimadas,
    })
    primera, cierre = _cierre_real(item, aprendices_meta)
    exigible = es_exigible(item)
    ubicado['fecha_primera_aprobacion'] = primera
    ubicado['fecha_cierre_real'] = cierre
    ubicado['exigible'] = exigible
    ubicado['es_camino_critico'] = exigible and not _es_etapa_productiva(item)
    ubicado['estado_tiempo'] = _estado_tiempo(ubicado, hoy, exigible)
    referencia = cierre or hoy
    ubicado['dias_desfase'] = (referencia - ubicado['fecha_plan_fin']).days if exigible else 0
    ubicado['estado_label'], ubicado['estado_tono'] = ESTADOS_TIEMPO[ubicado['estado_tiempo']]
    ubicado['etiqueta_trimestre'] = _etiqueta_rango(inicio, fin, lectivos)
    
    # Trimestres reales observados en juicios
    t_real_ini = _bloque_fecha(calendario, primera) if primera else None
    t_real_fin = _bloque_fecha(calendario, cierre) if cierre else (_bloque_fecha(calendario, hoy) if primera else None)
    ubicado['trimestre_real_inicio'] = t_real_ini
    ubicado['trimestre_real_fin'] = t_real_fin
    ubicado['duracion_dias_real'] = (cierre - primera).days if (primera and cierre) else None

    return ubicado


def _resumir(nombre, resultados, aprendices_meta, lectivos):
    aprobados = sum(item.get('aprendices_aprobados') or 0 for item in resultados)
    posibles = len(resultados) * max(aprendices_meta or 0, 1)
    atrasados = [item for item in resultados if item['estado_tiempo'] in ('atrasado', 'critico')]
    inicio = min(item['trimestre_inicio'] for item in resultados)
    fin = max(item['trimestre_fin'] for item in resultados)
    
    horas_totales = round(sum(item.get('horas_total') or 0 for item in resultados), 1)
    horas_directas = round(sum(item.get('horas_directas') or 0 for item in resultados), 1)
    horas_independientes = round(sum(item.get('horas_independientes') or 0 for item in resultados), 1)

    # Fechas reales del agregado
    fechas_primera = [item['fecha_primera_aprobacion'] for item in resultados if item.get('fecha_primera_aprobacion')]
    fechas_cierre = [item['fecha_cierre_real'] for item in resultados if item.get('fecha_cierre_real')]
    
    primera_global = min(fechas_primera) if fechas_primera else None
    # Cierre de la competencia: cuando todos los resultados cerraron o al menos el 80% de RAPs
    cierre_global = max(fechas_cierre) if (len(fechas_cierre) >= max(math.ceil(len(resultados) * UMBRAL_CIERRE), 1)) else None

    # Tramos reales para Gantt dual
    t_real_ini_list = [item['trimestre_real_inicio'] for item in resultados if item.get('trimestre_real_inicio')]
    t_real_fin_list = [item['trimestre_real_fin'] for item in resultados if item.get('trimestre_real_fin')]
    trimestre_real_inicio = min(t_real_ini_list) if t_real_ini_list else None
    trimestre_real_fin = max(t_real_fin_list) if t_real_fin_list else None

    exigible = any(item['exigible'] for item in resultados)
    pct_avance = round(aprobados / posibles * 100) if posibles else 0

    return {
        'nombre': nombre,
        'exigible': exigible,
        'es_camino_critico': exigible and 'etapa' not in nombre.lower(),
        'etiqueta_trimestre': _etiqueta_rango(inicio, fin, lectivos),
        'resultados': resultados,
        'resultados_total': len(resultados),
        'resultados_atrasados': len(atrasados),
        'horas': horas_totales,
        'horas_directas': horas_directas,
        'horas_independientes': horas_independientes,
        'trimestre_inicio': inicio,
        'trimestre_fin': fin,
        'trimestre_real_inicio': trimestre_real_inicio,
        'trimestre_real_fin': trimestre_real_fin,
        'fecha_primera_aprobacion': primera_global,
        'fecha_cierre_real': cierre_global,
        'porcentaje_avance': pct_avance,
        'estado_tiempo': _peor_estado({item['estado_tiempo'] for item in resultados}),
        'dias_desfase': max((item['dias_desfase'] for item in atrasados), default=0),
    }


def _agrupar_por(resultados, clave, aprendices_meta, lectivos):
    grupos = {}
    for item in resultados:
        nombre = item.get(clave) or 'Sin clasificar'
        grupos.setdefault(nombre, []).append(item)
    return [_resumir(nombre, hijos, aprendices_meta, lectivos) for nombre, hijos in grupos.items()]


def _decorar(grupo):
    grupo['estado_label'], grupo['estado_tono'] = ESTADOS_TIEMPO[grupo['estado_tiempo']]
    grupo['trimestres_desfase'] = round(grupo['dias_desfase'] / 91, 1) if grupo['dias_desfase'] > 0 else 0
    return grupo


def _orden_fase(nombre_fase):
    clave = _clave(nombre_fase)
    if 'induccion' in clave:
        return 0
    if 'analisis' in clave:
        return 1
    if 'planeacion' in clave or 'diseno' in clave:
        return 2
    if 'ejecucion' in clave or 'desarrollo' in clave or 'construccion' in clave:
        return 3
    if 'evaluacion' in clave:
        return 4
    if 'practica' in clave or 'productiva' in clave:
        return 9
    return 5


def _actividad_numero(actividad_str):
    match = re.search(r'AP0*(\d+)', str(actividad_str or ''), re.IGNORECASE)
    return int(match.group(1)) if match else 999


def _calcular_posicion_linea(fecha, calendario):
    """Calcula la posición horizontal en porcentaje (0%..100%) sobre los bloques del calendario."""
    if not fecha or not calendario.get('bloques'):
        return 0.0
    bloques = calendario['bloques']
    total_bloques = len(bloques)
    if not total_bloques:
        return 0.0
    if fecha <= bloques[0]['inicio']:
        return 0.0
    if fecha >= bloques[-1]['fin']:
        return 100.0
    for indice, bloque in enumerate(bloques):
        if fecha < bloque['inicio']:
            return round(indice / total_bloques * 100, 2)
        if fecha <= bloque['fin']:
            dias = max((bloque['fin'] - bloque['inicio']).days + 1, 1)
            avance = (fecha - bloque['inicio']).days / dias
            return round((indice + min(max(avance, 0.0), 1.0)) / total_bloques * 100, 2)
    return 100.0


def _ordenar_competencias_fase(competencias):
    """Ordena las competencias dentro de una fase respetando la secuencia pedagógica."""
    return sorted(
        competencias,
        key=lambda comp: (
            not comp['exigible'],
            0 if 'induccion' in _clave(comp['nombre']) else 1,
            comp['trimestre_inicio'],
            min((_actividad_numero(r.get('actividad')) for r in comp.get('resultados', [])), default=999),
            comp['nombre'],
        ),
    )


def _encadenar_competencias_tecnicas(competencias_fase, calendario, hoy, lectivos):
    """Encadena secuencialmente las competencias técnicas que comparten tramo temporal."""
    from datetime import timedelta

    tecnicas = [c for c in competencias_fase if c['exigible'] and not _es_etapa_productiva(c)]
    if not tecnicas:
        return

    # Agrupar por tramo común de trimestres dentro de la fase
    grupos_tramos = {}
    for comp in tecnicas:
        clave_tramo = (comp['trimestre_inicio'], comp['trimestre_fin'])
        grupos_tramos.setdefault(clave_tramo, []).append(comp)

    for (t_ini, t_fin), comps_grupo in grupos_tramos.items():
        b_ini = bloque_de(calendario, t_ini)
        b_fin = bloque_de(calendario, t_fin)
        f_tramo_ini = b_ini['inicio'] if b_ini else hoy
        f_tramo_fin = b_fin['fin'] if b_fin else hoy
        dias_tramo = max((f_tramo_fin - f_tramo_ini).days + 1, 1)

        horas_totales_grupo = sum(max(float(c.get('horas') or 0), 1.0) for c in comps_grupo) or 1.0
        offset_horas = 0.0

        for comp in comps_grupo:
            horas_c = max(float(comp.get('horas') or 0), 1.0)
            duracion_semanas = max(round(comp.get('horas', 0) / 30.0, 1), 0.5) if comp.get('horas', 0) > 0 else 1.0

            if len(comps_grupo) == 1:
                f_inicio = f_tramo_ini
                f_fin = f_tramo_fin
            else:
                offset_dias = round(offset_horas / horas_totales_grupo * dias_tramo)
                dias_duracion = max(round(horas_c / horas_totales_grupo * dias_tramo), 2)
                f_inicio = f_tramo_ini + timedelta(days=min(offset_dias, dias_tramo - 1))
                f_fin = min(f_inicio + timedelta(days=dias_duracion - 1), f_tramo_fin)
                offset_horas += horas_c

            comp['fecha_plan_inicio'] = f_inicio
            comp['fecha_plan_fin'] = f_fin
            comp['dias_duracion'] = (f_fin - f_inicio).days + 1
            comp['duracion_semanas'] = duracion_semanas
            comp['etiqueta_duracion'] = f"{comp['horas']:g}h (~{duracion_semanas:g} sem)"

            left_pct = _calcular_posicion_linea(f_inicio, calendario)
            right_pct = _calcular_posicion_linea(f_fin, calendario)
            comp['gantt_left_pct'] = left_pct
            comp['gantt_width_pct'] = max(round(right_pct - left_pct, 2), 1.2)

            # Recálculo de estado y desfase basado en la ventana encadenada
            if comp['porcentaje_avance'] >= 80 or comp.get('fecha_cierre_real'):
                if comp.get('fecha_cierre_real') and comp['fecha_cierre_real'] > f_fin:
                    comp['estado_tiempo'] = 'cerrado_tarde'
                    comp['dias_desfase'] = (comp['fecha_cierre_real'] - f_fin).days
                else:
                    comp['estado_tiempo'] = 'a_tiempo'
                    comp['dias_desfase'] = 0
            elif hoy < f_inicio:
                comp['estado_tiempo'] = 'programado'
                comp['dias_desfase'] = 0
            elif hoy <= f_fin:
                comp['estado_tiempo'] = 'en_curso'
                comp['dias_desfase'] = 0
            else:
                dias_vencido = (hoy - f_fin).days
                comp['dias_desfase'] = dias_vencido
                comp['estado_tiempo'] = 'critico' if dias_vencido > DIAS_ATRASO_CRITICO else 'atrasado'

            comp['estado_label'], comp['estado_tono'] = ESTADOS_TIEMPO[comp['estado_tiempo']]
            comp['trimestres_desfase'] = round(comp['dias_desfase'] / 91, 1) if comp['dias_desfase'] > 0 else 0


def construir_linea_tiempo(items, calendario, aprendices_meta=0, hoy=None):
    """Devuelve la planeación organizada en fases, competencias y trimestres."""
    hoy = hoy or date.today()
    if not items or not calendario.get('configurado'):
        return {'resultados': [], 'fases': [], 'competencias': [],
                'resumen': {'competencias_distintas': 0, 'competencias_exigibles': 0,
                            'competencias_sugeridas': 0, 'competencias_atrasadas': 0,
                            'competencias_criticas': 0, 'tramos_atrasados': 0,
                            'resultados_atrasados': 0, 'resultados_estimados': 0,
                            'dias_desfase': 0, 'trimestres_desfase': 0}}

    lectivos = calendario.get('trimestres_lectivos') or 1
    actividades = _orden_actividades(items)
    rangos = _rangos_declarados(items, actividades)
    _estimar_faltantes(actividades, rangos, lectivos)
    resultados = [_ubicar(item, rangos, calendario, aprendices_meta, hoy) for item in items]

    # 1. Agrupación inicial de fases respetando el orden pedagógico estándar SENA
    nombres_fases = list(dict.fromkeys(item.get('fase') or 'Sin fase' for item in resultados))
    nombres_fases.sort(key=lambda n: (_orden_fase(n), n))

    inicio_lectiva = calendario.get('inicio') or hoy
    fin_lectiva = calendario.get('fin_lectiva') or calendario.get('fin') or hoy

    fases = []
    for nombre_fase in nombres_fases:
        propios = [item for item in resultados if (item.get('fase') or 'Sin fase') == nombre_fase]
        fase = _decorar(_resumir(nombre_fase, propios, aprendices_meta, lectivos))
        fase['competencias'] = _ordenar_competencias_fase([
            _decorar(grupo) for grupo in _agrupar_por(propios, 'competencia', aprendices_meta, lectivos)
        ])
        for competencia in fase['competencias']:
            competencia['actividades'] = sorted({
                item.get('actividad') or 'Sin actividad' for item in competencia['resultados']
            })
            competencia['instructores'] = sorted({
                nombre for item in competencia['resultados']
                for nombre in (item.get('instructores') or [])
            })
            competencia['fase'] = nombre_fase

        # Encadenar las competencias técnicas de esta fase
        _encadenar_competencias_tecnicas(fase['competencias'], calendario, hoy, lectivos)

        # Transversales, Inglés y Etapa Productiva (paralelas / flexibles)
        for comp in fase['competencias']:
            if comp['exigible'] and not _es_etapa_productiva(comp):
                continue
            es_prod = _es_etapa_productiva(comp) or 'productiva' in comp['nombre'].lower() or 'practica' in comp['nombre'].lower()
            if es_prod:
                f_inicio = calendario.get('inicio_productiva') or fin_lectiva
                f_fin = calendario.get('fin') or fin_lectiva
                comp['fecha_plan_inicio'] = f_inicio
                comp['fecha_plan_fin'] = f_fin
                comp['duracion_semanas'] = 26.0
                comp['etiqueta_duracion'] = f"6 meses ({comp['horas']:g}h)" if comp['horas'] else "6 meses"
            else:
                b_ini = bloque_de(calendario, comp['trimestre_inicio'])
                b_fin = bloque_de(calendario, comp['trimestre_fin'])
                f_inicio = b_ini['inicio'] if b_ini else inicio_lectiva
                f_fin = b_fin['fin'] if b_fin else fin_lectiva
                comp['fecha_plan_inicio'] = f_inicio
                comp['fecha_plan_fin'] = f_fin
                dur_sem = max(round(comp.get('horas', 0) / 30.0, 1), 0.5) if comp.get('horas', 0) > 0 else 1.0
                comp['duracion_semanas'] = dur_sem
                comp['etiqueta_duracion'] = f"{comp['horas']:g}h (~{dur_sem:g} sem)"

            left_pct = _calcular_posicion_linea(f_inicio, calendario)
            right_pct = _calcular_posicion_linea(f_fin, calendario)
            comp['gantt_left_pct'] = left_pct
            comp['gantt_width_pct'] = max(round(right_pct - left_pct, 2), 1.2)
            comp['estado_label'], comp['estado_tono'] = ESTADOS_TIEMPO[comp['estado_tiempo']]
            comp['trimestres_desfase'] = round(comp['dias_desfase'] / 91, 1) if comp['dias_desfase'] > 0 else 0

        # Actualizar fronteras de la fase
        if fase['competencias']:
            fase['trimestre_inicio'] = min(c['trimestre_inicio'] for c in fase['competencias'])
            fase['trimestre_fin'] = max(c['trimestre_fin'] for c in fase['competencias'])
            fase['etiqueta_trimestre'] = _etiqueta_rango(fase['trimestre_inicio'], fase['trimestre_fin'], lectivos)
            fase['estado_tiempo'] = _peor_estado({c['estado_tiempo'] for c in fase['competencias']})
            fase['estado_label'], fase['estado_tono'] = ESTADOS_TIEMPO[fase['estado_tiempo']]
            fase['dias_desfase'] = max((c['dias_desfase'] for c in fase['competencias']), default=0)
            fase['trimestres_desfase'] = round(fase['dias_desfase'] / 91, 1) if fase['dias_desfase'] > 0 else 0

        fases.append(fase)

    competencias = [comp for fase in fases for comp in fase['competencias']]
    atrasadas = [comp for comp in competencias if comp['estado_tiempo'] in ('atrasado', 'critico')]
    desfase = max((comp['dias_desfase'] for comp in atrasadas), default=0)
    distintas = {comp['nombre'] for comp in competencias}
    exigibles = {comp['nombre'] for comp in competencias if comp['exigible']}
    nombres_atrasados = {comp['nombre'] for comp in atrasadas}
    nombres_criticos = {comp['nombre'] for comp in competencias if comp['estado_tiempo'] == 'critico'}

    return {
        'resultados': resultados,
        'fases': fases,
        'competencias': competencias,
        'resumen': {
            'competencias_distintas': len(distintas),
            'competencias_exigibles': len(exigibles),
            'competencias_sugeridas': len(distintas - exigibles),
            'competencias_atrasadas': len(nombres_atrasados),
            'competencias_criticas': len(nombres_criticos),
            'tramos_atrasados': len(atrasadas),
            'resultados_atrasados': sum(1 for item in resultados
                                        if item['estado_tiempo'] in ('atrasado', 'critico')),
            'resultados_estimados': sum(1 for item in resultados if not item['trimestre_declarado']),
            'dias_desfase': desfase,
            'trimestres_desfase': round(desfase / 91, 1) if desfase else 0,
        },
    }


