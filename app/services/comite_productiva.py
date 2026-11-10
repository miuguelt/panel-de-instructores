"""Remisión a comité por no culminar la etapa productiva dentro del plazo.

Regla (Acuerdo 009 de 2024):
- Art. 30, num. 2 (pág. 31): el plazo límite para la etapa productiva es la
  finalización por fecha del grupo. Si la ficha terminó y el aprendiz sigue en
  formación o aplazado, hay causal de deserción por incumplimiento de la etapa
  productiva, que el instructor reporta al comité (Art. 31, num. 2).
- Art. 47, num. 2, parágrafo 1 (pág. 39): pasado un año desde la fecha fin
  programada sin certificación, el aprendiz pasa a cancelado por vía
  administrativa.

Las funciones de evaluación son puras (sin base de datos) para poder probar
cada límite de fecha y cada estado por separado.
"""

from datetime import date, datetime

from app.models.aprendiz import Aprendiz, etiqueta_estado, normalizar_estado
from app.services.normativa_sena import fundamentos_de

TIPO_ALERTA = 'productiva_vencida'

# Estados que indican que el aprendiz no ha cerrado su proceso formativo.
ESTADOS_SIN_CULMINAR = (
    'EN', 'EN_FORMACION', 'INDUCCION', 'CONDICIONADO', 'APLAZADO', 'EN_APLAZAMIENTO',
)
ESTADOS_APLAZADO = ('APLAZADO', 'EN_APLAZAMIENTO')

DIAS_CANCELACION_ADMINISTRATIVA = 365

ACCION_COMITE = 'remitir_comite'
ACCION_CANCELACION = 'cancelacion_administrativa'


def fecha_limite_productiva(ficha):
    """Fecha límite para culminar la etapa productiva: la fecha fin del grupo."""
    return getattr(ficha, 'fecha_fin', None)


def ficha_terminada(ficha, hoy):
    """True cuando la ficha tiene fecha fin y esa fecha ya pasó."""
    limite = fecha_limite_productiva(ficha)
    return bool(limite and hoy > limite)


def _a_fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    return valor


def planeacion_avalada_a_tiempo(etapa, limite):
    """True si la planeación de la etapa productiva se avaló antes del cierre del grupo."""
    return bool(etapa and etapa.planeacion_avalada and etapa.fecha_aval
                and etapa.fecha_aval <= limite)


def evaluar_aprendiz_productiva(aprendiz, ficha, hoy, etapa=None, novedades=()):
    """Recomendación para un aprendiz de ficha terminada, o None si no aplica.

    `etapa` y `novedades` son los registros del panel para el aprendiz. Con
    planeación avalada a tiempo no se configura la causal del Art. 30, num. 2;
    con un aplazamiento vigente, la evaluación corresponde al reintegro
    (Art. 30, num. 3). La recomendación de cancelación administrativa al año
    (Art. 47) no se genera mientras haya un aplazamiento vigente, y el año se
    corre por los días que el aprendiz estuvo aplazado.
    """
    from app.services.novedades import aplazamiento_vigente, dias_aplazados_despues_de

    hoy = _a_fecha(hoy)
    if not ficha_terminada(ficha, hoy):
        return None
    estado = normalizar_estado(aprendiz.estado)
    if estado not in ESTADOS_SIN_CULMINAR:
        return None

    limite = fecha_limite_productiva(ficha)
    dias_vencida = (hoy - limite).days
    aplazado = estado in ESTADOS_APLAZADO
    vigente = aplazamiento_vigente(novedades, hoy)
    dias_aplazados = dias_aplazados_despues_de(novedades, limite, hoy)
    cancelacion = (
        not vigente
        and dias_vencida - dias_aplazados >= DIAS_CANCELACION_ADMINISTRATIVA
    )
    if not cancelacion and (
        planeacion_avalada_a_tiempo(etapa, limite) or aplazamiento_vigente(novedades, hoy)
    ):
        return None

    if cancelacion:
        accion = ACCION_CANCELACION
        claves = ['productiva_vencida', 'cancelacion_un_anio', 'procedimiento_comite']
        titulo = 'Más de un año sin certificar: procede cancelación administrativa'
        motivo = (
            f'La ficha {ficha.codigo} terminó el {limite:%d/%m/%Y} y han pasado '
            f'{dias_vencida} días sin que el aprendiz se certifique. Según el Acuerdo 009 '
            'de 2024, Art. 47, num. 2, parágrafo 1 (pág. 39), debe pasar a estado '
            'cancelado por vía administrativa.'
        )
    else:
        accion = ACCION_COMITE
        claves = [
            'productiva_vencida', 'procedimiento_desercion_productiva',
            'procedimiento_comite', 'debido_proceso',
        ]
        titulo = 'Remitir a comité: etapa productiva no culminada al cierre de la ficha'
        motivo = (
            f'La ficha {ficha.codigo} terminó por fechas el {limite:%d/%m/%Y} '
            f'(hace {dias_vencida} días) y el aprendiz sigue en estado '
            f'«{etiqueta_estado(aprendiz.estado)}». El Acuerdo 009 de 2024, Art. 30, '
            'num. 2 (pág. 31), fija como plazo límite de la etapa productiva la '
            'finalización por fecha del grupo; el Art. 31, num. 2, ordena reportarlo '
            'al comité de evaluación y seguimiento.'
        )

    advertencias = []
    if etapa and etapa.planeacion_avalada and not planeacion_avalada_a_tiempo(etapa, limite):
        advertencias.append(
            'La planeación de la etapa productiva se registró como avalada después del cierre '
            'del grupo; el comité debe valorar si se presentó dentro del plazo.'
        )
    if aplazado:
        claves += ['aplazamiento', 'aplazamiento_vencido']
        advertencias.append(
            'El aprendiz figura como aplazado. Antes de citar al comité, verifique la '
            'fecha fin del aplazamiento autorizado (máximo 3 meses más 3 de ampliación, '
            'Art. 18, num. 2, pág. 22) y si gestionó el reintegro a tiempo (Art. 30, '
            'num. 3, pág. 31).'
        )
    advertencias.append(
        'Confirme en el aplicativo de gestión académica que no exista un registro de '
        'etapa productiva, novedad o certificación que el reporte importado no muestre.'
    )

    return {
        'aprendiz_id': aprendiz.id,
        'documento': aprendiz.documento,
        'nombre': aprendiz.nombre_completo,
        'estado': estado,
        'estado_etiqueta': etiqueta_estado(aprendiz.estado),
        'ficha_id': ficha.id,
        'ficha_codigo': ficha.codigo,
        'fecha_fin_ficha': limite,
        'dias_vencida': dias_vencida,
        'aplazado': aplazado,
        'accion': accion,
        'nivel': 'roja',
        'titulo': titulo,
        'motivo': motivo,
        'advertencias': advertencias,
        'fundamentos': fundamentos_de(*claves),
    }


