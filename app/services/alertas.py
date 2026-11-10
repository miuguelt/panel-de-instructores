from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
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
from app.models.observador import TIPO_NEGATIVA, NotaObservador
from app.models.tarea import Entrega, ProrrogaTarea, Tarea
from app.services.asistencia import contar_sesiones_registradas
from app.services.trabajos_grupales import obtener_destinatarios_y_entregas_grupales


# ─────────────────────────────────────────────
# REGLAMENTO DEL APRENDIZ SENA — Acuerdo 009 de 2024 (Consejo Directivo Nacional)
# Fuente única de artículos y páginas: app/services/normativa_sena.py
# ─────────────────────────────────────────────
# Art. 30 num. 1 lit. a (pág. 30): 3 días continuos o 5 no continuos de
#   inasistencia injustificada durante el proceso → deserción → comité (Art. 31).
# Art. 30 num. 2 (pág. 31): etapa productiva no culminada al cierre por fecha
#   del grupo → deserción → comité (ver comite_productiva.py).
# Art. 46 (págs. 37-38): llamados de atención → plan de mejoramiento → comité.
# El porcentaje mínimo de asistencia es un umbral preventivo del panel: el
# reglamento no lo fija para la formación titulada.
# ─────────────────────────────────────────────


_SIN_CARGAR = object()

VENTANA_REVISION_FICHAS_TERMINADAS = 400


def _con_fundamento(detalle, clave_principal, *claves_adicionales):
    """Agrega al detalle de la alerta la norma, artículo y página que la sustentan."""
    from app.services.normativa_sena import fundamentos_de
    fundamentos = fundamentos_de(clave_principal, *claves_adicionales)
    detalle = dict(detalle)
    detalle['fundamento'] = fundamentos[0]
    detalle['fundamentos'] = fundamentos
    detalle['reglamento'] = fundamentos[0]['referencia']
    return detalle


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

        self.destinatarios_grupales, entregas_grupales = (
            obtener_destinatarios_y_entregas_grupales(
                ficha_id, [tarea.id for tarea in self.tareas]
            )
        )
        for tarea in self.tareas:
            if tarea.es_grupal:
                for entregas_aprendiz in self.entregas.values():
                    entregas_aprendiz.pop(tarea.id, None)
        for (tarea_id, aprendiz_id), entrega in entregas_grupales.items():
            self.entregas[aprendiz_id][tarea_id] = entrega

        self.prorrogas = defaultdict(dict)
        prorrogas = (
            ProrrogaTarea.query
            .join(Tarea, ProrrogaTarea.tarea_id == Tarea.id)
            .filter(Tarea.ficha_id == ficha_id)
            .all()
        )
        for p in prorrogas:
            self.prorrogas[p.aprendiz_id][p.tarea_id] = p

        # Se llenan bajo demanda: solo actualizar_alertas_ficha los necesita.
        self._alertas = None
        self._notas_negativas = None
        self._claves_notificacion = None
        self._instructores = None
        self._config_correo = _SIN_CARGAR

    def registros(self, aprendiz_id):
        return self.asistencia.get(aprendiz_id, [])

    def entregas_de(self, aprendiz_id):
        return self.entregas.get(aprendiz_id, {})

    def prorroga(self, aprendiz_id, tarea_id):
        return self.prorrogas.get(aprendiz_id, {}).get(tarea_id)

    def alertas_de(self, aprendiz_id):
        if self._alertas is None:
            self._alertas = defaultdict(list)
            for alerta in Alerta.query.filter(
                Alerta.ficha_id == self.ficha_id,
                Alerta.aprendiz_id.isnot(None),
            ).order_by(Alerta.fecha_generada.desc()).all():
                self._alertas[alerta.aprendiz_id].append(alerta)
        return self._alertas[aprendiz_id]

    def notas_negativas_de(self, aprendiz_id):
        """Fechas de los llamados de atencion del observador de un aprendiz.

        Solo se necesitan las fechas para contar los de la ventana vigente; una
        consulta por ficha evita un SELECT por aprendiz durante la evaluacion.
        """
        if self._notas_negativas is None:
            self._notas_negativas = defaultdict(list)
            filas = (
                db.session.query(NotaObservador.aprendiz_id, NotaObservador.fecha)
                .filter(
                    NotaObservador.ficha_id == self.ficha_id,
                    NotaObservador.tipo == TIPO_NEGATIVA,
                )
                .all()
            )
            for nota_aprendiz_id, fecha in filas:
                self._notas_negativas[nota_aprendiz_id].append(fecha)
        return self._notas_negativas[aprendiz_id]

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
    if destinatario_tipo == 'aprendiz' and ficha_id and tipo in ('calificacion', 'juicio_evaluativo'):
        try:
            db.session.flush()
            with db.session.begin_nested():
                from app.services.notificaciones_push import encolar_push

                encolar_push(notificacion)
        except Exception:
            # El envío remoto se procesa después del commit. Si el buzón no
            # puede programarse, la calificación y su aviso en el panel siguen.
            current_app.logger.exception(
                'No se pudo programar Web Push para la notificación %s.',
                notificacion.id,
            )
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
                _url_panel_aprendiz(ficha.id),
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
        _url_panel_aprendiz(ficha.id),
        contexto=contexto,
    )
    return alerta, True


