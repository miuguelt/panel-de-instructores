"""Pure progress calculation; result identity and thresholds never use rounded values."""

from datetime import datetime, timedelta, timezone
import unicodedata


def _hoy_colombia(valor=None):
    if valor is None:
        valor = datetime.now(timezone.utc)
    if isinstance(valor, datetime):
        valor = valor.replace(tzinfo=valor.tzinfo or timezone.utc)
        return valor.astimezone(timezone(timedelta(hours=-5))).date()
    return valor


def _tiempo(inicio, fin, hoy):
    if not inicio or not fin or fin < inicio:
        return {'porcentaje': None, 'fecha_hito': None, 'dias_faltantes': None,
                'alcanzado': False}
    total = (fin - inicio).days + 1
    transcurridos = max(0, min((hoy - inicio).days + 1, total))
    meta = (total * 7 + 9) // 10
    fecha = inicio + timedelta(days=meta - 1)
    return {'porcentaje': round(transcurridos / total * 100, 1),
            'fecha_hito': fecha, 'dias_faltantes': max(0, (fecha - hoy).days),
            'alcanzado': transcurridos >= meta}


def _texto(valor):
    texto = unicodedata.normalize('NFKD', str(valor or ''))
    return ' '.join(''.join(c for c in texto if not unicodedata.combining(c)).upper().split())


def _individual(aprendiz, resultados, total, meta):
    estados = list(resultados.values())
    aprobados = sum(e in ('APROBADO', 'A') for e in estados)
    evaluados = sum(e in ('APROBADO', 'A', 'AUN NO APROBADO', 'NO APROBADO', 'NA')
                    for e in estados)
    return {**aprendiz, 'total': total, 'meta': meta,
            'aprobados': aprobados, 'evaluados': evaluados,
            'sin_registro': total - len(estados),
            'porcentaje_aprobados': round(aprobados / total * 100, 1) if total else None,
            'porcentaje_evaluados': round(evaluados / total * 100, 1) if total else None,
            'faltan_aprobar': max(0, meta - aprobados) if total else None,
            'faltan_evaluar': max(0, meta - evaluados) if total else None,
            'cumple_aprobacion': bool(total and aprobados >= meta),
            'cumple_evaluacion': bool(total and evaluados >= meta)}


def calcular_seguimiento(aprendices, juicios, inicio_lectiva, fin_lectiva, hoy=None):
    """Use the shared report catalog, including missing results as pending.

    Dates cover induction through the last teaching day, excluding practice.
    Judgments must be ordered oldest to newest; later imports replace the same RAP.
    """
    por_aprendiz = {a['id']: {} for a in aprendices}
    catalogo = set()
    for juicio in juicios:
        identidad = (_texto(juicio['competencia']), _texto(juicio['resultado_aprendizaje']))
        if juicio['aprendiz_id'] not in por_aprendiz or not identidad[1]:
            continue
        catalogo.add(identidad)
        por_aprendiz[juicio['aprendiz_id']][identidad] = _texto(juicio['juicio'])
    total = len(catalogo)
    meta = (total * 7 + 9) // 10
    filas = [_individual(a, por_aprendiz[a['id']], total, meta) for a in aprendices]
    denominador = total * len(filas)
    promedio = lambda campo: (round(sum(a[campo] for a in filas) / denominador * 100, 1)
                              if denominador else None)
    return {'tiempo': _tiempo(inicio_lectiva, fin_lectiva, _hoy_colombia(hoy)),
            'aprendices': filas, 'total_aprendices': len(filas),
            'total_resultados': total, 'meta_resultados': meta,
            'promedio_aprobados': promedio('aprobados'),
            'promedio_evaluados': promedio('evaluados'),
            'pendientes_evaluacion': sum(not a['cumple_evaluacion'] for a in filas),
            'pendientes_aprobacion': sum(not a['cumple_aprobacion'] for a in filas),
            'faltan_evaluar': sum(a['faltan_evaluar'] or 0 for a in filas) if total else None,
            'faltan_aprobar': sum(a['faltan_aprobar'] or 0 for a in filas) if total else None}
