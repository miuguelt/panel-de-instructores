"""Invalidación de resultados al cambiar datos que alimentan los análisis."""

from sqlalchemy import event, inspect, update
from sqlalchemy.orm import Session


_CAMPOS_FICHA = {
    'fecha_inicio', 'fecha_fin', 'duracion_productiva_meses',
    'codigo_programa', 'nombre_programa',
}


def _ficha_afectada(entidad):
    """Retorna la ficha asociada a una entidad que cambia resultados."""
    from app.models import Aprendiz, ArchivoFichaVersion, Ficha, JuicioEvaluativo

    if isinstance(entidad, Ficha):
        estado = inspect(entidad)
        return entidad.id if any(
            estado.attrs[campo].history.has_changes() for campo in _CAMPOS_FICHA
        ) else None
    if isinstance(entidad, (Aprendiz, ArchivoFichaVersion, JuicioEvaluativo)):
        return entidad.ficha_id
    return None


@event.listens_for(Session, 'before_flush')
def invalidar_resultados_al_guardar(session, _flush_context, _instances):
    """Sube la revisión una vez por ficha cuando cambian sus datos fuente."""
    from app.models import Ficha

    fichas = set()
    for entidad in session.new.union(session.dirty).union(session.deleted):
        ficha_id = _ficha_afectada(entidad)
        if ficha_id:
            fichas.add(ficha_id)
    for ficha_id in fichas:
        session.execute(
            update(Ficha)
            .where(Ficha.id == ficha_id)
            .values(revision_calculos=Ficha.revision_calculos + 1)
        )
        for ficha in session.identity_map.values():
            if isinstance(ficha, Ficha) and ficha.id == ficha_id:
                session.expire(ficha, ['revision_calculos'])
