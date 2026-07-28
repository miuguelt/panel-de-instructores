from collections import defaultdict
from datetime import date, datetime, timedelta
from email.message import EmailMessage
import smtplib

from flask import current_app
from sqlalchemy.orm import joinedload

from app import db
from app.models.alertas import (
    Alerta,
    ConfiguracionAlertas,
    ConfiguracionAlertasComite,
    Notificacion,
    PlanMejoramiento,
)
from app.models.aprendiz import Aprendiz
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.models.ficha import Ficha
from app.models.instructor import Instructor
from app.models.ficha_instructor import FichaInstructor
from app.models.tarea import Entrega, Tarea
from app.services.asistencia import contar_sesiones_registradas


# ─────────────────────────────────────────────
# REGLAMENTO DEL APRENDIZ SENA — Resolución 009 de 2024
# ─────────────────────────────────────────────
# Art. 22: Faltas académicas
#   - 3 inasistencias consecutivas injustificadas → comité
#   - 5 inasistencias injustificadas en 3 meses → comité
#   - Inasistencia >= 25% del total de horas → causal de deserción
#   - Incumplimiento recurrente de evidencias → plan de mejoramiento
#
# Art. 28: Proceso formativo
#   a) Llamado de atención verbal
#   b) Plan de mejoramiento académico
#   c) Comité de evaluación y seguimiento
# ─────────────────────────────────────────────


_SIN_CARGAR = object()


class ContextoFicha:
    """Datos de una ficha cargados de una sola vez para evaluar a todos sus aprendices.

    Las reglas del reglamento se evaluan aprendiz por aprendiz. Consultadas de
    forma individual, una ficha de 30 aprendices con 20 sesiones y 10 tareas
    disparaba cientos de SELECT por peticion (un COUNT de faltas por aprendiz,
    un SELECT de entrega por tarea y aprendiz...). Aqui se traen los mismos
    datos en cuatro consultas y las funciones de calculo leen de estos indices.
    """

    def __init__(self, ficha_id, ahora=None):
        self.ficha_id = ficha_id
        self.ahora = ahora or datetime.utcnow()

        # aprendiz_id -> [(fecha_sesion, estado)] ordenado por fecha ascendente
        self.asistencia = defaultdict(list)
        filas = (
            db.session.query(
                RegistroAsistencia.aprendiz_id,
                SesionAsistencia.fecha,
                RegistroAsistencia.estado,
            )
            .join(SesionAsistencia, RegistroAsistencia.sesion_id == SesionAsistencia.id)
            .filter(SesionAsistencia.ficha_id == ficha_id)
            .order_by(SesionAsistencia.fecha.asc())
            .all()
        )
        for aprendiz_id, fecha, estado in filas:
            self.asistencia[aprendiz_id].append((fecha, estado))

        self.total_sesiones = contar_sesiones_registradas(ficha_id)
        self.tareas = Tarea.query.filter_by(ficha_id=ficha_id).all()

        # aprendiz_id -> {tarea_id: entrega mas reciente}
        self.entregas = defaultdict(dict)
        entregas = (
            Entrega.query
            .join(Tarea, Entrega.tarea_id == Tarea.id)
            .filter(Tarea.ficha_id == ficha_id)
            .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
            .all()
        )
        for entrega in entregas:
            self.entregas[entrega.aprendiz_id].setdefault(entrega.tarea_id, entrega)

        # Se llenan bajo demanda: solo actualizar_alertas_ficha los necesita.
        self._alertas = None
        self._claves_notificacion = None
        self._instructores = None
        self._config_correo = _SIN_CARGAR

    def registros(self, aprendiz_id):
        return self.asistencia.get(aprendiz_id, [])

    def entregas_de(self, aprendiz_id):
        return self.entregas.get(aprendiz_id, {})

    def alertas_de(self, aprendiz_id):
        if self._alertas is None:
            self._alertas = defaultdict(list)
            for alerta in Alerta.query.filter(
                Alerta.ficha_id == self.ficha_id,
                Alerta.aprendiz_id.isnot(None),
            ).order_by(Alerta.fecha_generada.desc()).all():
                self._alertas[alerta.aprendiz_id].append(alerta)
        return self._alertas[aprendiz_id]

    def registrar_alerta(self, alerta):
        """Indexa una alerta recien creada para que el resto del bucle la vea."""
        if self._alertas is not None:
            self._alertas[alerta.aprendiz_id].insert(0, alerta)

    def notificacion_existe(self, destinatario_tipo, destinatario_id, clave):
        if self._claves_notificacion is None:
            self._claves_notificacion = {
                (tipo, destino, clave_existente)
                for tipo, destino, clave_existente in db.session.query(
                    Notificacion.destinatario_tipo,
                    Notificacion.destinatario_id,
                    Notificacion.clave,
                ).filter(Notificacion.ficha_id == self.ficha_id).all()
            }
        return (destinatario_tipo, destinatario_id, clave) in self._claves_notificacion

    def anotar_notificacion(self, destinatario_tipo, destinatario_id, clave):
        if self._claves_notificacion is not None:
            self._claves_notificacion.add((destinatario_tipo, destinatario_id, clave))

    def instructores(self, ficha):
        if self._instructores is None:
            self._instructores = _instructores_ficha(ficha)
        return self._instructores

    def config_correo(self):
        if self._config_correo is _SIN_CARGAR:
            self._config_correo = ConfiguracionAlertasComite.query.filter_by(
                ficha_id=self.ficha_id
            ).first()
        return self._config_correo


