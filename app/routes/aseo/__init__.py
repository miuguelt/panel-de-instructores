"""Turnos de aseo: calendario del instructor, gestión delegada y vista del aprendiz.

Este paquete define los dos blueprints y los pasos que comparten sus rutas
(autorización, cálculo de turnos, configuración, exclusiones y el contexto del
calendario). Las rutas viven en ``instructor``, ``delegado`` y ``aprendiz``.
"""

from datetime import date

from flask import Blueprint, flash, redirect, request, session, url_for

from app import db
from app.models.aprendiz import Aprendiz
from app.models.aseo import ContadorAseo, TurnoAseo
from app.models.ficha import Ficha
from app.services.aseo import (
    ESTADOS_ACTIVOS,
    asegurar_contadores,
    datos_transparencia,
    generar_turnos,
    obtener_configuracion,
    rebalancear_turnos_pendientes,
    resumen_equidad,
)
from app.services.aseo_calendario import DIAS_LABORALES, OPCIONES_DIAS_SEMANA
from app.services.aseo_vista import (
    casilla_marcada,
    fecha_formulario,
    mensaje_generacion,
    mes_consulta,
    mover_mes,
    nombre_mes,
    ordenar_equidad,
)
from app.services.permisos import (
    aprendiz_de_sesion,
    bloquear_escritura_aprendiz_inactivo,
    puede_administrar_ficha_como_aprendiz,
    puede_gestionar_ficha,
)

aseo_bp = Blueprint('aseo', __name__, template_folder='../../templates/instructor')
aseo_aprendiz_bp = Blueprint('aseo_aprendiz', __name__, template_folder='../../templates/aprendiz')
aseo_aprendiz_bp.before_request(bloquear_escritura_aprendiz_inactivo)


def _ficha_autorizada(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    return ficha if puede_gestionar_ficha(ficha) else None


def _aprendiz_admin_autorizado(ficha_id):
    """Devuelve el aprendiz de sesión solo si tiene la delegación vigente."""
    if not puede_administrar_ficha_como_aprendiz(ficha_id):
        return None
    return aprendiz_de_sesion(ficha_id)


def _aprendiz_autorizado(ficha_id):
    """Devuelve el aprendiz de sesión si pertenece y está activo en la ficha."""
    aprendiz = aprendiz_de_sesion(ficha_id)
    if not aprendiz or aprendiz.estado not in ESTADOS_ACTIVOS or not aprendiz.activo:
        return None
    return aprendiz


def _volver_al_panel_aprendiz(ficha_id):
    if session.get('aprendiz_ficha_id') == ficha_id:
        return redirect(url_for('aprendiz.panel', ficha_id=ficha_id))
    return redirect(url_for('aprendiz.vista_aprendiz', ficha_id=ficha_id))


def _turno_de_la_ficha(ficha_id, turno_id):
    turno = db.session.get(TurnoAseo, turno_id)
    return turno if turno and turno.ficha_id == ficha_id else None


def _aprendiz_de_la_ficha(ficha_id, campo):
    """Aprendiz elegido en el formulario, solo si pertenece a la ficha."""
    aprendiz_id = request.form.get(campo, type=int)
    return Aprendiz.query.filter_by(id=aprendiz_id, ficha_id=ficha_id).first() if aprendiz_id else None


def _generar_desde_formulario(ficha_id, generado_por):
    """Calcula y equilibra los turnos pedidos; devuelve (mes inicial, mensaje, categoría).

    Lanza ``ValueError`` si las fechas o el cálculo no son válidos. No confirma la sesión.
    """
    formulario = request.form
    inicio = fecha_formulario(formulario.get('fecha_inicio'), 'fecha inicial')
    fin = fecha_formulario(formulario.get('fecha_fin'), 'fecha final')
    respetar_manuales = casilla_marcada(formulario, 'respetar_manuales', 'on')
    resultado = generar_turnos(
        ficha_id,
        inicio,
        fin,
        generado_por=generado_por,
        recalcular_existentes=casilla_marcada(formulario, 'recalcular', 'on'),
        respetar_manuales=respetar_manuales,
        dias_semana=formulario.getlist('dias_semana') if 'dias_semana_present' in formulario else None,
    )
    # Equilibra también los turnos ya programados fuera del rango visible, para
    # que el reparto sea justo sobre el total de turnos y no solo sobre un mes.
    equilibrados = (
        rebalancear_turnos_pendientes(
            ficha_id, fecha_inicio=inicio, respetar_manuales=respetar_manuales, generado_por=generado_por
        )
        if casilla_marcada(formulario, 'equilibrar_calendario', 'on')
        else []
    )
    mensaje, categoria = mensaje_generacion(resultado, equilibrados, resumen_equidad(ficha_id))
    return inicio, mensaje, categoria


def _guardar_configuracion(ficha_id):
    """Guarda las horas de aviso y la exclusión de ausentes; ``ValueError`` si el número no es válido."""
    try:
        aviso_horas = max(0, min(720, int(request.form.get('aviso_horas', 24))))
    except (TypeError, ValueError):
        raise ValueError('Las horas de aviso deben ser un número entero.')
    config = obtener_configuracion(ficha_id)
    config.excluir_ausentes = casilla_marcada(request.form, 'excluir_ausentes')
    config.aviso_horas = aviso_horas
    db.session.commit()


def _actualizar_exclusion(ficha_id, aprendiz):
    """Excluye temporalmente al aprendiz o lo devuelve a la cola, sin tocar su contador.

    Devuelve False si no se pudo cargar el contador y lanza ``ValueError`` si la fecha no es válida.
    """
    contador = ContadorAseo.query.filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz.id).first()
    if not contador:
        asegurar_contadores(ficha_id)
        contador = ContadorAseo.query.filter_by(ficha_id=ficha_id, aprendiz_id=aprendiz.id).first()
    if not contador:
        return False

    hasta = request.form.get('excluido_hasta', '').strip()
    if hasta:
        contador.excluido_hasta = fecha_formulario(hasta, 'fecha de exclusión')
        contador.motivo_exclusion = request.form.get('motivo', '').strip() or None
        flash(f'{aprendiz.nombre_completo} quedó excluido temporalmente sin perder su contador.', 'success')
    else:
        contador.excluido_hasta = None
        contador.motivo_exclusion = None
        flash(f'{aprendiz.nombre_completo} volvió a la cola justa.', 'success')
    db.session.commit()
    return True


