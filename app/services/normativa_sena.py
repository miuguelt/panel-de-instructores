"""Catálogo verificado de normas SENA que sustentan las remisiones a comité.

Cada fundamento indica norma, artículo, numeral, literal o parágrafo y la página
del PDF oficial donde el instructor puede leer el texto. Las páginas se
comprobaron sobre el escaneo oficial del Acuerdo 009 de 2024 (48 páginas), cuya
numeración impresa coincide con la página del PDF.

Las citas son resúmenes fieles y breves, no transcripciones completas: el texto
vinculante es siempre el del PDF.
"""

import hashlib
from pathlib import Path

DIRECTORIO_NORMATIVA = Path(__file__).resolve().parent.parent / 'normativa'

ACUERDO_009 = 'acuerdo-009-2024'

CATALOGO_NORMAS = {
    ACUERDO_009: {
        'id': ACUERDO_009,
        'titulo': 'Acuerdo 009 de 2024 — Reglamento del Aprendiz SENA',
        'entidad': 'Consejo Directivo Nacional del SENA',
        'fecha': '2024-11-20',
        'publicacion': 'Diario Oficial No. 52.947 del 21 de noviembre de 2024',
        'deroga': 'Acuerdos 07 de 2012, 02 de 2014, 06 de 2023 y 02 de 2024',
        'url_oficial': 'https://normograma.sena.edu.co/compilacion/docs/acuerdo_sena_0009_2024.htm',
        'archivo': 'acuerdo_009_2024_reglamento_aprendiz.pdf',
        'sha256': '9cac709d79f48e0d73e3cdace0f2b3738d0a7ecbf95c4f8dbea043bbe2cb605c',
        'paginas': 48,
    },
}

