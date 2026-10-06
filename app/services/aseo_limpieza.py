"""Limpieza de pendientes que ya no corresponden al calendario elegido."""

from datetime import datetime

from app import db
from app.models import IntercambioAseo
from app.services.festivos import es_festivo_colombia


def eliminar_turnos_fuera_del_calendario(existentes, dias_semana, estados_pendientes):
    """Elimina pendientes del rango recibido sin confirmar la transacción."""
    eliminables = [
        turno for turno in existentes.values()
        if turno.estado in estados_pendientes and (
            turno.fecha.weekday() not in dias_semana or es_festivo_colombia(turno.fecha)
        )
    ]
    if not eliminables:
        return 0

    ids = [turno.id for turno in eliminables]
    for intercambio in IntercambioAseo.query.filter(
        IntercambioAseo.turno_reciproco_id.in_(ids)
    ).all():
        intercambio.turno_reciproco = None
        if intercambio.estado == 'pendiente':
            intercambio.estado = 'rechazado'
            intercambio.respondido_en = datetime.utcnow()
    db.session.flush()

    for turno in eliminables:
        existentes.pop(turno.fecha, None)
        db.session.delete(turno)
    db.session.flush()
    return len(eliminables)
