"""Debido proceso del Reglamento del Aprendiz (Acuerdo 009 de 2024).

- Plazos en días hábiles con festivos de Colombia (Art. 28 par. 3; Art. 51).
- Llamados de atención escritos y sus topes (Art. 46, num. 1 lit. a y num. 2 lit. a).
- Validación del plan de mejoramiento académico (Art. 46, num. 1 lit. b y par. 1).
- Expediente para el comité de evaluación y seguimiento (Art. 51, num. 1 y 2).

Los planes registran la fase del proyecto formativo: el tope de planes y los
llamados previos se cuentan por fase. Los topes se informan como advertencias.
Un llamado anulado conserva su registro, pero no cuenta para ningún tope.
"""

from datetime import date, datetime, timedelta

from app import db
from app.models.alertas import LlamadoAtencion, PlanMejoramiento
from app.services.festivos import es_dia_habil
from app.services.normativa_sena import fundamentos_de
from app.services.periodo_formacion import obtener_periodo_formacion

DIAS_HABILES_JUSTIFICACION = 5
DIAS_HABILES_CITACION = 3
DIAS_HABILES_SESION_COMITE = 10
MAX_DIAS_PLAN = 20
MAX_LLAMADOS = 2
MAX_PLANES_POR_ETAPA = {'lectiva': 2, 'productiva': 1}

TIPOS_LLAMADO = {'academico': 'Académico', 'disciplinario': 'Disciplinario'}
FASES_PROYECTO = ('analisis', 'planeacion', 'ejecucion', 'evaluacion')
ETIQUETAS_FASE = {
    'analisis': 'Análisis', 'planeacion': 'Planeación',
    'ejecucion': 'Ejecución', 'evaluacion': 'Evaluación',
}


class ReglaDebidoProceso(ValueError):
    """Una acción contradice un tope del reglamento."""


def _a_fecha(valor):
    return valor.date() if isinstance(valor, datetime) else valor


def sumar_dias_habiles(desde, dias):
    """Fecha que resulta de contar `dias` hábiles después de `desde` (sin incluirla)."""
    if dias < 0:
        raise ValueError('La cantidad de días hábiles no puede ser negativa.')
    fecha = _a_fecha(desde)
    contados = 0
    while contados < dias:
        fecha += timedelta(days=1)
        if es_dia_habil(fecha):
            contados += 1
    return fecha


def restar_dias_habiles(hasta, dias):
    """Fecha que queda `dias` hábiles antes de `hasta` (sin incluirla)."""
    if dias < 0:
        raise ValueError('La cantidad de días hábiles no puede ser negativa.')
    fecha = _a_fecha(hasta)
    contados = 0
    while contados < dias:
        fecha -= timedelta(days=1)
        if es_dia_habil(fecha):
            contados += 1
    return fecha


def fecha_limite_justificacion(fecha_falta, dias=DIAS_HABILES_JUSTIFICACION):
    """Último día para justificar una inasistencia no programada (Art. 28, par. 3)."""
    return sumar_dias_habiles(fecha_falta, dias)


def etapa_en(ficha, fecha):
    """'productiva' si la fecha cae en la etapa productiva o después; si no, 'lectiva'."""
    periodo = obtener_periodo_formacion(ficha, _a_fecha(fecha))
    return 'productiva' if periodo['fase'] in ('productiva', 'finalizada') else 'lectiva'


def _llamados(aprendiz_id, tipo, etapa=None, fase=None):
    consulta = LlamadoAtencion.query.filter_by(aprendiz_id=aprendiz_id, tipo=tipo).filter(
        LlamadoAtencion.anulado_en.is_(None)
    )
    if etapa is not None:
        consulta = consulta.filter_by(etapa=etapa)
    if fase is not None:
        consulta = consulta.filter_by(fase=fase)
    return consulta.order_by(LlamadoAtencion.fecha.asc(), LlamadoAtencion.id.asc()).all()


