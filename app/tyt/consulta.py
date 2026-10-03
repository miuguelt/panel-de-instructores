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


def obtener_seguimiento_por_fichas(fichas, hoy=None):
    """Carga y calcula el seguimiento TyT para un conjunto de fichas en solo dos consultas."""
    if not fichas:
        return {}
    ficha_ids = [f.id for f in fichas]
    aprendices_todos = (
        Aprendiz.query.filter(Aprendiz.ficha_id.in_(ficha_ids))
        .order_by(Aprendiz.ficha_id, Aprendiz.apellidos, Aprendiz.nombre)
        .all()
    )
    juicios_todos = (
        JuicioEvaluativo.query.with_entities(
            JuicioEvaluativo.ficha_id,
            JuicioEvaluativo.aprendiz_id,
            JuicioEvaluativo.competencia,
            JuicioEvaluativo.resultado_aprendizaje,
            JuicioEvaluativo.juicio,
        )
        .filter(JuicioEvaluativo.ficha_id.in_(ficha_ids))
        .order_by(
            JuicioEvaluativo.ficha_id,
            JuicioEvaluativo.importado_en,
            JuicioEvaluativo.id,
        )
        .all()
    )

    aprendices_por_ficha = {fid: [] for fid in ficha_ids}
    for a in aprendices_todos:
        if a.activo_en_planeacion:
            aprendices_por_ficha[a.ficha_id].append(a)

    juicios_por_ficha = {fid: [] for fid in ficha_ids}
    for j in juicios_todos:
        juicios_por_ficha[j.ficha_id].append({
            'aprendiz_id': j.aprendiz_id,
            'competencia': j.competencia,
            'resultado_aprendizaje': j.resultado_aprendizaje,
            'juicio': j.juicio,
        })

    resultados = {}
    for ficha in fichas:
        fid = ficha.id
        ap_lista = [{'id': a.id, 'nombre': a.nombre_completo} for a in aprendices_por_ficha.get(fid, [])]
        j_lista = juicios_por_ficha.get(fid, [])
        calendario = obtener_periodo_formacion(ficha, hoy)
        seguimiento = calcular_seguimiento(
            ap_lista,
            j_lista,
            calendario['inicio_lectiva'],
            calendario['fin_lectiva'],
            hoy,
        )
        resultados[fid] = {**seguimiento, 'calendario': calendario}
    return resultados

