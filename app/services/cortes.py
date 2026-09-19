from datetime import datetime

from sqlalchemy import and_, or_
from flask_login import current_user

from app import db
from app.models.corte import Corte
from app.models.ficha_instructor import FichaInstructor


def cortes_visibles(ficha_id):
    """Consulta los cortes propios y los que el responsable decidió compartir."""
    consulta = Corte.query.filter_by(ficha_id=ficha_id)
    if not getattr(current_user, 'is_authenticated', False) or getattr(current_user, 'es_admin', False):
        return consulta
    return consulta.filter(
        or_(
            Corte.instructor_id == current_user.id,
            and_(
                Corte.compartido.is_(True),
                Corte.ficha_id.in_(
                    db.session.query(FichaInstructor.ficha_id).filter_by(
                        instructor_id=current_user.id,
                        ficha_id=ficha_id,
                    )
                ),
            ),
        )
    )


def corte_visible(ficha_id, corte_id):
    if not corte_id:
        return None
    return cortes_visibles(ficha_id).filter(Corte.id == corte_id).first()


def corte_actual(ficha_id, corte_id=None):
    """Obtiene el corte solicitado o el corte activo más reciente."""
    if corte_id:
        return corte_visible(ficha_id, corte_id)

    propios = cortes_visibles(ficha_id)
    if getattr(current_user, 'is_authenticated', False) and not getattr(current_user, 'es_admin', False):
        propios = propios.filter(Corte.instructor_id == current_user.id)
        propio_activo = propios.filter(Corte.estado == Corte.ESTADO_ACTIVO).order_by(
            Corte.fecha_inicio.desc(), Corte.id.desc()
        ).first()
        if propio_activo:
            return propio_activo
        return propios.order_by(Corte.fecha_inicio.desc(), Corte.id.desc()).first()
    activo = propios.filter(Corte.estado == Corte.ESTADO_ACTIVO).order_by(
        Corte.fecha_inicio.desc(), Corte.id.desc()
    ).first()
    if activo:
        return activo
    return propios.order_by(Corte.fecha_inicio.desc(), Corte.id.desc()).first()


def siguiente_nombre_corte(ficha_id, instructor_id):
    cantidad = Corte.query.filter_by(
        ficha_id=ficha_id,
        instructor_id=instructor_id,
    ).count()
    return f'Corte {cantidad + 1}'


def cambiar_estado_corte(corte, estado, ahora=None):
    """Aplica las transiciones permitidas del ciclo de vida de un corte.

    Un corte archivado es inmutable. Al reactivar uno cerrado se cierra el
    corte activo anterior del mismo instructor para conservar un único corte
    de trabajo por instructor y ficha.
    """
    if not corte or estado not in Corte.ESTADOS:
        return False
    ahora = ahora or datetime.utcnow()

    if corte.estado == Corte.ESTADO_ARCHIVADO:
        return estado == Corte.ESTADO_ARCHIVADO
    if estado == Corte.ESTADO_ARCHIVADO and corte.estado != Corte.ESTADO_CERRADO:
        return False

    if estado == Corte.ESTADO_ACTIVO:
        Corte.query.filter(
            Corte.ficha_id == corte.ficha_id,
            Corte.instructor_id == corte.instructor_id,
            Corte.id != corte.id,
            Corte.estado == Corte.ESTADO_ACTIVO,
        ).update(
            {
                Corte.estado: Corte.ESTADO_CERRADO,
                Corte.fecha_fin: ahora,
            },
            synchronize_session=False,
        )
        corte.estado = Corte.ESTADO_ACTIVO
        corte.fecha_fin = None
        return True

    if estado == Corte.ESTADO_CERRADO:
        corte.estado = Corte.ESTADO_CERRADO
        corte.fecha_fin = corte.fecha_fin or ahora
        return True

    corte.estado = Corte.ESTADO_ARCHIVADO
    corte.fecha_fin = corte.fecha_fin or ahora
    return True