def obtener_config_comite(ficha_id, crear=True):
    config = ConfiguracionAlertasComite.query.filter_by(ficha_id=ficha_id).first()
    if not config and crear:
        config = ConfiguracionAlertasComite(ficha_id=ficha_id)
        db.session.add(config)
        db.session.flush()
    return config


def obtener_config_asistencia(ficha_id, crear=True):
    config = ConfiguracionAlertas.query.filter_by(ficha_id=ficha_id).first()
    if not config and crear:
        config = ConfiguracionAlertas(ficha_id=ficha_id)
        db.session.add(config)
        db.session.flush()
    return config


# ── Notificaciones ────────────────────────────


def registrar_notificacion(destinatario_tipo, destinatario_id, mensaje, tipo,
                           clave, ficha_id=None, url=None, contexto=None):
    """Crea la notificacion si no existe ya una con la misma clave.

    Con ``contexto`` la deteccion de duplicados se resuelve contra el indice de
    claves ya cargado (y devuelve None si la notificacion ya existia); sin el,
    consulta la BD como antes. El indice evita un SELECT por notificacion
    cuando se recorren todos los aprendices de una ficha.
    """
    if not destinatario_id:
        return None
    clave_recortada = clave[:180]
    if contexto is not None:
        if contexto.notificacion_existe(destinatario_tipo, destinatario_id, clave_recortada):
            return None
        contexto.anotar_notificacion(destinatario_tipo, destinatario_id, clave_recortada)
    else:
        existente = Notificacion.query.filter_by(
            destinatario_tipo=destinatario_tipo,
            destinatario_id=destinatario_id,
            clave=clave_recortada,
        ).first()
        if existente:
            return existente
    notificacion = Notificacion(
        destinatario_tipo=destinatario_tipo,
        destinatario_id=destinatario_id,
        ficha_id=ficha_id,
        mensaje=mensaje,
        tipo=tipo,
        clave=clave_recortada,
        url=url,
    )
    db.session.add(notificacion)
    _enviar_correo_opcional(destinatario_tipo, destinatario_id, mensaje, ficha_id, contexto)
    return notificacion


def _instructores_ficha(ficha):
    ids = {ficha.instructor_id}
    ids.update(v.instructor_id for v in FichaInstructor.query.filter_by(ficha_id=ficha.id).all())
    return ids


def _notificar_instructores(ficha, mensaje, tipo, clave, url, contexto=None):
    destinatarios = (
        contexto.instructores(ficha) if contexto is not None else _instructores_ficha(ficha)
    )
    for instructor_id in destinatarios:
        registrar_notificacion('instructor', instructor_id, mensaje, tipo, clave,
                               ficha.id, url, contexto=contexto)


def _enviar_correo_opcional(destinatario_tipo, destinatario_id, mensaje, ficha_id,
                            contexto=None):
    if not ficha_id or not current_app.config.get('SMTP_HOST'):
        return
    if contexto is not None:
        config = contexto.config_correo()
    else:
        config = ConfiguracionAlertasComite.query.filter_by(ficha_id=ficha_id).first()
    if not config or not config.correo_habilitado:
        return
    if destinatario_tipo == 'aprendiz':
        aprendiz = db.session.get(Aprendiz, destinatario_id)
        correo = aprendiz.correo if aprendiz else None
    else:
        instructor = db.session.get(Instructor, destinatario_id)
        correo = instructor.correo if instructor else None
    if not correo:
        return
    try:
        email = EmailMessage()
        email['Subject'] = 'SENA Control Académico - aviso informativo'
        email['From'] = current_app.config.get('SMTP_FROM') or current_app.config.get('SMTP_USER') or 'no-reply@sena.edu.co'
        email['To'] = correo
        email.set_content(mensaje)
        with smtplib.SMTP(current_app.config['SMTP_HOST'], current_app.config.get('SMTP_PORT', 587), timeout=8) as servidor:
            servidor.starttls()
            if current_app.config.get('SMTP_USER') and current_app.config.get('SMTP_PASSWORD'):
                servidor.login(current_app.config['SMTP_USER'], current_app.config['SMTP_PASSWORD'])
            servidor.send_message(email)
    except Exception as error:
        current_app.logger.warning('No fue posible enviar correo opcional: %s', error)


