"""Alerta preventiva antes del cierre de la etapa lectiva.

En los 60 días previos al fin de la etapa lectiva (30 días: prioridad alta) avisa qué
aprendices tienen resultados de aprendizaje sin juicio aprobado, según los juicios
importados, o no tienen registrada la planeación avalada de su etapa productiva. Así el
instructor actúa antes de que se configure la causal del Acuerdo 009 de 2024, Art. 30,
num. 2 (pág. 31).
"""

from collections import defaultdict
from datetime import datetime

from app.models.aprendiz import ESTADOS_PLANEACION_ACTIVOS, normalizar_estado
from app.models.juicio import JuicioEvaluativo
from app.services.emparejamiento_juicios import clave_resultado, es_aprobado
from app.services.normativa_sena import fundamentos_de
from app.services.periodo_formacion import obtener_periodo_formacion

TIPO_ALERTA = 'cierre_lectivo'
DIAS_AVISO = 60
DIAS_PRIORIDAD_ALTA = 30


def _a_fecha(valor):
    return valor.date() if isinstance(valor, datetime) else valor


def ventana_cierre(ficha, hoy):
    """(nivel, días restantes, fin lectiva) si la ficha está en la ventana; si no, None."""
    periodo = obtener_periodo_formacion(ficha, _a_fecha(hoy))
    fin_lectiva = periodo.get('fin_lectiva')
    if not periodo.get('configurado') or not fin_lectiva:
        return None
    dias = (fin_lectiva - _a_fecha(hoy)).days
    if not 0 <= dias <= DIAS_AVISO:
        return None
    return ('roja' if dias <= DIAS_PRIORIDAD_ALTA else 'amarilla', dias, fin_lectiva)


def resultados_pendientes(juicios, aprendiz_ids=()):
    """aprendiz_id -> resultados de aprendizaje de la ficha sin ninguna aprobación.

    Se compara contra todos los resultados que la ficha tiene registrados (la
    unión de los juicios del grupo): a quien le falta un resultado o no tiene
    ningún juicio, ese resultado le cuenta como pendiente.
    """
    catalogo = set()
    aprobados = defaultdict(set)
    for aprendiz_id, competencia, resultado, juicio in juicios:
        clave = (clave_resultado(competencia), clave_resultado(resultado))
        catalogo.add(clave)
        if es_aprobado(juicio):
            aprobados[aprendiz_id].add(clave)
    ids = set(aprendiz_ids) | {fila[0] for fila in juicios}
    return {aprendiz_id: len(catalogo - aprobados[aprendiz_id]) for aprendiz_id in ids}


def cargar_pendientes(ficha_id, aprendiz_ids=()):
    filas = JuicioEvaluativo.query.with_entities(
        JuicioEvaluativo.aprendiz_id, JuicioEvaluativo.competencia,
        JuicioEvaluativo.resultado_aprendizaje, JuicioEvaluativo.juicio,
    ).filter(JuicioEvaluativo.ficha_id == ficha_id).all()
    return resultados_pendientes(filas, aprendiz_ids)


def evaluar_aprendiz_cierre(aprendiz, ventana, pendientes, etapa):
    """Alerta para un aprendiz dentro de la ventana de cierre, o None."""
    if not ventana or normalizar_estado(aprendiz.estado) not in ESTADOS_PLANEACION_ACTIVOS:
        return None
    nivel, dias, fin_lectiva = ventana
    sin_planeacion = not (etapa and etapa.planeacion_avalada)
    if not pendientes and not sin_planeacion:
        return None
    faltantes = []
    if pendientes:
        faltantes.append(f'{pendientes} resultado(s) de aprendizaje sin juicio aprobado')
    if sin_planeacion:
        faltantes.append('la planeación de la etapa productiva sin aval registrado')
    mensaje = (
        f'La etapa lectiva termina el {fin_lectiva:%d/%m/%Y}. {aprendiz.nombre} tiene '
        f'{" y ".join(faltantes)}.'
    )
    if sin_planeacion:
        mensaje += (
            ' Si al cierre de la ficha no ha presentado la planeación de su etapa '
            'productiva, se configura la causal del Acuerdo 009 de 2024, Art. 30, '
            'num. 2 (pág. 31).'
        )
    return {
        'nivel': nivel,
        'titulo': f'Cierre de etapa lectiva en {dias} días: hay pendientes',
        'mensaje': mensaje,
        'detalle': {
            'motivo': TIPO_ALERTA,
            'dias_para_cierre': dias,
            'fin_lectiva': fin_lectiva.isoformat(),
            'resultados_pendientes': pendientes,
            'sin_planeacion_productiva': sin_planeacion,
        },
    }


def actualizar_alertas_cierre(ficha, ahora, aprendices, etapas, contexto=None):
    """Crea, actualiza o resuelve las alertas de cierre lectivo de la ficha."""
    from app.models.alertas import Alerta
    from app.services.alertas import _con_fundamento, _crear_alerta

    from app.services.alertas import fecha_colombia
    ventana = ventana_cierre(ficha, fecha_colombia(ahora))
    pendientes = cargar_pendientes(ficha.id, [a.id for a in aprendices]) if ventana else {}
    evaluados = {a.id for a in aprendices}
    vigentes = set()
    for aprendiz in aprendices:
        alerta = evaluar_aprendiz_cierre(
            aprendiz, ventana, pendientes.get(aprendiz.id, 0), etapas.get(aprendiz.id))
        if not alerta:
            continue
        vigentes.add(aprendiz.id)
        detalle = _con_fundamento(alerta['detalle'], 'productiva_vencida')
        _crear_alerta(ficha, aprendiz, TIPO_ALERTA, alerta['nivel'], alerta['titulo'],
                      alerta['mensaje'], detalle, ahora, contexto=contexto)
    for abierta in Alerta.query.filter_by(ficha_id=ficha.id, tipo=TIPO_ALERTA, estado='activa').all():
        # Solo se cierran las alertas de quienes se evaluaron en esta llamada.
        if abierta.aprendiz_id in evaluados and abierta.aprendiz_id not in vigentes:
            abierta.estado = 'resuelta'
            abierta.fecha_resuelta = ahora
    return len(vigentes)