def registrar_llamado(aprendiz, ficha, tipo, descripcion, instructor_id=None,
                      orientaciones=None, fase=None, fecha=None, alerta_id=None):
    """Registra un llamado escrito respetando los topes del Art. 46.

    Académico: hasta dos por fase del proyecto formativo; el segundo exige
    orientaciones escritas. Disciplinario: hasta dos durante todo el programa;
    el segundo exige recomendaciones de mejoramiento.
    """
    if tipo not in TIPOS_LLAMADO:
        raise ReglaDebidoProceso('El tipo de llamado debe ser académico o disciplinario.')
    descripcion = (descripcion or '').strip()
    if not descripcion:
        raise ReglaDebidoProceso('Describe los hechos que motivan el llamado de atención.')
    if fase is not None and fase not in FASES_PROYECTO:
        raise ReglaDebidoProceso('La fase del proyecto formativo no es válida.')
    if tipo == 'academico' and fase is None:
        raise ReglaDebidoProceso('Indica la fase del proyecto formativo del llamado académico.')
    fecha = _a_fecha(fecha) or date.today()
    if fecha > date.today():
        raise ReglaDebidoProceso('La fecha del llamado no puede ser posterior a hoy.')
    etapa = etapa_en(ficha, fecha)

    if tipo == 'academico':
        previos = _llamados(aprendiz.id, tipo, etapa=etapa, fase=fase)
        alcance = f'la fase de {ETIQUETAS_FASE[fase].lower()}'
    else:
        previos = _llamados(aprendiz.id, tipo)
        alcance = 'el programa'
    if len(previos) >= MAX_LLAMADOS:
        siguiente = 'un plan de mejoramiento' if tipo == 'academico' else 'un plan de mejoramiento disciplinario'
        raise ReglaDebidoProceso(
            f'El aprendiz ya tiene {MAX_LLAMADOS} llamados {TIPOS_LLAMADO[tipo].lower()}s en '
            f'{alcance}. Según el Art. 46 del Acuerdo 009 de 2024 corresponde {siguiente}.'
        )
    numero = len(previos) + 1
    orientaciones = (orientaciones or '').strip() or None
    if numero == MAX_LLAMADOS and not orientaciones:
        raise ReglaDebidoProceso(
            'El segundo llamado debe incluir orientaciones o recomendaciones escritas '
            '(Art. 46 del Acuerdo 009 de 2024).'
        )
    llamado = LlamadoAtencion(
        aprendiz_id=aprendiz.id, ficha_id=ficha.id, tipo=tipo, etapa=etapa, fase=fase,
        numero=numero, fecha=fecha, descripcion=descripcion, orientaciones=orientaciones,
        alerta_id=alerta_id, creado_por=instructor_id,
    )
    db.session.add(llamado)
    db.session.flush()
    from app.services.alertas import registrar_notificacion
    registrar_notificacion(
        'aprendiz', aprendiz.id,
        f'Tu instructor registró un llamado de atención {TIPOS_LLAMADO[tipo].lower()} '
        f'por escrito ({numero} de {MAX_LLAMADOS}). Revisa los compromisos en tu panel; '
        'allí puedes dejar tus descargos por escrito.',
        'alerta', f'llamado:{llamado.id}', ficha.id,
        f'/aprendiz/{ficha.id}/panel',
    )
    db.session.commit()
    return llamado


def anular_llamado(llamado, motivo, instructor_id=None):
    """Anula un llamado mal registrado: queda en el expediente con su motivo."""
    motivo = (motivo or '').strip()
    if not motivo:
        raise ReglaDebidoProceso('Indica el motivo para anular el llamado de atención.')
    if llamado.anulado_en is not None:
        raise ReglaDebidoProceso('Este llamado de atención ya estaba anulado.')
    llamado.anulado_en = datetime.utcnow()
    llamado.anulado_por = instructor_id
    llamado.motivo_anulacion = motivo
    from app.services.alertas import registrar_notificacion
    registrar_notificacion(
        'aprendiz', llamado.aprendiz_id,
        'Tu instructor anuló un llamado de atención registrado. Ya no cuenta en tu proceso.',
        'alerta', f'llamado-anulado:{llamado.id}', llamado.ficha_id,
        f'/aprendiz/{llamado.ficha_id}/panel',
    )
    db.session.commit()
    return llamado


def registrar_descargos(llamado, texto):
    """Guarda la versión del aprendiz sobre un llamado vigente (derecho de defensa)."""
    texto = (texto or '').strip()
    if not texto:
        raise ReglaDebidoProceso('Escribe tus descargos antes de enviarlos.')
    if llamado.anulado_en is not None:
        raise ReglaDebidoProceso('Este llamado fue anulado; no necesitas presentar descargos.')
    llamado.descargos = texto
    llamado.descargos_en = datetime.utcnow()
    db.session.commit()
    return llamado


