"""Qué le falta a los datos para que la línea de tiempo sea exacta.

La vista no puede afirmar que una ficha va atrasada si la evidencia está
incompleta. Este módulo enumera, en lenguaje del instructor, los vacíos que
degradan la precisión y la acción concreta que los cierra.
"""

from __future__ import annotations


def _plural(cantidad, singular, plural):
    return f'{cantidad} {singular if cantidad == 1 else plural}'


def _sin_trimestre(resultados):
    estimados = [item for item in resultados if not item.get('trimestre_declarado')
                 and item.get('etapa') != 'productiva']
    if not estimados:
        return None
    actividades = sorted({item.get('actividad') or 'Sin actividad' for item in estimados})
    return {
        'clave': 'trimestre_estimado',
        'tono': 'warning',
        'titulo': 'Resultados sin trimestre declarado en la planeación',
        'detalle': (
            f'{_plural(len(estimados), "resultado", "resultados")} de '
            f'{_plural(len(actividades), "actividad", "actividades")} no traen la columna '
            'TRIMESTRE del formato GFPI-F-134, así que su ubicación se estimó con el orden '
            'de las actividades del proyecto.'
        ),
        'accion': 'Completa la columna TRIMESTRE en: ' + ', '.join(actividades[:4]) + '.',
    }


def _duracion_inconsistente(resultados, calendario):
    lectivos = calendario.get('trimestres_lectivos') or 0
    declarados = [item['trimestre_fin'] for item in resultados if item.get('trimestre_declarado')]
    maximo = max(declarados, default=0)
    if not maximo or maximo <= lectivos:
        return None
    return {
        'clave': 'duracion_inconsistente',
        'tono': 'danger',
        'titulo': 'La planeación declara más trimestres que la duración de la ficha',
        'detalle': (
            f'El documento llega hasta el trimestre {maximo}, pero las fechas de la ficha '
            f'solo dan para {_plural(lectivos, "trimestre lectivo", "trimestres lectivos")} '
            f'({calendario.get("meses_lectiva")} meses) más '
            f'{calendario.get("meses_productiva")} meses de etapa productiva.'
        ),
        'accion': 'Revisa la fecha de finalización de la ficha o la duración de la etapa productiva.',
    }


def _sin_correspondencia(resumen):
    cantidad = (resumen or {}).get('resultados_sin_planeacion') or 0
    if not cantidad:
        return None
    return {
        'clave': 'sin_correspondencia',
        'tono': 'warning',
        'titulo': 'Resultados del reporte que no existen en la planeación',
        'detalle': (
            f'{_plural(cantidad, "resultado", "resultados")} del Reporte de Juicios Evaluativos '
            'no se pudo ubicar en ninguna unidad planeada, así que su tiempo no entra en la línea.'
        ),
        'accion': 'Verifica que la planeación cargada sea la versión vigente del programa.',
    }


def _aprobaciones_previas(cantidad, calendario):
    if not cantidad:
        return None
    inicio = calendario.get('inicio')
    return {
        'clave': 'aprobaciones_previas',
        'tono': 'info',
        'titulo': 'Aprobaciones anteriores al inicio de la ficha',
        'detalle': (
            f'{_plural(cantidad, "juicio aprobado tiene", "juicios aprobados tienen")} fecha anterior '
            f'al {inicio.strftime("%d/%m/%Y") if inicio else "inicio de la ficha"}. '
            'Suelen ser homologaciones o traslados y no reflejan el ritmo de este grupo.'
        ),
        'accion': 'Se excluyen del ritmo proyectado; confírmalas si esperabas otra cosa.',
    }


def _sin_programa(contraste):
    if contraste and contraste.get('disponible'):
        return None
    return {
        'clave': 'sin_programa',
        'tono': 'info',
        'titulo': 'Falta el Programa de Formación para validar la planeación',
        'detalle': (
            'Sin el PDF oficial no hay contra quién comparar: no se puede saber si la '
            'planeación reparte las horas que exige el diseño curricular, si dejó '
            'competencias sin planear ni qué intensidad horaria implica el calendario.'
        ),
        'accion': 'Cárgalo en el área de documentos de la ficha; es un PDF y se lee automáticamente.',
    }