def fecha_colombia(ahora):
    """Fecha civil en Colombia (UTC-5, sin horario de verano) de un instante UTC.

    Las reglas cuentan días de formación: con la fecha UTC, desde las 7 p. m.
    el sistema ya creía estar en el día siguiente.
    """
    if isinstance(ahora, datetime):
        if ahora.tzinfo is not None:
            ahora = ahora.astimezone(timezone.utc).replace(tzinfo=None)
        return (ahora - timedelta(hours=5)).date()
    return ahora


def _contexto(ficha_id, contexto=None, ahora=None):
    """Devuelve el contexto recibido o construye uno para un uso aislado."""
    return contexto if contexto is not None else ContextoFicha(ficha_id, ahora)


def plazo_justificacion_efectivo(config):
    """Días hábiles para justificar: nunca menos de los 5 del Art. 28, par. 3."""
    from app.services.debido_proceso import DIAS_HABILES_JUSTIFICACION
    return max(DIAS_HABILES_JUSTIFICACION, int(config.dias_plazo_justificacion or 0))


def _registros_consolidados(registros, hoy, dias_plazo):
    """Registros cuyo plazo para justificar ya venció.

    Una falta solo cuenta como injustificada cuando el aprendiz ya no puede
    excusarla (Art. 28, par. 3, y Art. 29). Como el plazo crece con la fecha,
    los registros consolidados son siempre un prefijo cronológico.
    """
    from app.services.debido_proceso import fecha_limite_justificacion
    return [
        (fecha, estado) for fecha, estado in registros
        if fecha_limite_justificacion(fecha, dias_plazo) < hoy
    ]


def _consecutivas_injustificadas(aprendiz_id, ficha_id, contexto=None, registros=None):
    """Máximo de faltas seguidas, contadas en sesiones de formación programadas.

    «Días continuos» (Art. 30, num. 1, lit. a) se interpreta como sesiones
    programadas seguidas: un día sin sesión no interrumpe ni suma la racha.
    """
    ctx = _contexto(ficha_id, contexto)
    maximo = actual = 0
    for _fecha, estado in (registros if registros is not None else ctx.registros(aprendiz_id)):
        if estado == 'FALTA':
            actual += 1
            maximo = max(maximo, actual)
        else:
            actual = 0
    return maximo


