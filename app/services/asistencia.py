"""Persistence and reporting helpers for attendance data."""

import time

from sqlalchemy.exc import IntegrityError, OperationalError

from app import db
from app.models.asistencia import RegistroAsistencia, SesionAsistencia


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
