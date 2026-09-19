"""Check milestones using the existing worker, without starting another scheduler."""

from datetime import datetime, timedelta, timezone

from flask import current_app

from app import db
from app.models.ficha import Ficha
from app.tyt.avisos import actualizar_avisos


def revisar_hitos():
    ahora = datetime.now(timezone.utc)
    hoy = ahora.astimezone(timezone(timedelta(hours=-5))).date()
    fichas = Ficha.query.filter(Ficha.fecha_inicio <= hoy, Ficha.fecha_fin >= hoy).all()
    for ficha in fichas:
        ficha_id = ficha.id
        try:
            actualizar_avisos(ficha, ahora=ahora)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('No se pudo revisar el hito TyT de la ficha %s.', ficha_id)