# ── Alertas ─────────────────────────────────


def _crear_alerta(ficha, aprendiz, tipo, nivel, titulo, mensaje, detalle, ahora,
                  contexto=None):
    if contexto is not None:
        # alertas_de() viene ordenado por fecha_generada descendente, igual que
        # la consulta original, asi que la primera coincidencia es la vigente.
        abierta = next(
            (
                a for a in contexto.alertas_de(aprendiz.id)
                if a.tipo == tipo and a.estado in ('activa', 'escalada_comite')
            ),
            None,
        )
    else:
        abierta = Alerta.query.filter(
            Alerta.ficha_id == ficha.id,
            Alerta.aprendiz_id == aprendiz.id,
            Alerta.tipo == tipo,
            Alerta.estado.in_(['activa', 'escalada_comite']),
        ).order_by(Alerta.fecha_generada.desc()).first()
    if abierta:
        cambio_nivel = abierta.nivel != nivel
        abierta.nivel = nivel
        abierta.titulo = titulo
        abierta.mensaje = mensaje
        abierta.detalle_json = detalle
        abierta.fecha_ultima_evaluacion = ahora
        if abierta.estado == 'escalada_comite':
            return abierta, False
        if cambio_nivel:
            _notificar_instructores(
                ficha, f'{aprendiz.nombre_completo}: {titulo}.', 'alerta',
                f'alerta:{abierta.id}:{nivel}',
                f'/instructor/fichas/{ficha.id}/casos-seguimiento',
                contexto=contexto,
            )
            registrar_notificacion(
                'aprendiz', aprendiz.id,
                mensaje,
                'alerta', f'alerta:{abierta.id}:{nivel}', ficha.id,
                f'/aprendiz/{ficha.id}/panel?documento={aprendiz.documento}',
                contexto=contexto,
            )
        return abierta, False

    alerta = Alerta(
        ficha_id=ficha.id,
        aprendiz_id=aprendiz.id,
        tipo=tipo,
        nivel=nivel,
        titulo=titulo,
        mensaje=mensaje,
        detalle_json=detalle,
        fecha_generada=ahora,
        fecha_ultima_evaluacion=ahora,
    )
    db.session.add(alerta)
    db.session.flush()
    if contexto is not None:
        contexto.registrar_alerta(alerta)
    _notificar_instructores(
        ficha, f'{aprendiz.nombre_completo}: {titulo}.', 'alerta',
        f'alerta:{alerta.id}:nueva',
        f'/instructor/fichas/{ficha.id}/casos-seguimiento',
        contexto=contexto,
    )
    registrar_notificacion(
        'aprendiz', aprendiz.id,
        mensaje,
        'alerta', f'alerta:{alerta.id}:nueva', ficha.id,
        f'/aprendiz/{ficha.id}/panel?documento={aprendiz.documento}',
        contexto=contexto,
    )
    return alerta, True


def _contexto(ficha_id, contexto=None, ahora=None):
    """Devuelve el contexto recibido o construye uno para un uso aislado."""
    return contexto if contexto is not None else ContextoFicha(ficha_id, ahora)


def _consecutivas_injustificadas(aprendiz_id, ficha_id, contexto=None):
    ctx = _contexto(ficha_id, contexto)
    maximo = actual = 0
    for _fecha, estado in ctx.registros(aprendiz_id):
        if estado == 'FALTA':
            actual += 1
            maximo = max(maximo, actual)
        else:
            actual = 0
    return maximo


def _faltas_esporadicas_en_ventana(aprendiz_id, ficha_id, periodo_dias=90, contexto=None):
    ctx = _contexto(ficha_id, contexto)
    inicio_ventana = date.today() - timedelta(days=periodo_dias)
    return sum(
        1
        for fecha, estado in ctx.registros(aprendiz_id)
        if estado == 'FALTA' and fecha >= inicio_ventana
    )