def analizar_ficha(ficha, aprendices, hoy, etapas=None, novedades=None):
    """Recomendaciones de una ficha a partir de sus aprendices (sin consultas)."""
    if not ficha_terminada(ficha, _a_fecha(hoy)):
        return []
    etapas, novedades = etapas or {}, novedades or {}
    recomendaciones = []
    for aprendiz in aprendices:
        recomendacion = evaluar_aprendiz_productiva(
            aprendiz, ficha, hoy, etapas.get(aprendiz.id), novedades.get(aprendiz.id, ()))
        if recomendacion:
            recomendaciones.append(recomendacion)
    recomendaciones.sort(key=lambda r: (-r['dias_vencida'], r['nombre']))
    return recomendaciones


def analizar_fichas_terminadas(fichas, hoy=None):
    """Resumen por ficha terminada con los aprendices a remitir a comité."""
    hoy = _a_fecha(hoy) or date.today()
    resultado = []
    for ficha in fichas:
        if not ficha_terminada(ficha, hoy):
            continue
        from app.services.novedades import cargar_datos_ficha
        aprendices = Aprendiz.query.filter_by(ficha_id=ficha.id).all()
        etapas, novedades = cargar_datos_ficha(ficha.id)
        recomendaciones = analizar_ficha(ficha, aprendices, hoy, etapas, novedades)
        resultado.append({
            'ficha': ficha,
            'fecha_fin': ficha.fecha_fin,
            'dias_desde_cierre': (hoy - ficha.fecha_fin).days,
            'total_aprendices': len(aprendices),
            'recomendaciones': recomendaciones,
        })
    resultado.sort(key=lambda f: (-len(f['recomendaciones']), f['ficha'].codigo))
    return resultado


def actualizar_alertas_productiva(ficha, ahora, contexto=None, aprendices=None,
                                  etapas=None, novedades=None):
    """Crea, actualiza o resuelve las alertas de etapa productiva de la ficha."""
    from app.services.alertas import _crear_alerta
    from app.models.alertas import Alerta
    from app.services.novedades import cargar_datos_ficha

    from app.services.alertas import fecha_colombia
    hoy = fecha_colombia(ahora)
    if aprendices is None:
        aprendices = Aprendiz.query.filter_by(ficha_id=ficha.id).all()
    if etapas is None or novedades is None:
        etapas, novedades = cargar_datos_ficha(ficha.id)
    vigentes = set()
    for aprendiz in aprendices:
        recomendacion = evaluar_aprendiz_productiva(
            aprendiz, ficha, hoy, etapas.get(aprendiz.id), novedades.get(aprendiz.id, ()))
        if not recomendacion:
            continue
        vigentes.add(aprendiz.id)
        detalle = {
            'motivo': TIPO_ALERTA,
            'accion': recomendacion['accion'],
            'fecha_fin_ficha': recomendacion['fecha_fin_ficha'].isoformat(),
            'dias_vencida': recomendacion['dias_vencida'],
            'estado_aprendiz': recomendacion['estado'],
            'advertencias': recomendacion['advertencias'],
            'fundamentos': recomendacion['fundamentos'],
            'fundamento': recomendacion['fundamentos'][0],
            'reglamento': recomendacion['fundamentos'][0]['referencia'],
        }
        _crear_alerta(
            ficha, aprendiz, TIPO_ALERTA, recomendacion['nivel'],
            recomendacion['titulo'], recomendacion['motivo'], detalle, ahora,
            contexto=contexto,
        )

    abiertas = Alerta.query.filter(
        Alerta.ficha_id == ficha.id,
        Alerta.tipo == TIPO_ALERTA,
        Alerta.estado == 'activa',
    ).all()
    for alerta in abiertas:
        if alerta.aprendiz_id not in vigentes:
            alerta.estado = 'resuelta'
            alerta.fecha_resuelta = ahora
    return len(vigentes)