def _confirmar_sin_expirar():
    """Guarda los contadores recalculados sin expirar lo recién leído.

    Si la confirmación expirara los objetos, la plantilla volvería a consultar
    cada turno, contador y aprendiz uno por uno (N+1).
    """
    sesion = db.session()
    sesion.expire_on_commit = False
    try:
        sesion.commit()
    finally:
        sesion.expire_on_commit = True


def _contexto_calendario(ficha_id):
    """Variables del calendario del mes pedido y de la tabla de equidad en el orden pedido."""
    mes = mes_consulta(request.args.get('mes'))
    orden = request.args.get('orden', 'veces')
    datos = datos_transparencia(ficha_id, mes)
    _confirmar_sin_expirar()
    return {
        'aprendices': datos['aprendices'],
        'contadores': datos['contadores'],
        'equidad': ordenar_equidad(datos['equidad'], orden),
        'equidad_delta': datos['equidad_delta'],
        'equidad_minimo': datos['equidad_minimo'],
        'equidad_maximo': datos['equidad_maximo'],
        'equidad_promedio': datos['equidad_promedio'],
        'orden': orden,
        'mes': mes,
        'nombre_mes': nombre_mes(mes),
        'mes_anterior': mover_mes(mes, -1).strftime('%Y-%m'),
        'mes_siguiente': mover_mes(mes, 1).strftime('%Y-%m'),
        'semanas': datos['semanas'],
        'turnos': datos['turnos'],
        'turnos_por_fecha': datos['turnos_por_fecha'],
        'sesiones_mes': datos['sesiones_mes'],
        'festivos_mes': datos['festivos_mes'],
        'hoy': date.today(),
        'fecha_inicio_default': mes,
        'fecha_fin_default': datos['fin_mes'],
        'opciones_dias_semana': OPCIONES_DIAS_SEMANA,
        'dias_laborales': DIAS_LABORALES,
        'total_turnos': datos['total_turnos'],
        'total_cumplidos': datos['total_cumplidos'],
        'total_no_cumplidos': datos['total_no_cumplidos'],
        'total_programados': datos['total_programados'],
    }


from . import aprendiz, delegado, instructor  # noqa: E402,F401  (registran sus rutas)