def _incumplimientos_academicos(aprendiz_id, ficha_id, ahora, contexto=None):
    ctx = _contexto(ficha_id, contexto, ahora)
    tareas = ctx.tareas
    por_tarea = ctx.entregas_de(aprendiz_id)

    incumplidas = []
    for tarea in tareas:
        if (
            tarea.es_grupal
            and aprendiz_id not in ctx.destinatarios_grupales.get(tarea.id, set())
        ):
            continue
        entrega = por_tarea.get(tarea.id)
        prorroga = ctx.prorroga(aprendiz_id, tarea.id)
        limite_efectivo = prorroga.nueva_fecha_limite if prorroga and prorroga.nueva_fecha_limite else tarea.fecha_limite
        vencida = limite_efectivo and limite_efectivo < ahora
        rechazada = entrega and entrega.estado_revision == 'rechazada'
        tarde = entrega and entrega.fecha_entrega and limite_efectivo and entrega.fecha_entrega > limite_efectivo
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
    hoy = fecha_colombia(ahora)
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

    dias_plazo = plazo_justificacion_efectivo(config)

    for aprendiz in Aprendiz.query_en_formacion(ficha_id).all():
        consolidados = _registros_consolidados(contexto.registros(aprendiz.id), hoy, dias_plazo)
        consecutivas = _consecutivas_injustificadas(
            aprendiz.id, ficha_id, contexto, registros=consolidados
        )
        acumuladas = sum(1 for _fecha, estado in consolidados if estado == 'FALTA')
        incumplidas = _incumplimientos_academicos(aprendiz.id, ficha_id, ahora, contexto)
        pct_asistencia = _porcentaje_asistencia(aprendiz.id, ficha_id, contexto)
        reglas = []

        # ── R1: 3 sesiones consecutivas injustificadas → COMITÉ (Acuerdo 009, Art. 30 num. 1 lit. a) ──
        umbral_consec = config.umbral_fallas_consecutivas
        if consecutivas >= umbral_consec:
            reglas.append((
                'comite_desercion', 'roja',
                f'Riesgo de deserción: {consecutivas} sesiones seguidas sin justificar',
                f'{aprendiz.nombre}: registra {consecutivas} inasistencias consecutivas sin '
                'justificación. El Acuerdo 009 de 2024, Art. 30, num. 1, lit. a (pág. 30), '
                'lo define como deserción y el Art. 31 ordena reportarlo al comité.',
                _con_fundamento({
                    'motivo': 'consecutivas_injustificadas',
                    'fallas_consecutivas': consecutivas,
                    'umbral': umbral_consec,
                }, 'consecutivas_injustificadas', 'inasistencia_injustificada',
                    'procedimiento_desercion_inasistencia'),
            ))
        # ── R3: 5 fallas no continuas en todo el proceso → COMITÉ (Art. 30) ──
        elif acumuladas >= config.umbral_fallas_acumuladas:
            reglas.append((
                'comite_desercion', 'roja',
                f'Riesgo de deserción: {acumuladas} faltas injustificadas en el proceso',
                f'{aprendiz.nombre}: registra {acumuladas} inasistencias injustificadas '
                'durante el proceso. El Acuerdo 009 de 2024, Art. 30, num. 1, lit. a '
                '(pág. 30), define como deserción acumular cinco días no continuos.',
                _con_fundamento(
                    {'fallas_acumuladas': acumuladas, 'motivo': 'acumuladas_proceso',
                     'umbral': config.umbral_fallas_acumuladas},
                    'acumuladas_proceso', 'inasistencia_injustificada',
                    'procedimiento_desercion_inasistencia',
                ),
            ))
        # ── R5: % asistencia < umbral preventivo del panel (sin respaldo normativo) ──
        # Es solo un aviso preventivo: el Acuerdo no fija un mínimo, así que no
        # es causal de comité ni comparte tipo con R1-R3.
        if pct_asistencia < config.porcentaje_minimo_asistencia:
            reglas.append((
                'asistencia', 'amarilla',
                f'Asistencia baja: {pct_asistencia}%',
                f'{aprendiz.nombre}: tu asistencia es del {pct_asistencia}%. '
                'Es un umbral preventivo configurado en el panel: el Acuerdo 009 de 2024 '
                'no fija un porcentaje mínimo. Para remitir a comité verifique las causales '
                'del Art. 30, num. 1, lit. a (pág. 30).',
                _con_fundamento({
                    'motivo': 'porcentaje_asistencia',
                    'pct_asistencia': pct_asistencia,
                    'umbral': config.porcentaje_minimo_asistencia,
                }, 'porcentaje_asistencia', 'consecutivas_injustificadas'),
            ))

        # ── R4/R6: Tareas incumplidas → plan de mejoramiento / comité ──
        if len(incumplidas) >= config.umbral_tareas_incumplidas:
            reglas.append((
                'academica', 'roja',
                'Incumplimiento académico requiere plan de mejoramiento',
                f'{aprendiz.nombre}: hay {len(incumplidas)} actividades vencidas, tardías '
                'o rechazadas. Según el Acuerdo 009 de 2024, Art. 46, num. 1 (págs. 37-38), '
                'proceden llamados de atención y plan de mejoramiento; si no se cumple, '
                'el caso va a comité (parágrafo 4).',
                _con_fundamento({
                    'tareas_incumplidas': len(incumplidas),
                    'tareas': [t.id for t in incumplidas],
                    'requiere_plan': True,
                }, 'tareas_incumplidas'),
            ))

        # ── R7: llamados de atención del observador → SEGUIMIENTO integral ──
        # La dimensión integral (puntualidad, convivencia, trabajo en equipo)
        # no tiene otro indicador medible: sin esta regla, tres llamados de
        # atención fechados no abren caso hasta que alguien los lee.
        if config.umbral_notas_negativas > 0:
            desde = hoy - timedelta(days=config.periodo_dias_notas)
            llamados = sum(
                1 for fecha in contexto.notas_negativas_de(aprendiz.id) if fecha >= desde
            )
            if llamados >= config.umbral_notas_negativas:
                reglas.append((
                    'observador', 'amarilla',
                    f'Formación integral: {llamados} llamados de atención en la bitácora',
                    f'{aprendiz.nombre}: el observador registra {llamados} llamados de '
                    f'atención en los últimos {config.periodo_dias_notas} días. '
                    'Revisa la bitácora y acuerda un plan de mejoramiento antes de que el '
                    'caso escale a comité.',
                    _con_fundamento({
                        'motivo': 'notas_observador',
                        'notas_negativas': llamados,
                        'umbral': config.umbral_notas_negativas,
                        'periodo_dias': config.periodo_dias_notas,
                        'requiere_plan': True,
                    }, 'notas_observador'),
                ))

        tipos_activos = set()
        for tipo, nivel, titulo, mensaje, detalle in reglas:
            tipos_activos.add(tipo)
            _crear_alerta(ficha, aprendiz, tipo, nivel, titulo, mensaje, detalle, ahora,
                          contexto=contexto)

        activas = [a for a in contexto.alertas_de(aprendiz.id) if a.estado == 'activa']
        for alerta in activas:
            if alerta.tipo in (
                'asistencia', 'academica', 'comite_desercion', 'observador'
            ) and alerta.tipo not in tipos_activos:
                alerta.estado = 'resuelta'
                alerta.fecha_resuelta = ahora
        resultados.extend(reglas)

    # Reglas que dependen de novedades y etapa productiva: se cargan una vez por ficha.
    from app.services.cierre_lectivo import actualizar_alertas_cierre
    from app.services.comite_productiva import actualizar_alertas_productiva
    from app.services.novedades import actualizar_alertas_reintegro, cargar_datos_ficha
    todos = Aprendiz.query.filter_by(ficha_id=ficha_id).all()
    etapas, novedades = cargar_datos_ficha(ficha_id)
    # Fichas terminadas por fecha: etapa productiva no culminada (Art. 30 num. 2).
    actualizar_alertas_productiva(ficha, ahora, contexto=contexto, aprendices=todos,
                                  etapas=etapas, novedades=novedades)
    # Aplazamientos sin reintegro gestionado (Art. 18 num. 3 y Art. 30 num. 3).
    actualizar_alertas_reintegro(ficha, ahora, todos, novedades, contexto=contexto)
    # Pendientes antes del cierre de la etapa lectiva (prevención del Art. 30 num. 2).
    actualizar_alertas_cierre(ficha, ahora, todos, etapas, contexto=contexto)

    db.session.commit()
    from app.services.cronograma import actualizar_alertas_cronograma
    actualizar_alertas_cronograma(ficha_id, ahora=ahora)
    auto_escalar_casos_pendientes(ficha_id, ahora, contexto=contexto)
    return resultados


