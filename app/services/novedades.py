"""Novedades del aprendiz y etapa productiva (Acuerdo 009 de 2024).

- Art. 18, num. 2 (pág. 22): aplazamiento hasta 3 meses, ampliable 3 más por el comité.
- Art. 18, num. 3 (pág. 23): solicitar el reintegro dentro de los 5 días hábiles previos
  al vencimiento del aplazamiento.
- Art. 30, num. 3 (pág. 31): hay deserción si no se gestiona el reintegro al menos 3 días
  hábiles antes de la fecha fin del aplazamiento.
El panel avisa al entrar en la ventana de 5 días y recomienda comité al pasar el límite
de 3 días, citando ambas normas.
"""

from collections import defaultdict
from datetime import date, datetime

from app import db
from app.models.aprendiz import normalizar_estado
from app.models.novedades import (
    ALTERNATIVAS_PRODUCTIVA, CAUSAS_APLAZAMIENTO, ESTADOS_NOVEDAD, ESTADOS_PRODUCTIVA,
    MOMENTOS_SEGUIMIENTO, TIPOS_NOVEDAD, EtapaProductiva, NovedadAprendiz, SeguimientoProductiva,
)
from app.services.debido_proceso import restar_dias_habiles
from app.services.normativa_sena import fundamentos_de
from app.services.periodo_formacion import _restar_meses

TIPO_ALERTA_REINTEGRO = 'reintegro_vencido'
DIAS_HABILES_AVISO_REINTEGRO = 5
DIAS_HABILES_LIMITE_REINTEGRO = 3
MESES_APLAZAMIENTO = 3
MESES_AMPLIACION = 3
ESTADOS_SIN_CULMINAR = (
    'EN', 'EN_FORMACION', 'INDUCCION', 'CONDICIONADO', 'APLAZADO', 'EN_APLAZAMIENTO',
)


class ErrorNovedad(ValueError):
    """Los datos de la novedad o de la etapa productiva no cumplen el reglamento."""


def _a_fecha(valor):
    return valor.date() if isinstance(valor, datetime) else valor


def sumar_meses(fecha, meses):
    return _restar_meses(fecha, -meses)


def fecha_fin_maxima_aplazamiento(fecha_inicio, ampliacion=False):
    meses = MESES_APLAZAMIENTO + (MESES_AMPLIACION if ampliacion else 0)
    return sumar_meses(fecha_inicio, meses)


def registrar_novedad(aprendiz, ficha, tipo, fecha_solicitud, estado='solicitada',
                      fecha_inicio=None, fecha_fin=None, causa=None, ampliacion=False,
                      observacion=None, instructor_id=None, acta_comite=None):
    """Valida y guarda una novedad del Art. 18."""
    if tipo not in TIPOS_NOVEDAD:
        raise ErrorNovedad('El tipo de novedad no es válido.')
    if estado not in ESTADOS_NOVEDAD:
        raise ErrorNovedad('El estado de la novedad no es válido.')
    fecha_solicitud = _a_fecha(fecha_solicitud)
    if not fecha_solicitud:
        raise ErrorNovedad('Indica la fecha de solicitud de la novedad.')
    fecha_inicio, fecha_fin = _a_fecha(fecha_inicio), _a_fecha(fecha_fin)
    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        raise ErrorNovedad('La fecha fin no puede ser anterior a la fecha de inicio.')
    if tipo == 'aplazamiento':
        if not fecha_inicio or not fecha_fin:
            raise ErrorNovedad('El aplazamiento requiere fecha de inicio y fecha fin.')
        if causa not in CAUSAS_APLAZAMIENTO:
            raise ErrorNovedad(
                'Selecciona la causa del aplazamiento (Art. 18, num. 2, literales a a f, pág. 22).')
        maxima = fecha_fin_maxima_aplazamiento(fecha_inicio, ampliacion)
        if fecha_fin > maxima:
            plazo = '6 meses con la ampliación' if ampliacion else '3 meses'
            raise ErrorNovedad(
                f'El aplazamiento supera {plazo} (termina después del {maxima:%d/%m/%Y}). '
                'Acuerdo 009 de 2024, Art. 18, num. 2, pág. 22.')
    else:
        causa, ampliacion = None, False
    acta_comite = (acta_comite or '').strip() or None
    if ampliacion and estado == 'autorizada' and not acta_comite:
        # La ampliación la recomienda el comité (Art. 18, num. 2): sin acta queda solicitada.
        estado = 'solicitada'
    novedad = NovedadAprendiz(
        acta_comite=acta_comite,
        aprendiz_id=aprendiz.id, ficha_id=ficha.id, tipo=tipo, estado=estado,
        fecha_solicitud=fecha_solicitud, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        causa=causa, ampliacion=bool(ampliacion),
        observacion=(observacion or '').strip() or None, creado_por=instructor_id,
    )
    db.session.add(novedad)
    db.session.commit()
    return novedad