FUNDAMENTOS = {
    'productiva_vencida': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 30',
        'ubicacion': 'numeral 2 — Deserción por incumplimiento de la etapa productiva',
        'pagina': 31,
        'cita': (
            'Hay deserción cuando, terminada la etapa lectiva y con plazo límite la '
            'finalización por fecha del grupo, el aprendiz no ha presentado la planeación '
            'de su etapa productiva avalada por el instructor de seguimiento.'
        ),
        'verificado': True,
    },
    'procedimiento_desercion_productiva': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 31',
        'ubicacion': 'numeral 2 y parágrafo 1',
        'pagina': 31,
        'cita': (
            'Si el aprendiz no informa el motivo del incumplimiento o abandona el proceso, '
            'el instructor de etapa productiva reporta la situación al comité de evaluación '
            'y seguimiento, que revisa el caso para confirmar la deserción.'
        ),
        'verificado': True,
    },
    'cancelacion_un_anio': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 47',
        'ubicacion': 'numeral 2 (Cancelación de matrícula), parágrafo 1',
        'pagina': 39,
        'cita': (
            'Los aprendices que no se hayan certificado luego de transcurrido un año de la '
            'fecha fin programada para el grupo pasarán a estado cancelado por vía administrativa.'
        ),
        'verificado': True,
    },
    'aplazamiento': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 18',
        'ubicacion': 'numeral 2 — Aplazamiento',
        'pagina': 22,
        'cita': (
            'El aplazamiento se autoriza hasta por tres meses calendario; el comité puede '
            'recomendar ampliarlo hasta por tres meses más previa solicitud del aprendiz.'
        ),
        'verificado': True,
    },
    'traslado': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 18',
        'ubicacion': 'numeral 1 — Traslado',
        'pagina': 21,
        'cita': (
            'El traslado es la solicitud formal para continuar la formación en otro centro, '
            'jornada o modalidad; la coordinación académica analiza su viabilidad y recomienda '
            'a la subdirección.'
        ),
        'verificado': True,
    },
    'reintegro_solicitud': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 18',
        'ubicacion': 'numeral 3 — Reintegro',
        'pagina': 23,
        'cita': (
            'El aprendiz debe solicitar el reintegro dentro de los cinco días hábiles previos al '
            'vencimiento del aplazamiento; si no lo solicita o no se reintegra en el plazo, se '
            'entiende como causal de deserción.'
        ),
        'verificado': True,
    },
    'retiro_voluntario': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 18',
        'ubicacion': 'numeral 4 — Retiro voluntario',
        'pagina': 24,
        'cita': (
            'El retiro voluntario sin causa justificable (incapacidad, licencia, calamidad, '
            'asuntos judiciales o servicio militar) constituye falta grave y se registra como '
            'cancelación de la matrícula.'
        ),
        'verificado': True,
    },
    'aplazamiento_vencido': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 30',
        'ubicacion': 'numeral 3 — Deserción por falta de gestión oportuna de novedades',
        'pagina': 31,
        'cita': (
            'Hay deserción cuando el aprendiz no gestiona el reintegro por lo menos tres '
            'días hábiles antes de la fecha fin del aplazamiento.'
        ),
        'verificado': True,
    },
    'consecutivas_injustificadas': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 30',
        'ubicacion': 'numeral 1, literal a',
        'pagina': 30,
        'cita': (
            'En formación presencial hay deserción al tener tres días continuos de '
            'inasistencia injustificada o acumular cinco días no continuos de inasistencia '
            'injustificada durante todo el proceso.'
        ),
        'verificado': True,
    },
    'acumuladas_proceso': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 30',
        'ubicacion': 'numeral 1, literal a',
        'pagina': 30,
        'cita': (
            'Acumular cinco días no continuos de inasistencia injustificada durante todo '
            'el proceso de formación configura deserción en formación presencial.'
        ),
        'verificado': True,
    },
    'inasistencia_injustificada': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 28 (parágrafo 3) y Artículo 29',
        'ubicacion': 'plazo de cinco días hábiles para justificar',
        'pagina': 30,
        'cita': (
            'La inasistencia no programada debe informarse dentro de los cinco días hábiles '
            'siguientes con soportes; si no se reporta o los soportes no corresponden, es '
            'incumplimiento injustificado.'
        ),
        'verificado': True,
    },
    'procedimiento_desercion_inasistencia': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 31',
        'ubicacion': 'numeral 1',
        'pagina': 31,
        'cita': (
            'Si el aprendiz no justifica la inasistencia, el instructor y el equipo ejecutor '
            'reportan la situación al comité de evaluación y seguimiento.'
        ),
        'verificado': True,
    },
    'tareas_incumplidas': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 46',
        'ubicacion': 'numeral 1, literales a y b; parágrafo 4',
        'pagina': 37,
        'pagina_final': 38,
        'cita': (
            'Ante incumplimiento académico proceden hasta dos llamados de atención escritos y '
            'luego un plan de mejoramiento de máximo 20 días calendario; si el aprendiz no lo '
            'cumple, el caso se lleva a comité de evaluación y seguimiento.'
        ),
        'verificado': True,
    },
    'notas_observador': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 46',
        'ubicacion': 'numeral 2, literales a y b; parágrafo 4',
        'pagina': 38,
        'cita': (
            'Las medidas formativas disciplinarias son hasta dos llamados de atención escritos '
            'y un plan de mejoramiento disciplinario; si no se cumple, el caso va a comité.'
        ),
        'verificado': True,
    },
    'porcentaje_asistencia': {
        'norma_id': None,
        'articulo': 'Umbral configurado en el panel',
        'ubicacion': 'Configuración de alertas de la ficha',
        'pagina': None,
        'cita': (
            'El Acuerdo 009 de 2024 no fija un porcentaje mínimo de asistencia para la '
            'formación titulada. Este indicador es preventivo; para remitir a comité use '
            'las causales del Artículo 30, numeral 1, literal a (página 30).'
        ),
        'verificado': False,
    },
    'procedimiento_comite': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 51',
        'ubicacion': 'numerales 1 y 2 — informe o queja y citación al aprendiz',
        'pagina': 43,
        'cita': (
            'El procedimiento inicia con un informe que contenga fecha, descripción detallada '
            'de los hechos y firma; la citación al comité se hace dentro de los tres días '
            'hábiles siguientes al recibo del informe.'
        ),
        'verificado': True,
    },
    'plazo_justificacion': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 28',
        'ubicacion': 'parágrafo 3 — inasistencias no programadas',
        'pagina': 30,
        'cita': (
            'Las inasistencias no programadas deben informarse al instructor a más tardar '
            'dentro de los cinco días hábiles siguientes a su ocurrencia, con los soportes.'
        ),
        'verificado': True,
    },
    'llamado_academico': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 46',
        'ubicacion': 'numeral 1, literal a — llamado de atención académico',
        'pagina': 37,
        'cita': (
            'Los llamados de atención académicos son por escrito; el aprendiz puede recibir '
            'hasta dos por fase del proyecto formativo, y el segundo va acompañado de '
            'orientaciones académicas escritas.'
        ),
        'verificado': True,
    },
    'plan_academico': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 46',
        'ubicacion': 'numeral 1, literal b y parágrafo 1 — plan de mejoramiento académico',
        'pagina': 37,
        'cita': (
            'Agotados los dos llamados de atención se establece un plan de mejoramiento que no '
            'puede superar 20 días calendario; máximo dos por fase o módulo de la etapa lectiva '
            'y uno por etapa productiva.'
        ),
        'verificado': True,
    },
    'llamado_disciplinario': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 46',
        'ubicacion': 'numeral 2, literal a — llamado de atención disciplinario',
        'pagina': 38,
        'cita': (
            'El aprendiz puede recibir hasta dos llamados de atención disciplinarios escritos '
            'durante la duración del programa; el segundo se acompaña de recomendaciones de '
            'mejoramiento.'
        ),
        'verificado': True,
    },
    'citacion_comite': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 51',
        'ubicacion': 'numeral 2, literales a a g — contenido de la citación',
        'pagina': 44,
        'cita': (
            'La citación incluye relación del informe y pruebas, identificación del aprendiz, '
            'normas presuntamente infringidas, tipo y calificación provisional de la falta, '
            'derecho a descargos, y lugar, fecha y hora de la sesión, que debe realizarse '
            'dentro de los diez días hábiles siguientes al recibo del informe.'
        ),
        'verificado': True,
    },
    'debido_proceso': {
        'norma_id': ACUERDO_009,
        'articulo': 'Artículo 50',
        'ubicacion': 'numerales 1 a 7 — criterios para aplicar sanciones',
        'pagina': 42,
        'cita': (
            'Toda actuación garantiza publicidad, contradicción, presunción de inocencia, '
            'valoración integral de pruebas, motivación y proporcionalidad.'
        ),
        'verificado': True,
    },
}


