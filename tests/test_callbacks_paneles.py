"""Orden y consolidación de competencias en reportes HTTP de aprendices."""

from datetime import datetime
from html import unescape
from io import BytesIO
import re

import pytest
from pypdf import PdfReader

from app import db
from app.models import JuicioEvaluativo
from tests.test_auditoria_rutas import entorno, ingresar, ingresar_aprendiz


@pytest.fixture
def competencias_persistidas(entorno):
    app, cliente, instructor, ficha, _, aprendiz, otro_aprendiz, _ = entorno
    registros = [
        ('tecnica', 'Zeta técnica', 'APROBADO', datetime(2026, 9, 20)),
        ('ingles', 'Zeta inglés', 'POR EVALUAR', datetime(2026, 9, 20)),
        ('transversal', 'Zeta transversal', 'AUN NO APROBADO', datetime(2026, 9, 20)),
        ('tecnica', 'Alfa técnica', 'APROBADO', datetime(2026, 9, 10)),
        ('ingles', 'Alfa inglés', 'APROBADO', datetime(2026, 9, 10)),
        ('transversal', 'Alfa transversal', 'APROBADO', datetime(2026, 9, 10)),
        ('tecnica', 'Alfa técnica', 'POR EVALUAR', None),
    ]
    for indice, (tipo, competencia, juicio, fecha) in enumerate(registros, start=1):
        db.session.add(JuicioEvaluativo(
            ficha_id=ficha.id, aprendiz_id=aprendiz.id, competencia=competencia,
            tipo_competencia=tipo, resultado_aprendizaje=f'Resultado de aprendizaje {indice}',
            juicio=juicio, fecha_juicio=fecha, funcionario_registro=instructor.nombre,
        ))
    db.session.add(JuicioEvaluativo(
        ficha_id=ficha.id, aprendiz_id=otro_aprendiz.id,
        competencia='Competencia de otro aprendiz', tipo_competencia='tecnica',
        resultado_aprendizaje='Resultado que no corresponde a este reporte', juicio='APROBADO',
    ))
    db.session.commit()
    return cliente, instructor, ficha, aprendiz


def texto_visible(html):
    return ' '.join(unescape(re.sub(r'<[^>]*>', ' ', html)).split())


def test_historial_ordena_competencias_por_nombre_y_conserva_juicios(competencias_persistidas):
    cliente, instructor, ficha, aprendiz = competencias_persistidas
    ingresar(cliente, instructor)

    respuesta = cliente.get(f'/instructor/fichas/{ficha.id}/aprendices/{aprendiz.id}/historial')

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    tarjetas = re.findall(r'<article class="report-competency-card">(.*?)</article>', html, re.DOTALL)
    nombres = [unescape(re.search(r'<h4>(.*?)</h4>', tarjeta, re.DOTALL).group(1))
               for tarjeta in tarjetas]
    assert nombres == ['Alfa técnica', 'Zeta técnica', 'Alfa transversal',
                       'Zeta transversal', 'Alfa inglés', 'Zeta inglés']
    contenido = dict(zip(nombres, [texto_visible(tarjeta) for tarjeta in tarjetas]))
    assert '1/2 RAPs' in contenido['Alfa técnica']
    assert '50% avance' in contenido['Alfa técnica']
    assert 'En progreso' in contenido['Alfa técnica']
    assert 'Resultado de aprendizaje 4' in contenido['Alfa técnica']
    assert 'Resultado de aprendizaje 7' in contenido['Alfa técnica']
    assert 'Sin fecha' in contenido['Alfa técnica']
    assert '1/1 RAPs' in contenido['Zeta técnica']
    assert 'Completada' in contenido['Zeta técnica']
    assert '0/1 RAPs' in contenido['Zeta transversal']
    assert 'Pendiente' in contenido['Zeta transversal']
    assert 'Competencia de otro aprendiz' not in html


def test_reporte_pdf_ordena_competencias_por_tipo_y_nombre(competencias_persistidas):
    cliente, _, ficha, aprendiz = competencias_persistidas
    ingresar_aprendiz(cliente, aprendiz)

    respuesta = cliente.get(f'/aprendiz/{ficha.id}/descargar-reporte')

    assert respuesta.status_code == 200
    assert respuesta.mimetype == 'application/pdf'
    assert f'reporte_{ficha.codigo}.pdf' in respuesta.headers['Content-Disposition']
    lector = PdfReader(BytesIO(respuesta.data))
    texto = '\n'.join(pagina.extract_text() for pagina in lector.pages)
    nombres = ['Alfa inglés', 'Zeta inglés', 'Alfa técnica', 'Zeta técnica',
               'Alfa transversal', 'Zeta transversal']
    posiciones = [texto.index(nombre) for nombre in nombres]
    assert posiciones == sorted(posiciones)
    assert all(texto.count(nombre) == 1 for nombre in nombres)
    assert '57%' in texto
    assert '1/2 RAPs (50%)' in texto
    assert 'Resultado de aprendizaje 7' in texto
    assert 'POR EVALUAR' in texto
    assert 'AUN NO APROBADO' in texto
    assert 'Competencia de otro aprendiz' not in texto
    assert 'Resultado que no corresponde a este reporte' not in texto
