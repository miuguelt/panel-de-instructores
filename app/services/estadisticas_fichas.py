"""Agregados de «Mis fichas».

Cada indicador se resuelve con una consulta agrupada por ficha, para todas las
fichas del instructor a la vez: el panel no crece en consultas al sumar fichas
ni tareas. Las reglas son las mismas del resto de la app: un juicio cuenta como
aprobado solo con «APROBADO» explícito y la asistencia descuenta solo las
faltas sin justificar.
"""

from datetime import datetime

from sqlalchemy import func, or_

from app import db
from app.models.alertas import Alerta, PlanMejoramiento
from app.models.aprendiz import ESTADOS_EN_FORMACION, Aprendiz
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.models.juicio import JuicioEvaluativo
from app.models.observador import NotaObservador
from app.models.tarea import MODALIDAD_EVIDENCIA, Entrega, Tarea
from app.services.emparejamiento_juicios import condicion_aprobado_sql

NOTAS_VACIAS = {'positiva': 0, 'negativa': 0, 'neutra': 0}
TAREAS_VACIAS = {'total': 0, 'entregas': 0, 'pendientes': 0}


def _estados_aprendices(ids):
    estados = {}
    filas = (db.session.query(Aprendiz.ficha_id, Aprendiz.estado, func.count(Aprendiz.id))
             .filter(Aprendiz.ficha_id.in_(ids)).group_by(Aprendiz.ficha_id, Aprendiz.estado).all())
    for fid, estado, cantidad in filas:
        datos = estados.setdefault(fid, {'total': 0, 'activos': 0, 'estados': {}})
        datos['estados'][estado] = cantidad
        datos['total'] += cantidad
        if estado in ESTADOS_EN_FORMACION:
            datos['activos'] += cantidad
    return estados


def _asistencia(ids):
    """(sesiones con registros, faltas sin justificar de aprendices en formación) por ficha."""
    sesiones = dict(db.session.query(SesionAsistencia.ficha_id, func.count(func.distinct(SesionAsistencia.id)))
                    .join(RegistroAsistencia).filter(SesionAsistencia.ficha_id.in_(ids))
                    .group_by(SesionAsistencia.ficha_id).all())
    faltas = dict(db.session.query(SesionAsistencia.ficha_id, func.count(RegistroAsistencia.id))
                  .join(RegistroAsistencia).join(Aprendiz, RegistroAsistencia.aprendiz_id == Aprendiz.id)
                  .filter(SesionAsistencia.ficha_id.in_(ids), RegistroAsistencia.estado == 'FALTA',
                          Aprendiz.estado.in_(ESTADOS_EN_FORMACION))
                  .group_by(SesionAsistencia.ficha_id).all())
    return sesiones, faltas


def _tareas(ids, estados, instructor_id, ahora):
    """Tareas, entregas y pendientes (rechazadas + aprendices sin entrega en tareas vencidas)."""
    consulta = (db.session.query(Tarea.ficha_id, Tarea.fecha_limite, func.count(Entrega.id),
                                 func.sum(db.case((Entrega.estado_revision == 'rechazada', 1), else_=0)))
                .outerjoin(Entrega).filter(Tarea.ficha_id.in_(ids)))
    if instructor_id is not None:
        consulta = consulta.filter(Tarea.instructor_id == instructor_id)
    tareas = {fid: dict(TAREAS_VACIAS) for fid in ids}
    for fid, limite, entregas, rechazadas in consulta.group_by(Tarea.ficha_id, Tarea.id, Tarea.fecha_limite).all():
        datos = tareas[fid]
        datos['total'] += 1
        datos['entregas'] += entregas or 0
        datos['pendientes'] += rechazadas or 0
        if limite and limite < ahora:
            datos['pendientes'] += max(estados.get(fid, {}).get('activos', 0) - (entregas or 0), 0)
    return tareas


def _por_calificar(ids):
    return dict(db.session.query(Tarea.ficha_id, func.count(Entrega.id))
                .join(Entrega, Entrega.tarea_id == Tarea.id).join(Aprendiz, Entrega.aprendiz_id == Aprendiz.id)
                .filter(Tarea.ficha_id.in_(ids), Tarea.modalidad == MODALIDAD_EVIDENCIA,
                        or_(Entrega.calificada.is_(False), Entrega.estado_revision == 'pendiente'),
                        Aprendiz.estado.in_(ESTADOS_EN_FORMACION))
                .group_by(Tarea.ficha_id).all())


def _conteo(modelo, ids, *condiciones):
    return dict(db.session.query(modelo.ficha_id, func.count(modelo.id))
                .filter(modelo.ficha_id.in_(ids), *condiciones).group_by(modelo.ficha_id).all())