# ── Auto-escalación ──────────────────────────


def auto_escalar_casos_pendientes(ficha_id, ahora=None, contexto=None):
    """Recuerda al instructor los casos abiertos hace mucho; nunca escala solo.

    Pasar un caso a comité exige el informe del instructor (Art. 51, num. 1):
    el sistema solo avisa, una vez por alerta, y la decisión queda en manos
    de una persona.
    """
    ahora = ahora or datetime.utcnow()
    config = obtener_config_comite(ficha_id)
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        return 0
    alertas = Alerta.query.options(joinedload(Alerta.aprendiz)).filter_by(
        ficha_id=ficha_id, estado='activa'
    ).filter(
        Alerta.aprendiz_id.isnot(None)
    ).all()
    recordadas = 0
    for alerta in alertas:
        dias = (ahora - alerta.fecha_generada).days
        if dias >= config.auto_escalar_dias:
            _notificar_instructores(
                ficha,
                f'El caso de {alerta.aprendiz.nombre_completo} lleva {dias} días abierto '
                f'({alerta.titulo}). Revise si corresponde remitirlo a comité con su informe.',
                'escalamiento',
                f'recordatorio-comite:{alerta.id}',
                f'/instructor/fichas/{ficha.id}/casos-seguimiento',
                contexto=contexto,
            )
            recordadas += 1
    if recordadas:
        db.session.commit()
    return recordadas