def _incumplimientos_academicos(aprendiz_id, ficha_id, ahora, contexto=None):
    ctx = _contexto(ficha_id, contexto, ahora)
    tareas = ctx.tareas
    por_tarea = ctx.entregas_de(aprendiz_id)

    incumplidas = []
    for tarea in tareas:
        entrega = por_tarea.get(tarea.id)
        vencida = tarea.fecha_limite and tarea.fecha_limite < ahora
        rechazada = entrega and entrega.estado_revision == 'rechazada'
        tarde = entrega and entrega.fecha_entrega and tarea.fecha_limite and entrega.fecha_entrega > tarea.fecha_limite
        if rechazada or (vencida and (not entrega or tarde)):
            incumplidas.append(tarea)
    return incumplidas


def _porcentaje_asistencia(aprendiz_id, ficha_id, contexto=None):
    ctx = _contexto(ficha_id, contexto)
    total = ctx.total_sesiones
    if total == 0:
        return 100.0
    faltas = sum(1 for _fecha, estado in ctx.registros(aprendiz_id) if estado == 'FALTA')
    return round((total - faltas) / total * 100, 1)


def _fase_ficha(ficha, hoy=None):
    hoy = hoy or date.today()
    cronograma = _obtener_cronograma(ficha, hoy)
    return cronograma.get('fase', 'lectiva') if cronograma.get('configurado') else 'lectiva'


def _obtener_cronograma(ficha, hoy=None):
    hoy = hoy or date.today()
    inicio = ficha.fecha_inicio
    fin = ficha.fecha_fin
    if not inicio or not fin or fin < inicio:
        return {'configurado': False, 'fase': 'sin_fechas'}
    meses_productiva = max(int(ficha.duracion_productiva_meses or 6), 1)
    import calendar
    total = fin.year * 12 + fin.month - 1 - meses_productiva
    ano, mes0 = divmod(total, 12)
    mes = mes0 + 1
    dia_min = min(fin.day, calendar.monthrange(ano, mes)[1]) if hasattr(calendar, 'monthrange') else fin.day
    inicio_productiva = date(ano, mes, dia_min)
    if hoy < inicio:
        fase = 'por_iniciar'
    elif hoy < inicio_productiva:
        fase = 'lectiva'
    elif hoy <= fin:
        fase = 'productiva'
    else:
        fase = 'finalizada'
    return {'configurado': True, 'fase': fase, 'inicio_productiva': inicio_productiva, 'fin': fin}