TRANSICIONES_NOVEDAD = {
    'solicitada': {'autorizada', 'negada'},
    'autorizada': set(),
    'negada': set(),
}


def cambiar_estado_novedad(novedad, estado, instructor_id=None, acta_comite=None):
    """Decide una novedad solicitada. Una decisión tomada no se revierte aquí."""
    if estado not in ESTADOS_NOVEDAD:
        raise ErrorNovedad('El estado de la novedad no es válido.')
    if estado not in TRANSICIONES_NOVEDAD.get(novedad.estado, set()):
        raise ErrorNovedad(
            f'Una novedad {novedad.etiqueta_estado.lower()} no puede pasar a '
            f'«{ESTADOS_NOVEDAD[estado].lower()}». Registre una nueva solicitud si cambió la situación.')
    acta_comite = (acta_comite or '').strip() or novedad.acta_comite
    if estado == 'autorizada' and novedad.ampliacion and not acta_comite:
        raise ErrorNovedad(
            'La ampliación del aplazamiento la recomienda el comité (Art. 18, num. 2): '
            'registre el número del acta para autorizarla.')
    novedad.estado = estado
    novedad.acta_comite = acta_comite
    novedad.estado_cambiado_en = datetime.utcnow()
    novedad.estado_cambiado_por = instructor_id
    db.session.commit()
    return novedad


def ultimo_aplazamiento(novedades):
    """Aplazamiento autorizado más reciente de una lista de novedades."""
    aplazamientos = [
        n for n in novedades
        if n.tipo == 'aplazamiento' and n.estado == 'autorizada' and n.fecha_fin
    ]
    return max(aplazamientos, key=lambda n: (n.fecha_fin, n.id or 0), default=None)


def _reintegros(novedades, aplazamiento):
    desde = aplazamiento.fecha_inicio or aplazamiento.fecha_solicitud
    return [
        n for n in novedades
        if n.tipo == 'reintegro' and n.estado != 'negada'
        and n.fecha_solicitud is not None and desde is not None and n.fecha_solicitud >= desde
    ]


def tiene_reintegro(novedades, aplazamiento):
    """True si el reintegro se solicitó a tiempo: a más tardar 3 días hábiles antes del fin.

    Uno presentado después del límite no extingue la causal del Art. 30, num. 3:
    queda como reintegro tardío para que el instructor y el comité decidan.
    """
    limite = fechas_reintegro(aplazamiento)['limite']
    return any(n.fecha_solicitud <= limite for n in _reintegros(novedades, aplazamiento))


def reintegro_tardio(novedades, aplazamiento):
    """Solicitud de reintegro presentada después del límite, o None."""
    limite = fechas_reintegro(aplazamiento)['limite']
    tardios = [n for n in _reintegros(novedades, aplazamiento) if n.fecha_solicitud > limite]
    return min(tardios, key=lambda n: n.fecha_solicitud, default=None)


def fechas_reintegro(aplazamiento):
    """Fecha de aviso (5 hábiles antes, Art. 18) y límite (3 hábiles antes, Art. 30)."""
    return {
        'aviso': restar_dias_habiles(aplazamiento.fecha_fin, DIAS_HABILES_AVISO_REINTEGRO),
        'limite': restar_dias_habiles(aplazamiento.fecha_fin, DIAS_HABILES_LIMITE_REINTEGRO),
        'fin': aplazamiento.fecha_fin,
    }


def dias_aplazados_despues_de(novedades, desde, hasta):
    """Días autorizados de aplazamiento que caen entre ``desde`` y ``hasta``."""
    total = 0
    for n in novedades or []:
        if n.tipo != 'aplazamiento' or n.estado != 'autorizada' or not n.fecha_inicio or not n.fecha_fin:
            continue
        inicio, fin = max(n.fecha_inicio, desde), min(n.fecha_fin, hasta)
        if fin >= inicio:
            total += (fin - inicio).days + 1
    return total


def aplazamiento_vigente(novedades, hoy):
    """Aplazamiento autorizado cuya fecha fin aún no pasa, o None."""
    aplazamiento = ultimo_aplazamiento(novedades)
    if aplazamiento and _a_fecha(hoy) <= aplazamiento.fecha_fin:
        return aplazamiento
    return None


