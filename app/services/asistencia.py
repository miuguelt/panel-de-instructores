"""Persistence and reporting helpers for attendance data."""

import time

from sqlalchemy.exc import IntegrityError, OperationalError

from app import db
from app.models.asistencia import RegistroAsistencia, SesionAsistencia


# La prioridad evita que una celda quede con un estado menos severo cuando
# existen registros históricos duplicados para la misma fecha. En condiciones
# normales la restricción única de sesión/fecha impide duplicados, pero la capa
# de presentación debe seguir siendo coherente con el detalle si hay datos
# antiguos que todavía no fueron saneados.
PRIORIDAD_ESTADO_ASISTENCIA = {
    'ASISTE': 1,
    'TARDANZA': 2,
    'FALTA_JUSTIFICADA': 3,
    'EXCUSA_MEDICA': 3,
    'FALTA': 4,
}

CLASE_ESTADO_ASISTENCIA = {
    'ASISTE': 'asiste',
    'TARDANZA': 'tardanza',
    'FALTA_JUSTIFICADA': 'falta-j',
    'EXCUSA_MEDICA': 'falta-j',
    'FALTA': 'falta-nj',
}

ETIQUETA_ESTADO_ASISTENCIA = {
    'ASISTE': 'Asistió',
    'TARDANZA': 'Tardanza',
    'FALTA_JUSTIFICADA': 'Falta justificada',
    'EXCUSA_MEDICA': 'Excusa médica',
    'FALTA': 'Falta injustificada',
}


def mapa_asistencia_por_fecha(registros):
    """Devuelve un único estado visual por fecha para un aprendiz.

    El resultado es directamente serializable a JSON y lo consumen tanto el
    calendario del instructor como el del aprendiz. Cuando hay más de un
    registro para una fecha, conserva el estado de mayor prioridad y, en empate,
    el registro más reciente.
    """
    resultado = {}
    for registro in registros:
        if not registro.sesion or not registro.sesion.fecha:
            continue
        estado = (registro.estado or '').upper()
        prioridad = PRIORIDAD_ESTADO_ASISTENCIA.get(estado, 0)
        fecha_iso = registro.sesion.fecha.isoformat()
        actual = resultado.get(fecha_iso)
        clave_nueva = (prioridad, registro.id or 0)
        clave_actual = (
            actual.get('_prioridad', 0),
            actual.get('_registro_id', 0),
        ) if actual else (-1, -1)
        if actual and clave_nueva <= clave_actual:
            continue
        resultado[fecha_iso] = {
            'estado': estado,
            'clase': CLASE_ESTADO_ASISTENCIA.get(estado, 'sin-registro'),
            'etiqueta': ETIQUETA_ESTADO_ASISTENCIA.get(estado, estado or 'Sin registro'),
            'causal_justificacion': registro.causal_justificacion or '',
            'nota': registro.nota or '',
            '_prioridad': prioridad,
            '_registro_id': registro.id or 0,
        }

    for evento in resultado.values():
        evento.pop('_prioridad', None)
        evento.pop('_registro_id', None)
    return resultado


def sesiones_registradas_query(ficha_id):
    """Return attendance sessions that contain at least one saved record."""
    return (
        SesionAsistencia.query
        .join(
            RegistroAsistencia,
            RegistroAsistencia.sesion_id == SesionAsistencia.id,
        )
        .filter(SesionAsistencia.ficha_id == ficha_id)
        .distinct()
    )


def contar_sesiones_registradas(ficha_id):
    """Count real attendance sessions, excluding calendar placeholders."""
    return sesiones_registradas_query(ficha_id).count()


def guardar_asistencia(ficha_id, fecha, registros, max_intentos=2):
    """Upsert one complete attendance call and commit it independently.

    ``registros`` maps learner ids to ``(estado, causal_justificacion)``.
    The short retry protects double submissions and transient PostgreSQL
    disconnects without allowing auxiliary modules to roll back attendance.
    """
    for intento in range(max_intentos):
        try:
            sesion = (
                SesionAsistencia.query
                .filter_by(ficha_id=ficha_id, fecha=fecha)
                .with_for_update()
                .first()
            )
            if not sesion:
                sesion = SesionAsistencia(ficha_id=ficha_id, fecha=fecha)
                db.session.add(sesion)
                db.session.flush()

            existentes = {
                registro.aprendiz_id: registro
                for registro in RegistroAsistencia.query.filter_by(
                    sesion_id=sesion.id
                ).all()
            }

            for aprendiz_id, (estado, causal) in registros.items():
                registro = existentes.get(aprendiz_id)
                if registro is None:
                    db.session.add(
                        RegistroAsistencia(
                            sesion_id=sesion.id,
                            aprendiz_id=aprendiz_id,
                            estado=estado,
                            causal_justificacion=causal,
                        )
                    )
                else:
                    registro.estado = estado
                    registro.causal_justificacion = causal

            db.session.commit()
            return sesion
        except (IntegrityError, OperationalError):
            db.session.rollback()
            if intento + 1 >= max_intentos:
                raise
            db.session.remove()
            time.sleep(0.15 * (2 ** intento))
        except Exception:
            db.session.rollback()
            raise

    raise RuntimeError('No fue posible guardar la asistencia.')