def actualizar_alertas_ficha(ficha_id, ahora=None):
    ahora = ahora or datetime.utcnow()
    hoy = ahora.date()
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        return []
    config = obtener_config_comite(ficha_id)
    fase = _fase_ficha(ficha, hoy)
    en_productiva = fase == 'productiva'
    resultados = []
    # Un solo indice para toda la ficha: sin el, cada aprendiz repetia los
    # mismos COUNT de asistencia y SELECT de entregas.
    contexto = ContextoFicha(ficha_id, ahora)

    for aprendiz in Aprendiz.query_en_formacion(ficha_id).all():
        consecutivas = _consecutivas_injustificadas(aprendiz.id, ficha_id, contexto)
        acumuladas = sum(
            1 for _fecha, estado in contexto.registros(aprendiz.id) if estado == 'FALTA'
        )
        esporadicas = _faltas_esporadicas_en_ventana(
            aprendiz.id, ficha_id, config.periodo_dias_esporadicas, contexto
        )
        incumplidas = _incumplimientos_academicos(aprendiz.id, ficha_id, ahora, contexto)
        pct_asistencia = _porcentaje_asistencia(aprendiz.id, ficha_id, contexto)
        reglas = []

        # ── R1: 3 sesiones consecutivas injustificadas → COMITÉ (Art. 22) ──
        umbral_consec = config.umbral_fallas_consecutivas
        if consecutivas >= umbral_consec:
            reglas.append((
                'comite_desercion', 'roja',
                f'Riesgo de deserción: {consecutivas} sesiones seguidas sin justificar',
                f'{aprendiz.nombre}: registra {consecutivas} inasistencias consecutivas sin '
                'justificación. La Resolución 009 indica que esto activa proceso de comité.',
                {
                    'motivo': 'consecutivas_injustificadas',
                    'fallas_consecutivas': consecutivas,
                    'umbral': umbral_consec,
                    'reglamento': 'Res. 009 Art. 22',
                },
            ))
        # ── R2: 5 faltas esporádicas en 3 meses → COMITÉ (Art. 22) ──
        elif esporadicas >= config.umbral_fallas_esporadicas:
            meses = round(config.periodo_dias_esporadicas / 30)
            reglas.append((
                'comite_desercion', 'roja',
                f'Riesgo de deserción: {esporadicas} faltas en {meses} meses',
                f'{aprendiz.nombre}: {esporadicas} inasistencias injustificadas '
                f'en los últimos {meses} meses. La Resolución 009 establece '
                f'{config.umbral_fallas_esporadicas} faltas en este período como causal de comité.',
                {
                    'motivo': 'esporadicas_trimestre',
                    'fallas_esporadicas': esporadicas,
                    'periodo_dias': config.periodo_dias_esporadicas,
                    'umbral': config.umbral_fallas_esporadicas,
                    'reglamento': 'Res. 009 Art. 22',
                },
            ))
        # ── R3: Fallas acumuladas → SEGUIMIENTO ──
        elif acumuladas >= config.umbral_fallas_acumuladas:
            reglas.append((
                'asistencia', 'amarilla',
                'Seguimiento académico por inasistencia',
                f'{aprendiz.nombre}: tienes {acumuladas} fallas no justificadas acumuladas. '
                'Conversa con tu instructor para acordar un plan de apoyo.',
                {'fallas_acumuladas': acumuladas, 'motivo': 'seguimiento',
                 'reglamento': 'Res. 009 Art. 28'},
            ))
        # ── R5: % asistencia < crítico → COMITÉ (Art. 22 — inasistencia >= 25%) ──
        if pct_asistencia < config.porcentaje_minimo_asistencia:
            reglas.append((
                'comite_desercion', 'roja',
                f'Asistencia crítica: {pct_asistencia}% — por debajo del mínimo reglamentario',
                f'{aprendiz.nombre}: tu asistencia es del {pct_asistencia}%. '
                'La Resolución 009 establece que la inasistencia igual o superior al 25% '
                'del total de horas programadas es causal de comité de evaluación.',
                {
                    'motivo': 'porcentaje_asistencia',
                    'pct_asistencia': pct_asistencia,
                    'umbral': config.porcentaje_minimo_asistencia,
                    'reglamento': 'Res. 009 Art. 22',
                },
            ))

        # ── R4/R6: Tareas incumplidas → plan de mejoramiento / comité ──
        if len(incumplidas) >= config.umbral_tareas_incumplidas:
            reglas.append((
                'academica', 'roja',
                'Incumplimiento académico requiere plan de mejoramiento',
                f'{aprendiz.nombre}: hay {len(incumplidas)} actividades vencidas, tardías '
                'o rechazadas. El instructor debe crear un plan de mejoramiento '
                'conforme a la Resolución 009 Art. 28.',
                {
                    'tareas_incumplidas': len(incumplidas),
                    'tareas': [t.id for t in incumplidas],
                    'requiere_plan': True,
                    'reglamento': 'Res. 009 Art. 28',
                },
            ))

        tipos_activos = set()
        for tipo, nivel, titulo, mensaje, detalle in reglas:
            tipos_activos.add(tipo)
            _crear_alerta(ficha, aprendiz, tipo, nivel, titulo, mensaje, detalle, ahora,
                          contexto=contexto)

        activas = [a for a in contexto.alertas_de(aprendiz.id) if a.estado == 'activa']
        for alerta in activas:
            if alerta.tipo in ('asistencia', 'academica', 'comite_desercion') and alerta.tipo not in tipos_activos:
                alerta.estado = 'resuelta'
                alerta.fecha_resuelta = ahora
        resultados.extend(reglas)

    db.session.commit()
    from app.services.cronograma import actualizar_alertas_cronograma
    actualizar_alertas_cronograma(ficha_id, ahora=ahora)
    auto_escalar_casos_pendientes(ficha_id, ahora, contexto=contexto)
    return resultados


# ── Auto-escalación ──────────────────────────


