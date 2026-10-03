"""Idempotent internal milestone notifications; the caller owns the transaction."""

from sqlalchemy.exc import IntegrityError

from app import db
from app.models.alertas import Notificacion
from app.models.ficha_instructor import FichaInstructor
from app.tyt.consulta import obtener_seguimiento


def _guardar(tipo, destinatario, ficha_id, clave, mensaje, url, existentes):
    identidad = dict(destinatario_tipo=tipo, destinatario_id=destinatario, clave=clave)
    if (tipo, destinatario) in existentes:
        return False
    try:
        with db.session.begin_nested():
            db.session.add(Notificacion(**identidad, ficha_id=ficha_id,
                                        mensaje=mensaje, url=url, tipo='tyt'))
            db.session.flush()
        return True
    except IntegrityError:
        # A concurrent review can insert the same recipient/key first.
        if not Notificacion.query.filter_by(**identidad).first():
            raise
        return False


def _mensaje_personal(fila):
    if not fila['total']:
        return 'Aún no hay resultados en el reporte. Solicita la actualización a tu instructor.'
    if fila['cumple_evaluacion']:
        evaluacion = 'Ya tienes al menos el 70 % de resultados evaluados.'
    else:
        evaluacion = f"Te falta evaluar {fila['faltan_evaluar']} resultado(s) para llegar al 70 %."
    return (f"{evaluacion} Tienes {fila['aprobados']} de {fila['total']} aprobados; "
            f"faltan {fila['faltan_aprobar']} resultado(s) por aprobar para esa meta.")


def actualizar_avisos(ficha, seguimiento=None, ahora=None):
    """Crea los avisos TyT faltantes y señala si hubo nuevas notificaciones."""
    if seguimiento is not None:
        tiempo = seguimiento['tiempo']
    else:
        from app.services.periodo_formacion import obtener_periodo_formacion
        from app.tyt.calculo import _tiempo, _hoy_colombia
        calendario = obtener_periodo_formacion(ficha, ahora)
        tiempo = _tiempo(calendario['inicio_lectiva'], calendario['fin_lectiva'], _hoy_colombia(ahora))

    if not tiempo['alcanzado']:
        return False

    clave = f"tyt:{ficha.id}:lectiva70:{tiempo['fecha_hito'].isoformat()}"
    existentes = set(Notificacion.query.with_entities(
        Notificacion.destinatario_tipo, Notificacion.destinatario_id,
    ).filter_by(ficha_id=ficha.id, clave=clave).all())

    instructores = {ficha.instructor_id}
    instructores.update(v.instructor_id for v in FichaInstructor.query.filter_by(ficha_id=ficha.id))

    faltan_instructores = any(('instructor', i_id) not in existentes for i_id in instructores if i_id)
    if not faltan_instructores:
        if any(d == 'aprendiz' for d, _ in existentes):
            return False
        from app.models.aprendiz import ESTADOS_EN_FORMACION, Aprendiz
        if not Aprendiz.query.filter(
            Aprendiz.ficha_id == ficha.id,
            Aprendiz.estado.in_(ESTADOS_EN_FORMACION),
        ).first():
            return False

    seguimiento = seguimiento or obtener_seguimiento(ficha, ahora)
    prefijo = (f"Saber TyT · Ficha {ficha.codigo}: se alcanzó el 70 % de la etapa lectiva "
               f"el {tiempo['fecha_hito'].strftime('%d/%m/%Y')}. ")
    mensaje = (f"{prefijo}{seguimiento['pendientes_evaluacion']} de "
               f"{seguimiento['total_aprendices']} aprendices aún no alcanzan el 70 % evaluado. "
               'Revisa el avance individual y coordina la preparación de Saber TyT.')
    creadas = 0
    for instructor_id in instructores:
        creadas += _guardar(
            'instructor', instructor_id, ficha.id, clave, mensaje,
            f'/instructor/fichas/{ficha.id}/seguimiento-tyt', existentes,
        )
    for fila in seguimiento['aprendices']:
        creadas += _guardar(
            'aprendiz', fila['id'], ficha.id, clave, prefijo + _mensaje_personal(fila),
            f'/aprendiz/{ficha.id}/panel#seguimiento-tyt-{ficha.id}', existentes,
        )
    return creadas > 0