def evaluar_reintegro(aprendiz, novedades, hoy):
    """Recomendación por reintegro no gestionado, o None si no aplica."""
    hoy = _a_fecha(hoy)
    if normalizar_estado(aprendiz.estado) not in ESTADOS_SIN_CULMINAR:
        return None
    aplazamiento = ultimo_aplazamiento(novedades)
    if not aplazamiento or tiene_reintegro(novedades, aplazamiento):
        return None
    fechas = fechas_reintegro(aplazamiento)
    tardio = reintegro_tardio(novedades, aplazamiento)
    if hoy > fechas['limite']:
        nivel = 'roja'
        if tardio:
            titulo = 'Reintegro tardío: revise el caso con el comité'
            motivo = (
                f'El aprendiz solicitó el reintegro el {tardio.fecha_solicitud:%d/%m/%Y}, '
                f'después del límite del {fechas["limite"]:%d/%m/%Y}. La solicitud tardía no '
                'extingue la causal del Acuerdo 009 de 2024, Art. 30, num. 3 (pág. 31); el '
                'comité valora si la acepta.'
            )
        else:
            titulo = 'Remitir a comité: no solicitó el reintegro a tiempo'
            motivo = (
                f'El aplazamiento termina el {fechas["fin"]:%d/%m/%Y} y no hay solicitud de '
                f'reintegro registrada. El límite era el {fechas["limite"]:%d/%m/%Y}. El Acuerdo 009 '
                'de 2024, Art. 30, num. 3 (pág. 31), lo define como deserción por falta de gestión '
                'oportuna de novedades.'
            )
        claves = ['aplazamiento_vencido', 'reintegro_solicitud', 'procedimiento_comite',
                  'debido_proceso']
    elif hoy >= fechas['aviso']:
        nivel = 'amarilla'
        titulo = 'El aprendiz debe solicitar el reintegro'
        motivo = (
            f'El aplazamiento termina el {fechas["fin"]:%d/%m/%Y}. Según el Art. 18, num. 3 '
            f'(pág. 23), el reintegro se solicita dentro de los 5 días hábiles previos; si no lo '
            f'gestiona a más tardar el {fechas["limite"]:%d/%m/%Y} se configura la causal del '
            'Art. 30, num. 3 (pág. 31).'
        )
        claves = ['reintegro_solicitud', 'aplazamiento_vencido']
    else:
        return None
    return {
        'aprendiz_id': aprendiz.id,
        'nivel': nivel,
        'titulo': titulo,
        'motivo': motivo,
        'fechas': fechas,
        'fundamentos': fundamentos_de(*claves),
    }


def registrar_etapa_productiva(aprendiz, ficha, alternativa, estado='por_iniciar', empresa=None,
                               fecha_inicio=None, fecha_fin_estimada=None,
                               planeacion_avalada=False, fecha_aval=None,
                               instructor_seguimiento=None):
    """Crea o actualiza la etapa productiva del aprendiz en la ficha."""
    if alternativa not in ALTERNATIVAS_PRODUCTIVA:
        raise ErrorNovedad('Selecciona una alternativa de etapa productiva válida.')
    if estado not in ESTADOS_PRODUCTIVA:
        raise ErrorNovedad('El estado de la etapa productiva no es válido.')
    fecha_inicio, fecha_fin_estimada = _a_fecha(fecha_inicio), _a_fecha(fecha_fin_estimada)
    fecha_aval = _a_fecha(fecha_aval)
    if fecha_inicio and fecha_fin_estimada and fecha_fin_estimada < fecha_inicio:
        raise ErrorNovedad('La fecha fin estimada no puede ser anterior a la de inicio.')
    if planeacion_avalada and not fecha_aval:
        raise ErrorNovedad('Indica la fecha en que se avaló la planeación de la etapa productiva.')
    etapa = EtapaProductiva.query.filter_by(aprendiz_id=aprendiz.id, ficha_id=ficha.id).first()
    if etapa is None:
        etapa = EtapaProductiva(aprendiz_id=aprendiz.id, ficha_id=ficha.id)
        db.session.add(etapa)
    etapa.alternativa = alternativa
    etapa.estado = estado
    etapa.empresa = (empresa or '').strip() or None
    etapa.fecha_inicio = fecha_inicio
    etapa.fecha_fin_estimada = fecha_fin_estimada
    etapa.planeacion_avalada = bool(planeacion_avalada)
    etapa.fecha_aval = fecha_aval if planeacion_avalada else None
    etapa.instructor_seguimiento = (instructor_seguimiento or '').strip() or None
    db.session.commit()
    return etapa