def auto_escalar_casos_pendientes(ficha_id, ahora=None, contexto=None):
    ahora = ahora or datetime.utcnow()
    config = obtener_config_comite(ficha_id)
    ficha = db.session.get(Ficha, ficha_id)
    # joinedload del aprendiz: el mensaje de escalamiento usa su nombre y sin
    # esto cada alerta escalada dispara un SELECT adicional.
    alertas = Alerta.query.options(joinedload(Alerta.aprendiz)).filter_by(
        ficha_id=ficha_id, estado='activa'
    ).filter(
        Alerta.aprendiz_id.isnot(None)
    ).all()
    escaladas = 0
    for alerta in alertas:
        dias = (ahora - alerta.fecha_generada).days
        if dias >= config.auto_escalar_dias:
            alerta.estado = 'escalada_comite'
            alerta.fecha_escalada = ahora
            alerta.auto_escalada = True
            if ficha:
                _notificar_instructores(
                    ficha,
                    f'El caso de {alerta.aprendiz.nombre_completo} fue escalado automáticamente a comité: {alerta.titulo}.',
                    'escalamiento',
                    f'escalamiento:{alerta.id}',
                    f'/instructor/fichas/{ficha.id}/casos-seguimiento',
                    contexto=contexto,
                )
            escaladas += 1
    if escaladas:
        db.session.commit()


# ── Evaluación automática programada ─────────


def ejecutar_revision_automatica():
    ahora = datetime.utcnow()
    hoy = ahora.date()
    fichas = Ficha.query.filter(
        (Ficha.fecha_fin >= hoy) | (Ficha.fecha_fin.is_(None))
    ).all()
    evaluadas = 0
    for ficha in fichas:
        try:
            actualizar_alertas_ficha(ficha.id, ahora)
            evaluadas += 1
        except Exception as error:
            current_app.logger.error('Error auto-evaluando ficha %s: %s', ficha.id, error)
    return evaluadas


# ── Plan de mejoramiento (Art. 28 Res. 009) ──


def crear_plan_mejoramiento(aprendiz_id, ficha_id, instructor_id, actividades,
                            fecha_limite=None, alerta_id=None):
    plan = PlanMejoramiento(
        aprendiz_id=aprendiz_id,
        ficha_id=ficha_id,
        alerta_id=alerta_id,
        actividades=actividades,
        fecha_limite=fecha_limite,
        creado_por=instructor_id,
    )
    db.session.add(plan)
    db.session.flush()
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    ficha = db.session.get(Ficha, ficha_id)
    if aprendiz and ficha:
        mensaje = f'Se creó un plan de mejoramiento para {aprendiz.nombre_completo}. Revisa las actividades acordadas en el panel.'
        _notificar_instructores(
            ficha, mensaje, 'alerta',
            f'plan-creado:{plan.id}',
            f'/instructor/fichas/{ficha.id}/casos-seguimiento',
        )
        registrar_notificacion(
            'aprendiz', aprendiz_id,
            f'Tu instructor creó un plan de mejoramiento para ti. Revisa las actividades y fechas acordadas.',
            'alerta', f'plan-creado:{plan.id}', ficha_id,
            f'/aprendiz/{ficha.id}/panel?documento={aprendiz.documento}',
        )
    db.session.commit()
    return plan


def cumplir_plan_mejoramiento(plan_id):
    plan = db.session.get(PlanMejoramiento, plan_id)
    if not plan or plan.estado != 'pendiente':
        return None
    plan.estado = 'cumplido'
    plan.fecha_cumplimiento = datetime.utcnow()
    db.session.commit()
    return plan


def vencer_planes_pendientes(ahora=None):
    ahora = ahora or datetime.utcnow()
    vencidos = PlanMejoramiento.query.filter(
        PlanMejoramiento.estado == 'pendiente',
        PlanMejoramiento.fecha_limite.isnot(None),
        PlanMejoramiento.fecha_limite < ahora,
    ).all()
    for plan in vencidos:
        plan.estado = 'vencido'
    if vencidos:
        db.session.commit()
    return len(vencidos)


# ── Recordatorios ────────────────────────────