def validar_plan(aprendiz_id, ficha, fecha_creacion, fecha_limite, fase=None):
    """Errores que impiden crear el plan y advertencias que el instructor debe ver.

    Los llamados previos y el tope de planes se cuentan en la fase del proyecto
    formativo indicada; sin fase, en toda la etapa.
    """
    errores, advertencias = [], []
    if fase is not None and fase not in FASES_PROYECTO:
        errores.append('La fase del proyecto formativo no es válida.')
        return errores, advertencias
    creacion = _a_fecha(fecha_creacion)
    limite = _a_fecha(fecha_limite)
    if limite is None:
        errores.append('Indica la fecha límite del plan: no puede superar 20 días calendario.')
    elif limite < creacion:
        errores.append('La fecha límite no puede ser anterior a la fecha de creación del plan.')
    elif (limite - creacion).days > MAX_DIAS_PLAN:
        errores.append(
            f'El plan dura {(limite - creacion).days} días y el máximo es {MAX_DIAS_PLAN} días '
            'calendario (Acuerdo 009 de 2024, Art. 46, num. 1, lit. b, pág. 37).'
        )

    etapa = etapa_en(ficha, creacion)
    por_fase = fase is not None and etapa == 'lectiva'
    alcance = f'la fase de {ETIQUETAS_FASE[fase].lower()}' if por_fase else f'la etapa {etapa}'
    llamados = _llamados(aprendiz_id, 'academico', etapa=etapa, fase=fase if por_fase else None)
    if len(llamados) < MAX_LLAMADOS:
        advertencias.append(
            f'El aprendiz tiene {len(llamados)} llamado(s) académico(s) escrito(s) en '
            f'{alcance}. El reglamento prevé el plan después de dos llamados '
            '(Art. 46, num. 1, pág. 37).'
        )
    planes = sum(
        1 for plan in PlanMejoramiento.query.filter_by(aprendiz_id=aprendiz_id, ficha_id=ficha.id)
        if etapa_en(ficha, plan.fecha_creacion) == etapa
        and (not por_fase or plan.fase == fase)
    )
    tope = MAX_PLANES_POR_ETAPA[etapa]
    if planes >= tope:
        regla = 'por fase o módulo' if etapa == 'lectiva' else 'en la etapa productiva'
        advertencias.append(
            f'Ya hay {planes} plan(es) en {alcance}. El tope es {tope} {regla} '
            '(Art. 46, parágrafo 1, pág. 37).'
        )
    return errores, advertencias


def plazos_comite(fecha_informe):
    """Plazos del Art. 51 contados desde el recibo del informe o queja."""
    fecha_informe = _a_fecha(fecha_informe)
    return {
        'fecha_informe': fecha_informe,
        'citacion_limite': sumar_dias_habiles(fecha_informe, DIAS_HABILES_CITACION),
        'sesion_limite': sumar_dias_habiles(fecha_informe, DIAS_HABILES_SESION_COMITE),
    }


CONTENIDO_CITACION = (
    'a) Relación del informe o queja con copia de las pruebas existentes.',
    'b) Identificación del aprendiz, programa de formación y grupo.',
    'c) Normas del reglamento presuntamente infringidas.',
    'd) Tipo de falta: académica o disciplinaria.',
    'e) Calificación provisional de la falta.',
    'f) Solicitud de descargos y derecho a controvertir y aportar pruebas.',
    'g) Lugar, fecha y hora de la sesión del comité.',
)


TIPOS_DESERCION = {'comite_desercion', 'productiva_vencida', 'reintegro_vencido'}
TIPOS_DISCIPLINARIOS = {'observador'}


def tipo_falta_de(tipos):
    """Rótulo del caso según las causales de sus alertas."""
    tipos = set(tipos)
    rotulos = []
    if tipos & TIPOS_DESERCION:
        rotulos.append('Deserción (Art. 30)')
    if tipos - TIPOS_DESERCION - TIPOS_DISCIPLINARIOS:
        rotulos.append('académica')
    if tipos & TIPOS_DISCIPLINARIOS:
        rotulos.append('disciplinaria')
    if not rotulos:
        return 'Académica'
    texto = ' y '.join(rotulos)
    return texto[0].upper() + texto[1:]


def armar_expediente(ficha, aprendiz, alertas, fecha_informe=None):
    """Datos del informe al comité: normas, medidas previas y plazos (Art. 51)."""
    fundamentos, claves = [], set()
    tipos = set()
    for alerta in alertas:
        tipos.add(alerta.tipo)
        detalle = alerta.detalle_json or {}
        propios = list(detalle.get('fundamentos') or [])
        if not propios and detalle.get('fundamento'):
            propios = [detalle['fundamento']]
        for fundamento in propios:
            if fundamento.get('clave') not in claves:
                claves.add(fundamento.get('clave'))
                fundamentos.append(fundamento)
    for fundamento in fundamentos_de('procedimiento_comite', 'citacion_comite', 'debido_proceso'):
        if fundamento['clave'] not in claves:
            fundamentos.append(fundamento)
    llamados = (
        LlamadoAtencion.query.filter_by(aprendiz_id=aprendiz.id, ficha_id=ficha.id)
        .filter(LlamadoAtencion.anulado_en.is_(None))
        .order_by(LlamadoAtencion.fecha.asc(), LlamadoAtencion.id.asc()).all()
    )
    planes = (
        PlanMejoramiento.query.filter_by(aprendiz_id=aprendiz.id, ficha_id=ficha.id)
        .order_by(PlanMejoramiento.fecha_creacion.asc()).all()
    )
    if fecha_informe is None:
        # El plazo corre desde la remisión del caso, no desde que se abre el expediente.
        fechas = [a.fecha_escalada for a in alertas if getattr(a, 'fecha_escalada', None)]
        fecha_informe = min(fechas) if fechas else date.today()
    return {
        'tipo_falta': tipo_falta_de(tipos),
        'fundamentos': fundamentos,
        'llamados': llamados,
        'planes': planes,
        'plazos': plazos_comite(fecha_informe),
        'contenido_citacion': CONTENIDO_CITACION,
    }