# ── Evaluación automática programada ─────────


def ejecutar_revision_automatica():
    ahora = datetime.utcnow()
    hoy = fecha_colombia(ahora)
    # Se incluyen fichas terminadas hasta poco más de un año atrás: en ese
    # intervalo corren la remisión por etapa productiva (Art. 30 num. 2) y la
    # cancelación administrativa (Art. 47 num. 2 par. 1).
    desde = hoy - timedelta(days=VENTANA_REVISION_FICHAS_TERMINADAS)
    fichas = Ficha.query.filter(
        (Ficha.fecha_fin >= desde) | (Ficha.fecha_fin.is_(None))
    ).all()
    evaluadas = 0
    for ficha in fichas:
        ficha_id = ficha.id
        try:
            actualizar_alertas_ficha(ficha_id, ahora)
            evaluadas += 1
        except Exception:
            db.session.rollback()
            current_app.logger.exception('No se pudieron revisar automáticamente las alertas de la ficha %s.', ficha_id)
    return evaluadas


# ── Plan de mejoramiento (Acuerdo 009 de 2024, Art. 46) ──


def crear_plan_mejoramiento(aprendiz_id, ficha_id, instructor_id, actividades,
                            fecha_limite=None, alerta_id=None, tarea_id=None, fase=None,
                            fecha_creacion=None):
    """Crea el plan solo si cumple el Art. 46 (máximo 20 días calendario).

    Lanza ``ValueError`` con los errores de ``validar_plan``; las advertencias
    se devuelven en ``plan.advertencias`` para que la ruta las muestre.
    """
    from app.services.debido_proceso import validar_plan
    ficha_plan = db.session.get(Ficha, ficha_id)
    creacion = fecha_creacion or datetime.utcnow()
    errores, advertencias = validar_plan(aprendiz_id, ficha_plan, creacion, fecha_limite, fase=fase)
    if errores:
        raise ValueError(' '.join(errores))
    plan = PlanMejoramiento(
        fase=fase,
        fecha_creacion=creacion,
        aprendiz_id=aprendiz_id,
        ficha_id=ficha_id,
        alerta_id=alerta_id,
        tarea_id=tarea_id,
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
            _url_panel_aprendiz(ficha.id),
        )
    db.session.commit()
    plan.advertencias = advertencias
    return plan


def cumplir_plan_mejoramiento(plan_id):
    plan = db.session.get(PlanMejoramiento, plan_id)
    if not plan or plan.estado != 'pendiente':
        return None
    plan.estado = 'cumplido'
    plan.fecha_cumplimiento = datetime.utcnow()
    db.session.commit()
    return plan


def vencer_planes_pendientes(ahora=None, ficha_id=None):
    """Marca vencidos los planes sin evidencia cuya fecha límite ya pasó.

    Un plan con evidencia enviada espera la revisión del instructor: el
    aprendiz cumplió a tiempo y no se le puede tratar como incumplido.
    """
    ahora = ahora or datetime.utcnow()
    consulta = PlanMejoramiento.query.filter(
        PlanMejoramiento.estado == 'pendiente',
        PlanMejoramiento.fecha_limite.isnot(None),
        PlanMejoramiento.fecha_limite < ahora,
        PlanMejoramiento.evidencia_enviada_en.is_(None),
    )
    if ficha_id is not None:
        consulta = consulta.filter(PlanMejoramiento.ficha_id == ficha_id)
    vencidos = consulta.all()
    for plan in vencidos:
        plan.estado = 'vencido'
    if vencidos:
        db.session.commit()
    return len(vencidos)