def registrar_seguimiento(etapa, momento, fecha, observacion=None, instructor_id=None):
    """Registra un momento de seguimiento; cada momento se registra una sola vez."""
    if momento not in MOMENTOS_SEGUIMIENTO:
        raise ErrorNovedad('El momento de seguimiento no es válido.')
    fecha = _a_fecha(fecha)
    if not fecha:
        raise ErrorNovedad('Indica la fecha del seguimiento.')
    registrados = {s.momento for s in etapa.seguimientos}
    if momento in registrados:
        raise ErrorNovedad(f'Ya se registró el momento «{MOMENTOS_SEGUIMIENTO[momento]}».')
    if momento != 'concertacion' and 'concertacion' not in registrados:
        raise ErrorNovedad('Registra primero la concertación de la etapa productiva.')
    seguimiento = SeguimientoProductiva(
        etapa_id=etapa.id, momento=momento, fecha=fecha,
        observacion=(observacion or '').strip() or None, creado_por=instructor_id,
    )
    db.session.add(seguimiento)
    db.session.commit()
    db.session.refresh(etapa)
    return seguimiento


def cargar_datos_ficha(ficha_id):
    """Etapas y novedades de la ficha en dos consultas, indexadas por aprendiz."""
    etapas = {
        e.aprendiz_id: e for e in EtapaProductiva.query.filter_by(ficha_id=ficha_id).all()
    }
    novedades = defaultdict(list)
    for novedad in NovedadAprendiz.query.filter_by(ficha_id=ficha_id).order_by(
            NovedadAprendiz.fecha_solicitud.asc(), NovedadAprendiz.id.asc()).all():
        novedades[novedad.aprendiz_id].append(novedad)
    return etapas, novedades


def actualizar_alertas_reintegro(ficha, ahora, aprendices, novedades, contexto=None):
    """Crea, actualiza o resuelve las alertas por reintegro no gestionado."""
    from app.models.alertas import Alerta
    from app.services.alertas import _crear_alerta

    from app.services.alertas import fecha_colombia
    hoy = fecha_colombia(ahora)
    vigentes = set()
    for aprendiz in aprendices:
        recomendacion = evaluar_reintegro(aprendiz, novedades.get(aprendiz.id, []), hoy)
        if not recomendacion:
            continue
        vigentes.add(aprendiz.id)
        fechas = recomendacion['fechas']
        detalle = {
            'motivo': TIPO_ALERTA_REINTEGRO,
            'fecha_fin_aplazamiento': fechas['fin'].isoformat(),
            'fecha_limite_reintegro': fechas['limite'].isoformat(),
            'fundamentos': recomendacion['fundamentos'],
            'fundamento': recomendacion['fundamentos'][0],
            'reglamento': recomendacion['fundamentos'][0]['referencia'],
        }
        _crear_alerta(ficha, aprendiz, TIPO_ALERTA_REINTEGRO, recomendacion['nivel'],
                      recomendacion['titulo'], recomendacion['motivo'], detalle, ahora,
                      contexto=contexto)
    for alerta in Alerta.query.filter_by(ficha_id=ficha.id, tipo=TIPO_ALERTA_REINTEGRO,
                                         estado='activa').all():
        if alerta.aprendiz_id not in vigentes:
            alerta.estado = 'resuelta'
            alerta.fecha_resuelta = ahora
    return len(vigentes)


def resumen_aprendiz(aprendiz, etapa, novedades, hoy=None):
    """Datos listos para la vista de novedades y etapa productiva."""
    hoy = _a_fecha(hoy) or date.today()
    aplazamiento = ultimo_aplazamiento(novedades)
    from app.models.aprendiz import etiqueta_estado

    return {
        'aprendiz': aprendiz,
        'estado_etiqueta': etiqueta_estado(aprendiz.estado),
        'etapa': etapa,
        'novedades': list(reversed(novedades)),
        'aplazamiento': aplazamiento,
        'fechas_reintegro': fechas_reintegro(aplazamiento) if aplazamiento else None,
        'reintegro_solicitado': bool(aplazamiento and tiene_reintegro(novedades, aplazamiento)),
        'recomendacion': evaluar_reintegro(aprendiz, novedades, hoy),
        'momentos': {s.momento for s in etapa.seguimientos} if etapa else set(),
    }
