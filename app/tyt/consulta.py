"""Read the authoritative report in two queries, independently of learner count."""

from app.models.aprendiz import Aprendiz
from app.models.juicio import JuicioEvaluativo
from app.tyt.calculo import calcular_seguimiento
from app.services.periodo_formacion import obtener_periodo_formacion


def obtener_seguimiento(ficha, hoy=None):
    aprendices = [a for a in Aprendiz.query.filter_by(ficha_id=ficha.id)
                  .order_by(Aprendiz.apellidos, Aprendiz.nombre).all()
                  if a.activo_en_planeacion]
    juicios = JuicioEvaluativo.query.with_entities(
        JuicioEvaluativo.aprendiz_id, JuicioEvaluativo.competencia,
        JuicioEvaluativo.resultado_aprendizaje, JuicioEvaluativo.juicio,
    ).filter_by(ficha_id=ficha.id).order_by(
        JuicioEvaluativo.importado_en, JuicioEvaluativo.id,
    ).all()
    calendario = obtener_periodo_formacion(ficha, hoy)
    seguimiento = calcular_seguimiento(
        [{'id': a.id, 'nombre': a.nombre_completo} for a in aprendices],
        [dict(j._mapping) for j in juicios],
        calendario['inicio_lectiva'], calendario['fin_lectiva'], hoy,
    )
    return {**seguimiento, 'calendario': calendario}