# ── Recordatorios ────────────────────────────


def _url_panel_aprendiz(ficha_id):
    """Enlace al panel del aprendiz; nunca lleva la cédula (la sesión identifica)."""
    return f'/aprendiz/{ficha_id}/panel'


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

    destinatarios_grupales, entregas_grupales = (
        obtener_destinatarios_y_entregas_grupales(
            ficha_id, [tarea.id for tarea in tareas]
        )
    )
    for tarea in tareas:
        if tarea.es_grupal:
            entregas_aprendiz.pop(tarea.id, None)
    entregas_aprendiz.update({
        tarea_id: entrega
        for (tarea_id, destino_id), entrega in entregas_grupales.items()
        if destino_id == aprendiz_id
    })

    for tarea in tareas:
        if (
            tarea.es_grupal
            and aprendiz_id not in destinatarios_grupales.get(tarea.id, set())
        ):
            continue
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
            _url_panel_aprendiz(ficha_id),
        )

    ultimo = RegistroAsistencia.query.join(SesionAsistencia).filter(
        SesionAsistencia.ficha_id == ficha_id,
        RegistroAsistencia.aprendiz_id == aprendiz_id,
        RegistroAsistencia.estado == 'FALTA',
    ).order_by(SesionAsistencia.fecha.desc()).first()
    if ultimo:
        from app.services.debido_proceso import fecha_limite_justificacion
        limite = fecha_limite_justificacion(ultimo.sesion.fecha, config.dias_plazo_justificacion)
        registrar_notificacion(
            'aprendiz', aprendiz_id,
            'Si tu inasistencia tiene una excusa médica, laboral excepcional o citación oficial, '
            f'preséntala a tu instructor a más tardar el {limite:%d/%m/%Y} '
            f'({config.dias_plazo_justificacion} días hábiles, Acuerdo 009 de 2024, Art. 28, '
            'parágrafo 3). Si no la justificas, cuenta como inasistencia injustificada.',
            'justificacion', f'justificacion:{ultimo.id}', ficha_id,
            _url_panel_aprendiz(ficha_id),
        )
    db.session.commit()


def notificar_calificacion(entrega, ficha_id, commit=True):
    """Notifica una calificación publicada.

    ``commit=False`` permite que las operaciones masivas agreguen todas las
    notificaciones a la misma transacción que las calificaciones.
    """
    if not entrega:
        return
    if entrega.grupo_id and entrega.tarea and entrega.tarea.es_grupal:
        _destinatarios, entregas_compartidas = obtener_destinatarios_y_entregas_grupales(
            ficha_id, [entrega.tarea_id]
        )
        ids_aprendices = {
            aprendiz_id
            for (tarea_id, aprendiz_id), entrega_grupal in entregas_compartidas.items()
            if tarea_id == entrega.tarea_id and entrega_grupal.id == entrega.id
        }
        aprendices = Aprendiz.query.filter(
            Aprendiz.id.in_(ids_aprendices)
        ).order_by(Aprendiz.id).all() if ids_aprendices else []
    else:
        aprendices = [entrega.aprendiz] if entrega.aprendiz else []

    for aprendiz in aprendices:
        registrar_notificacion(
            'aprendiz', aprendiz.id,
            'Tu instructor publicó una calificación o retroalimentación. Si no estás de acuerdo, '
            'puedes solicitar revisión dentro de los dos días hábiles siguientes a la publicación.',
            'calificacion', f'calificacion:{entrega.id}:{entrega.revisada_en}', ficha_id,
            f'/aprendiz/{ficha_id}/notificaciones',
        )
    if commit:
        db.session.commit()