def _horas_desalineadas(contraste):
    horas = (contraste or {}).get('horas') or {}
    if not horas or horas.get('estado') == 'coincide':
        return None
    diferencia = horas['diferencia']
    verbo = 'más' if diferencia > 0 else 'menos'
    return {
        'clave': 'horas_desalineadas',
        'tono': 'warning',
        'titulo': 'La planeación no reparte las horas del programa',
        'detalle': (
            f'La planeación suma {horas["planeacion"]:g} horas y el programa declara '
            f'{horas["programa_lectiva"]:g} horas lectivas: '
            f'{abs(diferencia):g} horas de {verbo}.'
        ),
        'accion': 'Revisa las horas por competencia en el contraste con el programa.',
    }


def _competencias_sin_planear(contraste):
    faltantes = (contraste or {}).get('competencias_sin_planear') or []
    if not faltantes:
        return None
    horas = sum(dato['horas'] for dato in faltantes)
    return {
        'clave': 'competencias_sin_planear',
        'tono': 'danger',
        'titulo': 'Competencias del programa que la planeación no incluye',
        'detalle': (
            f'{_plural(len(faltantes), "competencia del diseño curricular no aparece", "competencias del diseño curricular no aparecen")} '
            f'en la planeación cargada, con {horas:g} horas oficiales sin repartir: '
            + ', '.join(dato['nombre'][:60] for dato in faltantes[:3])
            + ('…' if len(faltantes) > 3 else '.')
        ),
        'accion': 'Confirma que la planeación corresponde a la versión vigente del programa.',
    }


def _resultados_sin_planear(contraste):
    faltantes = (contraste or {}).get('resultados_sin_planear') or []
    if not faltantes:
        return None
    return {
        'clave': 'resultados_sin_planear',
        'tono': 'warning',
        'titulo': 'Resultados de aprendizaje del programa sin planear',
        'detalle': (
            f'{_plural(len(faltantes), "resultado oficial no tiene", "resultados oficiales no tienen")} '
            'una unidad equivalente en la planeación, así que nunca aparecerán en la línea de tiempo.'
        ),
        'accion': 'Compáralos en el detalle del contraste con el programa.',
    }


def _intensidad_exigente(contraste):
    intensidad = (contraste or {}).get('intensidad') or {}
    horas_semana = intensidad.get('horas_semana') or 0
    if not horas_semana or horas_semana <= 40:
        return None
    return {
        'clave': 'intensidad_exigente',
        'tono': 'warning',
        'titulo': 'El calendario exige más horas de las que caben en una semana',
        'detalle': (
            f'{intensidad["horas_lectivas"]:g} horas lectivas en {intensidad["meses"]} meses '
            f'equivalen a {intensidad["horas_semana"]:g} horas por semana.'
        ),
        'accion': 'Revisa las fechas de la ficha o la duración de la etapa productiva.',
    }


def _sin_fechas(calendario):
    if calendario.get('configurado'):
        return None
    return {
        'clave': 'sin_fechas',
        'tono': 'danger',
        'titulo': 'La ficha no tiene fechas de inicio y finalización',
        'detalle': 'Sin ellas no existe calendario y ningún trimestre puede ubicarse.',
        'accion': 'Registra las fechas de la ficha para habilitar la línea de tiempo.',
    }


def revisar_datos_planeacion(resultados, calendario, resumen=None, aprobaciones_previas=0,
                             contraste=None):
    """Enumera los vacíos de datos que degradan la precisión de la línea de tiempo."""
    hallazgos = [
        _sin_fechas(calendario),
        _competencias_sin_planear(contraste),
        _duracion_inconsistente(resultados, calendario),
        _horas_desalineadas(contraste),
        _intensidad_exigente(contraste),
        _sin_trimestre(resultados),
        _resultados_sin_planear(contraste),
        _sin_correspondencia(resumen),
        _aprobaciones_previas(aprobaciones_previas, calendario),
        _sin_programa(contraste),
    ]
    return [hallazgo for hallazgo in hallazgos if hallazgo]
