"""Programa de formación mínimo en PDF para las pruebas del módulo.

Reproduce los marcadores del documento oficial del SENA: duración por etapa,
bloques ``4. CONTENIDOS CURRICULARES DE LA COMPETENCIA`` con su código de norma,
la duración máxima estimada y la lista numerada de resultados de aprendizaje.
"""

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


COMPETENCIAS_EJEMPLO = [
    {
        'codigo': '220501092',
        'norma': 'Establecer requisitos de la solución de software de acuerdo con estándares y procedimiento técnico',
        'nombre': 'ESPECIFICACIÓN DE REQUISITOS DEL SOFTWARE',
        'horas': 144,
        'resultados': [
            '01  Caracterizar los procesos de la organización de acuerdo con el software a construir.',
            '02  Recolectar información del software a construir de acuerdo con las necesidades del cliente.',
        ],
        'conocimientos_proceso': [
            '* IDENTIFICAR PROCESOS DE LA ORGANIZACIÓN.',
            '* APLICAR TÉCNICAS DE ANÁLISIS DE PROCESOS.',
            '* ELABORAR DIAGRAMA DE PROCESOS.',
        ],
        'conocimientos_saber': [
            '* TEORÍA GENERAL DE SISTEMAS: ORÍGENES, CONCEPTOS.',
            '* SISTEMAS DE INFORMACIÓN: ELEMENTOS, OBJETIVOS.',
        ],
        'criterios_evaluacion': [
            '* IDENTIFICA PROCESOS DE LA ORGANIZACIÓN DE ACUERDO CON LA ESTRUCTURA ORGANIZACIONAL.',
            '* APLICA TÉCNICAS DE ANÁLISIS DE PROCESOS.',
        ],
        'requisitos_academicos': 'TECNÓLOGO O PROFESIONAL EN SISTEMAS Y AFINES.',
        'experiencia': 'VEINTICUATRO (24) MESES DE EXPERIENCIA.',
    },
    {
        'codigo': '240201524',
        'norma': 'Desarrollar procesos de comunicación eficaces y efectivos',
        'nombre': 'COMUNICACIÓN',
        'horas': 48,
        'resultados': ['01  Interpretar el contexto comunicativo.'],
        'conocimientos_proceso': ['* MANTENER LA ATENCIÓN Y ESCUCHA EN LOS PROCESOS DE COMUNICACIÓN.'],
        'conocimientos_saber': ['* COMUNICACIÓN: CONCEPTO, TIPOS, USOS.'],
        'criterios_evaluacion': ['* RECONOCE LA IMPORTANCIA DE LA COMUNICACIÓN HUMANA.'],
        'requisitos_academicos': 'PROFESIONAL EN CIENCIAS DE LA COMUNICACIÓN.',
        'experiencia': 'DOCE (12) MESES DE EXPERIENCIA.',
    },
    {
        'codigo': '999999999',
        'norma': 'RESULTADOS DE APRENDIZAJE ETAPA PRACTICA',
        'nombre': 'ETAPA PRACTICA',
        'horas': 864,
        'resultados': [],
        'conocimientos_proceso': [],
        'conocimientos_saber': [],
        'criterios_evaluacion': [],
        'requisitos_academicos': '',
        'experiencia': '',
    },
]


def _lineas_competencia(competencia):
    lineas = [
        '4. CONTENIDOS CURRICULARES DE LA COMPETENCIA',
        competencia.get('norma', competencia['nombre']),
        '4.1 NORMA / UNIDAD DE',
        'COMPETENCIA',
        f"{competencia['codigo']} 4.2 CÓDIGO NORMA DE",
        'COMPETENCIA LABORAL',
        f"4.3 NOMBRE DE LA COMPETENCIA {competencia['nombre']}",
        '4.5 RESULTADOS DE APRENDIZAJE',
        '4.4 DURACIÓN MÁXIMA ESTIMADA PARA EL LOGRO DEL',
        f"APRENDIZAJE (Horas) {competencia['horas']} horas",
        'DENOMINACIÓN',
        *competencia['resultados'],
        '4.6 CONOCIMIENTOS',
        '4.6.1 CONOCIMIENTOS DE PROCESO',
        *(competencia.get('conocimientos_proceso') or ['* CONOCIMIENTO DE EJEMPLO.']),
        '4.6.2 CONOCIMIENTOS DEL SABER',
        *(competencia.get('conocimientos_saber') or ['* SABER DE EJEMPLO.']),
        '4.7 CRITERIOS DE EVALUACIÓN',
        *(competencia.get('criterios_evaluacion') or ['* CRITERIO DE EJEMPLO.']),
        '4.8 PERFIL DEL INSTRUCTOR',
        '4.8.1 Requisitos Académicos:',
        competencia.get('requisitos_academicos', 'PROFESIONAL EN EL ÁREA.'),
        '4.8.2 Experiencia laboral y/o especialización:',
        competencia.get('experiencia', 'MÍNIMO 12 MESES.'),
    ]
    return lineas


def crear_programa_pdf(carpeta, competencias=None, horas_lectiva=1056, horas_productiva=864):
    """Genera el PDF de programa que espera ``parsear_programa``."""
    # Una lista vacía es intencional: sirve para probar el rechazo de un PDF
    # que no tiene la estructura del programa.
    competencias = COMPETENCIAS_EJEMPLO if competencias is None else competencias
    lineas = [
        'ANALISIS Y DESARROLLO DE SOFTWARE.',
        '1. INFORMACION BÁSICA DEL PROGRAMA DE FORMACION TITULADA',
        '1.2. Código',
        'Programa:',
        '228118',
        f'{horas_lectiva} horasEtapa Lectiva:',
        'Etapa Productiva:',
        f'Total: {horas_lectiva + horas_productiva} horas',
        f'{horas_productiva} horas',
    ]
    for competencia in competencias:
        lineas.extend(_lineas_competencia(competencia))

    ruta = Path(carpeta) / 'programa.pdf'
    lienzo = canvas.Canvas(str(ruta), pagesize=letter)
    alto = letter[1] - 40
    for linea in lineas:
        if alto < 40:
            lienzo.showPage()
            alto = letter[1] - 40
        lienzo.setFont('Helvetica', 9)
        lienzo.drawString(30, alto, linea)
        alto -= 12
    lienzo.save()
    return ruta