def notificar_juicios_importados(resultado, commit=False):
    """Agrupa cambios evaluativos importados en un aviso por aprendiz y reporte."""
    if (not resultado or resultado.get('ficha_creada')
            or resultado.get('carga_inicial_juicios')):
        return 0
    ficha = resultado.get('ficha')
    importacion_id = resultado.get('importacion_id')
    if not ficha or not importacion_id:
        return 0
    ids_aprendices = sorted(set(resultado.get('aprendices_juicios_modificados') or ()))
    creadas = 0
    for aprendiz_id in ids_aprendices:
        aviso = registrar_notificacion(
            'aprendiz', aprendiz_id,
            'Tu reporte de resultados formativos fue actualizado. Entra al panel para consultar la información.',
            'juicio_evaluativo', f'juicio-importacion:{importacion_id}:{aprendiz_id}',
            ficha.id, f'/aprendiz/{ficha.id}/notificaciones',
        )
        creadas += aviso is not None
    if commit:
        db.session.commit()
    return creadas


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
    notas = (
        NotaObservador.query
        .options(joinedload(NotaObservador.autor))
        .filter(
            NotaObservador.ficha_id == ficha_id,
            NotaObservador.aprendiz_id.in_(ids),
        )
        .all()
    )
    for nota in notas:
        eventos[nota.aprendiz_id].append({
            'fecha': nota.fecha,
            'tipo': 'observador',
            'titulo': f'{nota.etiqueta_tipo}: {nota.etiqueta_categoria}',
            'detalle': nota.descripcion,
            'nota': f'Registró {nota.autor.nombre}' if nota.autor else None,
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
        detalle_entrega = 'Entrega ' + (entrega.estado_revision or 'pendiente')
        if getattr(entrega, 'justificacion_retraso', None):
            detalle_entrega += f' (Extemporánea: {entrega.justificacion_retraso})'
        eventos.append({
            'fecha': (entrega.fecha_entrega or datetime.utcnow()).date(),
            'tipo': 'academica',
            'titulo': entrega.tarea.titulo,
            'detalle': detalle_entrega,
            'nota': entrega.feedback,
        })

    prorrogas = (
        ProrrogaTarea.query
        .options(joinedload(ProrrogaTarea.tarea))
        .join(Tarea)
        .filter(
            Tarea.ficha_id == ficha_id,
            ProrrogaTarea.aprendiz_id == aprendiz_id,
        )
        .all()
    )
    for prorroga in prorrogas:
        fecha_pr = prorroga.nueva_fecha_limite.strftime('%d/%m/%Y %H:%M') if prorroga.nueva_fecha_limite else '—'
        det = f'Prórroga concedida hasta {fecha_pr}'
        if prorroga.motivo:
            det += f' · Motivo: {prorroga.motivo}'
        eventos.append({
            'fecha': (prorroga.creada_en or datetime.utcnow()).date(),
            'tipo': 'academica',
            'titulo': f'Prórroga: {prorroga.tarea.titulo}',
            'detalle': det,
            'nota': prorroga.motivo,
        })

    planes_ap = (
        PlanMejoramiento.query
        .options(joinedload(PlanMejoramiento.tarea))
        .filter(
            PlanMejoramiento.ficha_id == ficha_id,
            PlanMejoramiento.aprendiz_id == aprendiz_id,
        )
        .all()
    )
    for plan_item in planes_ap:
        tit = 'Plan de mejoramiento'
        if plan_item.tarea:
            tit += f': {plan_item.tarea.titulo}'
        det_plan = f'Estado: {plan_item.estado} · Actividades: {plan_item.actividades}'
        if plan_item.fecha_limite:
            det_plan += f' (Límite: {plan_item.fecha_limite.strftime("%d/%m/%Y")})'
        eventos.append({
            'fecha': (plan_item.fecha_creacion or datetime.utcnow()).date(),
            'tipo': 'academica',
            'titulo': tit,
            'detalle': det_plan,
            'nota': plan_item.observaciones_instructor,
        })
    # Las notas del observador son la única traza de la dimensión integral
    # (puntualidad, convivencia, trabajo en equipo). Sin ellas el borrador del
    # comité solo puede argumentar con asistencia y evidencias.
    notas = (
        NotaObservador.query
        .options(joinedload(NotaObservador.autor))
        .filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz_id)
        .all()
    )
    for nota in notas:
        eventos.append({
            'fecha': nota.fecha,
            'tipo': 'observador',
            'titulo': f'{nota.etiqueta_tipo}: {nota.etiqueta_categoria}',
            'detalle': nota.descripcion,
            'nota': f'Registró {nota.autor.nombre}' if nota.autor else None,
        })
    return sorted(eventos, key=lambda evento: evento['fecha'], reverse=True)