def _juicios(ids):
    """Totales por ficha y aprendices con todos sus juicios aprobados."""
    aprobado = func.sum(db.case((condicion_aprobado_sql(JuicioEvaluativo.juicio), 1), else_=0))
    filas = (db.session.query(JuicioEvaluativo.ficha_id, JuicioEvaluativo.aprendiz_id, func.count(JuicioEvaluativo.id), aprobado)
             .join(Aprendiz).filter(JuicioEvaluativo.ficha_id.in_(ids), Aprendiz.estado.in_(ESTADOS_EN_FORMACION))
             .group_by(JuicioEvaluativo.ficha_id, JuicioEvaluativo.aprendiz_id).all())
    juicios, certificados = {}, {fid: 0 for fid in ids}
    for fid, _aprendiz, total, aprobados in filas:
        total, aprobados = total or 0, aprobados or 0
        datos = juicios.setdefault(fid, {'total': 0, 'aprobados': 0})
        datos['total'] += total
        datos['aprobados'] += aprobados
        if total and total == aprobados:
            certificados[fid] += 1
    return juicios, certificados


def competencias_mas_debiles(competencias, limite=2):
    """Competencias con menor aprobación; a igual porcentaje, la de más juicios primero."""
    return sorted(competencias.items(),
                  key=lambda item: (item[1]['aprobados'] / item[1]['total'] if item[1]['total'] else 0,
                                    -item[1]['total']))[:limite]


def _competencias(ids):
    aprobado = func.sum(db.case((condicion_aprobado_sql(JuicioEvaluativo.juicio), 1), else_=0))
    filas = (db.session.query(JuicioEvaluativo.ficha_id, JuicioEvaluativo.competencia, func.count(JuicioEvaluativo.id), aprobado)
             .join(Aprendiz).filter(JuicioEvaluativo.ficha_id.in_(ids), Aprendiz.estado.in_(ESTADOS_EN_FORMACION))
             .group_by(JuicioEvaluativo.ficha_id, JuicioEvaluativo.competencia).all())
    por_ficha = {}
    for fid, competencia, total, aprobados in filas:
        if competencia and competencia.strip():
            por_ficha.setdefault(fid, {})[competencia] = {'total': total or 0, 'aprobados': aprobados or 0}
    return {fid: competencias_mas_debiles(comps) for fid, comps in por_ficha.items()}


def _notas(ids):
    notas = {}
    filas = (db.session.query(NotaObservador.ficha_id, NotaObservador.tipo, func.count(NotaObservador.id))
             .filter(NotaObservador.ficha_id.in_(ids)).group_by(NotaObservador.ficha_id, NotaObservador.tipo).all())
    for fid, tipo, cantidad in filas:
        notas.setdefault(fid, dict(NOTAS_VACIAS))[tipo] = cantidad
    return notas


def consolidar_ficha(activos, total, sesiones, faltas, tareas, juicios, pct_tiempo):
    """Porcentajes de una ficha; sin sesiones o sin tareas el porcentaje queda en None («Sin datos»)."""
    posibles = sesiones * activos
    esperadas = tareas['total'] * activos
    return {
        'total_aprendices': activos,
        'total_aprendices_incl_inactivos': total,
        'sesiones': sesiones,
        'pct_asistencia': round((posibles - faltas) / posibles * 100, 1) if posibles else None,
        'tareas_totales': tareas['total'],
        'entregas_totales': tareas['entregas'],
        'pendientes': tareas['pendientes'],
        'pct_entregas': round(tareas['entregas'] / esperadas * 100) if esperadas else None,
        'juicios_totales': juicios.get('total', 0),
        'juicios_aprobados': juicios.get('aprobados', 0),
        'pct_juicios': round(juicios['aprobados'] / juicios['total'] * 100) if juicios.get('total') else 0,
        'pct_tiempo': int(pct_tiempo or 0),
    }


def calcular_estadisticas_fichas(fichas, cronogramas, instructor_id=None, ahora=None):
    """(estados de aprendices por ficha, indicadores por ficha) para «Mis fichas».

    ``instructor_id`` limita las tareas a las del instructor; ``None`` (administrador) cuenta todas.
    """
    if not fichas:
        return {}, {}
    ahora = ahora or datetime.utcnow()
    ids = [f.id for f in fichas]
    estados = _estados_aprendices(ids)
    sesiones, faltas = _asistencia(ids)
    tareas = _tareas(ids, estados, instructor_id, ahora)
    por_calificar = _por_calificar(ids)
    alertas = _conteo(Alerta, ids, Alerta.estado == 'activa')
    planes = _conteo(PlanMejoramiento, ids, PlanMejoramiento.estado == 'pendiente')
    juicios, certificados = _juicios(ids)
    competencias = _competencias(ids)
    notas = _notas(ids)

    extra = {}
    for fid in ids:
        datos = estados.get(fid, {})
        nota = notas.get(fid, NOTAS_VACIAS)
        extra[fid] = {
            **consolidar_ficha(datos.get('activos', 0), datos.get('total', 0), sesiones.get(fid, 0), faltas.get(fid, 0),
                               tareas.get(fid, TAREAS_VACIAS), juicios.get(fid, {}), cronogramas.get(fid, {}).get('porcentaje', 0)),
            'por_calificar': por_calificar.get(fid, 0),
            'aprendices_certificados': certificados.get(fid, 0),
            'alertas_activas': alertas.get(fid, 0),
            'top_competencias': competencias.get(fid, []),
            'notas_positivas': nota['positiva'],
            'notas_negativas': nota['negativa'],
            'notas_neutras': nota['neutra'],
            'notas_total': sum(nota.values()),
            'planes_pendientes': planes.get(fid, 0),
        }
    return estados, extra