def crear_recordatorios_aprendiz(ficha_id, aprendiz_id, ahora=None):
    ahora = ahora or datetime.utcnow()
    aprendiz = db.session.get(Aprendiz, aprendiz_id)
    if not aprendiz or aprendiz.ficha_id != ficha_id:
        return
    config = obtener_config_comite(ficha_id)
    tareas = Tarea.query.filter_by(ficha_id=ficha_id).all()
    # Las entregas del aprendiz se traen de una vez: una consulta por tarea
    # multiplicaba el costo del panel, que el grupo entero abre a la vez.
    entregas_aprendiz = {}
    for entrega in (
        Entrega.query
        .join(Tarea, Entrega.tarea_id == Tarea.id)
        .filter(Tarea.ficha_id == ficha_id, Entrega.aprendiz_id == aprendiz_id)
        .order_by(Entrega.fecha_entrega.desc(), Entrega.id.desc())
        .all()
    ):
        entregas_aprendiz.setdefault(entrega.tarea_id, entrega)

    for tarea in tareas:
        if not tarea.fecha_limite:
            continue
        entrega = entregas_aprendiz.get(tarea.id)
        if entrega and entrega.entregada_a_tiempo:
            continue
        horas = (tarea.fecha_limite - ahora).total_seconds() / 3600
        ventana = '24h' if 0 <= horas <= 24 else '48h' if 24 < horas <= 48 else None
        if not ventana:
            continue
        registrar_notificacion(
            'aprendiz', aprendiz_id,
            f'Recuerda tu evidencia "{tarea.titulo}": vence el '
            f'{tarea.fecha_limite.strftime("%d/%m/%Y %H:%M")}.',
            'tarea', f'tarea:{tarea.id}:{ventana}', ficha_id,
            f'/aprendiz/{ficha_id}/panel?documento={aprendiz.documento}',
        )

    ultimo = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        RegistroAsistencia.aprendiz_id == aprendiz_id,
        RegistroAsistencia.estado == 'FALTA',
    ).order_by(SesionAsistencia.fecha.desc()).first()
    if ultimo:
        registrar_notificacion(
            'aprendiz', aprendiz_id,
            'Si tu inasistencia tiene una excusa médica, laboral excepcional o citación oficial, '
            f'preséntala a tu instructor dentro de los {config.dias_plazo_justificacion} días sugeridos '
            'para que pueda revisarla.',
            'justificacion', f'justificacion:{ultimo.id}', ficha_id,
            f'/aprendiz/{ficha_id}/panel?documento={aprendiz.documento}',
        )
    db.session.commit()


def notificar_calificacion(entrega, ficha_id):
    if not entrega or not entrega.aprendiz:
        return
    registrar_notificacion(
        'aprendiz', entrega.aprendiz_id,
        'Tu instructor publicó una calificación o retroalimentación. Si no estás de acuerdo, '
        'puedes solicitar revisión dentro de los dos días hábiles siguientes a la publicación.',
        'calificacion', f'calificacion:{entrega.id}:{entrega.revisada_en}', ficha_id,
        f'/aprendiz/{ficha_id}/panel?documento={entrega.aprendiz.documento}',
    )
    db.session.commit()


def asegurar_resumen_semanal(ficha, ahora=None):
    ahora = ahora or datetime.utcnow()
    semana = ahora.isocalendar()
    clave = f'resumen:{semana.year}-{semana.week}'
    if all(Notificacion.query.filter_by(
        destinatario_tipo='instructor', destinatario_id=instructor_id, clave=clave
    ).first() for instructor_id in _instructores_ficha(ficha)):
        return
    activas = Alerta.query.filter_by(ficha_id=ficha.id, estado='activa').all()
    rojas = sum(1 for alerta in activas if alerta.nivel == 'roja')
    amarillas = sum(1 for alerta in activas if alerta.nivel == 'amarilla')
    proximas = sum(
        1 for tarea in Tarea.query.filter_by(ficha_id=ficha.id).all()
        if tarea.fecha_limite and ahora <= tarea.fecha_limite <= ahora + timedelta(days=7)
    )
    _notificar_instructores(
        ficha,
        f'Resumen semanal: {rojas} caso(s) en nivel rojo, {amarillas} en amarillo y '
        f'{proximas} tarea(s) próximas a vencer. Revisa los casos antes de tomar decisiones.',
        'resumen_semanal', clave,
        f'/instructor/fichas/{ficha.id}/casos-seguimiento',
    )
    db.session.commit()


# ── Consultas ────────────────────────────────


def obtener_casos(ficha_id):
    # joinedload del aprendiz: la vista lee alertas[0].aprendiz de cada caso.
    alertas = Alerta.query.options(joinedload(Alerta.aprendiz)).filter(
        Alerta.ficha_id == ficha_id,
        Alerta.aprendiz_id.isnot(None),
        Alerta.estado.in_(['activa', 'escalada_comite']),
    ).order_by(Alerta.nivel.desc(), Alerta.fecha_generada.asc()).all()
    agrupados = defaultdict(list)
    for alerta in alertas:
        agrupados[alerta.aprendiz_id].append(alerta)
    nivel_prioridad = {'roja': 0, 'amarilla': 1, 'verde': 2}
    return sorted(
        agrupados.values(),
        key=lambda lista: (
            min(nivel_prioridad.get(a.nivel, 9) for a in lista),
            0 if any(a.estado == 'activa' for a in lista) else 1,
            lista[0].fecha_generada,
        ),
    )