def obtener_norma(norma_id):
    """Devuelve la ficha de una norma del catálogo o None si no existe."""
    return CATALOGO_NORMAS.get(norma_id)


def ruta_archivo(norma_id):
    """Ruta local del PDF de la norma, o None si la norma no existe."""
    norma = obtener_norma(norma_id)
    if not norma:
        return None
    return DIRECTORIO_NORMATIVA / norma['archivo']


def url_descarga(norma_id, pagina=None):
    """URL interna para abrir el PDF, posicionada en la página indicada."""
    if not obtener_norma(norma_id):
        return None
    base = f'/instructor/normativa/{norma_id}'
    return f'{base}#page={int(pagina)}' if pagina else base


def obtener_fundamento(clave):
    """Fundamento listo para guardar en una alerta y mostrar al instructor.

    Lanza KeyError si la clave no existe: una regla sin fundamento es un error
    de programación que no debe llegar silenciosamente a la interfaz.
    """
    base = FUNDAMENTOS[clave]
    norma = obtener_norma(base['norma_id']) if base['norma_id'] else None
    fundamento = dict(base)
    fundamento['clave'] = clave
    fundamento['norma'] = norma['titulo'] if norma else None
    fundamento['url'] = url_descarga(base['norma_id'], base['pagina']) if norma else None
    fundamento['referencia'] = formatear_referencia(fundamento)
    return fundamento


def formatear_referencia(fundamento):
    """Texto corto: 'Acuerdo 009 de 2024 — Artículo 30, numeral 2 (pág. 31)'."""
    if not fundamento.get('norma_id'):
        return f"{fundamento['articulo']} (sin respaldo normativo explícito)"
    norma = obtener_norma(fundamento['norma_id'])
    corto = norma['titulo'].split(' — ')[0]
    pagina = fundamento['pagina']
    if fundamento.get('pagina_final'):
        paginas = f"págs. {pagina}-{fundamento['pagina_final']}"
    else:
        paginas = f'pág. {pagina}'
    return f"{corto} — {fundamento['articulo']}, {fundamento['ubicacion']} ({paginas})"


def fundamentos_de(*claves):
    """Lista de fundamentos para varias claves, en el orden recibido."""
    return [obtener_fundamento(clave) for clave in claves]


def sha256_archivo(ruta):
    digest = hashlib.sha256()
    with open(ruta, 'rb') as archivo:
        for bloque in iter(lambda: archivo.read(65536), b''):
            digest.update(bloque)
    return digest.hexdigest()


def validar_catalogo():
    """Lista de problemas del catálogo; vacía cuando todo es consistente."""
    problemas = []
    for norma_id, norma in CATALOGO_NORMAS.items():
        ruta = ruta_archivo(norma_id)
        if not ruta.is_file():
            problemas.append(f'{norma_id}: falta el archivo {norma["archivo"]}')
        elif sha256_archivo(ruta) != norma['sha256']:
            problemas.append(f'{norma_id}: el hash SHA-256 no coincide')
    for clave, fundamento in FUNDAMENTOS.items():
        norma_id = fundamento['norma_id']
        if norma_id is None:
            if fundamento['verificado']:
                problemas.append(f'{clave}: sin norma no puede marcarse como verificado')
            continue
        norma = obtener_norma(norma_id)
        if not norma:
            problemas.append(f'{clave}: norma desconocida {norma_id}')
            continue
        ultima = fundamento.get('pagina_final', fundamento['pagina'])
        if not (1 <= fundamento['pagina'] <= ultima <= norma['paginas']):
            problemas.append(f'{clave}: página fuera del documento')
    return problemas