def obtener_indicadores_caso(aprendiz_id, ficha_id, ahora=None, contexto=None):
    """Return decision-ready indicators for one learner's follow-up case.

    ``contexto`` permite reutilizar el indice de la ficha cuando la vista de
    casos recorre a varios aprendices seguidos.
    """
    ahora = ahora or datetime.utcnow()
    ctx = _contexto(ficha_id, contexto, ahora)
    registros = ctx.registros(aprendiz_id)
    tareas_incumplidas = _incumplimientos_academicos(aprendiz_id, ficha_id, ahora, ctx)
    return {
        'asistencia': _porcentaje_asistencia(aprendiz_id, ficha_id, ctx),
        'sesiones': ctx.total_sesiones,
        'faltas': sum(estado == 'FALTA' for _fecha, estado in registros),
        'justificadas': sum(
            estado in ('FALTA_JUSTIFICADA', 'EXCUSA_MEDICA')
            for _fecha, estado in registros
        ),
        'consecutivas': _consecutivas_injustificadas(aprendiz_id, ficha_id, ctx),
        'tareas_incumplidas': len(tareas_incumplidas),
    }


def obtener_lineas_tiempo(ficha_id, aprendiz_ids):
    """Linea de tiempo de varios aprendices con dos consultas para toda la ficha.

    La vista de casos la pedia aprendiz por aprendiz, dos consultas cada uno.
    """
    ids = list(aprendiz_ids)
    if not ids:
        return {}
    eventos = defaultdict(list)
    registros = (
        RegistroAsistencia.query
        .options(joinedload(RegistroAsistencia.sesion))
        .join(SesionAsistencia)
        .filter(
            SesionAsistencia.ficha_id == ficha_id,
            RegistroAsistencia.aprendiz_id.in_(ids),
        )
        .all()
    )
    for registro in registros:
        eventos[registro.aprendiz_id].append({
            'fecha': registro.sesion.fecha,
            'tipo': 'asistencia',
            'titulo': 'Asistencia',
            'detalle': registro.estado.replace('_', ' ').capitalize(),
            'nota': registro.nota,
            'soporte_url': registro.soporte_url,
        })
    entregas = (
        Entrega.query
        .options(joinedload(Entrega.tarea))
        .join(Tarea)
        .filter(
            Tarea.ficha_id == ficha_id,
            Entrega.aprendiz_id.in_(ids),
        )
        .all()
    )
    for entrega in entregas:
        eventos[entrega.aprendiz_id].append({
            'fecha': (entrega.fecha_entrega or datetime.utcnow()).date(),
            'tipo': 'academica',
            'titulo': entrega.tarea.titulo,
            'detalle': 'Entrega ' + (entrega.estado_revision or 'pendiente'),
            'nota': entrega.feedback,
        })
    return {
        aprendiz_id: sorted(lista, key=lambda evento: evento['fecha'], reverse=True)
        for aprendiz_id, lista in eventos.items()
    }


def obtener_linea_tiempo(aprendiz_id, ficha_id):
    eventos = []
    # joinedload de sesion y tarea: la linea de tiempo lee la fecha de cada
    # sesion y el titulo de cada tarea, un SELECT por evento sin esto.
    registros = (
        RegistroAsistencia.query
        .options(joinedload(RegistroAsistencia.sesion))
        .join(SesionAsistencia)
        .filter(
            SesionAsistencia.ficha_id == ficha_id,
            RegistroAsistencia.aprendiz_id == aprendiz_id,
        )
        .all()
    )
    for registro in registros:
        eventos.append({
            'fecha': registro.sesion.fecha,
            'tipo': 'asistencia',
            'titulo': 'Asistencia',
            'detalle': registro.estado.replace('_', ' ').capitalize(),
            'nota': registro.nota,
            'soporte_url': registro.soporte_url,
        })
    entregas = (
        Entrega.query
        .options(joinedload(Entrega.tarea))
        .join(Tarea)
        .filter(
            Tarea.ficha_id == ficha_id,
            Entrega.aprendiz_id == aprendiz_id,
        )
        .all()
    )
    for entrega in entregas:
        eventos.append({
            'fecha': (entrega.fecha_entrega or datetime.utcnow()).date(),
            'tipo': 'academica',
            'titulo': entrega.tarea.titulo,
            'detalle': 'Entrega ' + (entrega.estado_revision or 'pendiente'),
            'nota': entrega.feedback,
        })
    return sorted(eventos, key=lambda evento: evento['fecha'], reverse=True)
