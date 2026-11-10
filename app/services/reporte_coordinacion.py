"""Reporte en Excel para la coordinación académica.

Tres hojas: resumen por ficha, remisiones a comité (con fundamento y página) y
aplazamientos con fecha límite de reintegro. Usa los mismos servicios que las vistas,
para que el reporte nunca contradiga lo que el instructor ve en pantalla.
"""

import io
from collections import Counter
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.models.alertas import Alerta, LlamadoAtencion, PlanMejoramiento
from app.models.aprendiz import Aprendiz, etiqueta_estado
from app.services.comite_productiva import ACCION_COMITE, analizar_ficha
from app.services.novedades import (
    aplazamiento_vigente, cargar_datos_ficha, evaluar_reintegro, fechas_reintegro,
    reintegro_tardio, tiene_reintegro, ultimo_aplazamiento,
)

COLUMNAS_RESUMEN = (
    'Ficha', 'Programa', 'Fecha fin', 'Aprendices', 'Distribución por estado',
    'Casos activos', 'Casos escalados a comité', 'Llamados de atención', 'Planes vigentes',
    'Aplazamientos vigentes', 'Etapa productiva avalada', 'Remisiones por etapa productiva',
    'Cancelaciones administrativas', 'Remisiones por reintegro',
)
COLUMNAS_REMISIONES = (
    'Ficha', 'Documento', 'Aprendiz', 'Estado', 'Causal', 'Acción recomendada',
    'Motivo', 'Fundamento principal', 'Página PDF',
)
COLUMNAS_NOVEDADES = (
    'Ficha', 'Documento', 'Aprendiz', 'Causa', 'Inicio', 'Fin del aplazamiento',
    'Avisar desde', 'Límite para pedir reintegro', 'Reintegro tardío',
)
VERDE_SENA = '39A900'


def _datos_ficha(ficha, hoy):
    aprendices = Aprendiz.query.filter_by(ficha_id=ficha.id).order_by(
        Aprendiz.apellidos, Aprendiz.nombre).all()
    etapas, novedades = cargar_datos_ficha(ficha.id)
    productiva = analizar_ficha(ficha, aprendices, hoy, etapas, novedades)
    reintegros = []
    for aprendiz in aprendices:
        recomendacion = evaluar_reintegro(aprendiz, novedades.get(aprendiz.id, []), hoy)
        if recomendacion and recomendacion['nivel'] == 'roja':
            reintegros.append((aprendiz, recomendacion))
    alertas = Alerta.query.filter(
        Alerta.ficha_id == ficha.id, Alerta.aprendiz_id.isnot(None),
        Alerta.estado.in_(['activa', 'escalada_comite']),
    ).all()
    return {
        'aprendices': aprendices, 'etapas': etapas, 'novedades': novedades,
        'productiva': productiva, 'reintegros': reintegros,
        'casos_activos': len({a.aprendiz_id for a in alertas}),
        'escalados': len({a.aprendiz_id for a in alertas if a.estado == 'escalada_comite'}),
        # Los llamados anulados se conservan en el expediente, pero no cuentan.
        'llamados': LlamadoAtencion.query.filter_by(ficha_id=ficha.id).filter(
            LlamadoAtencion.anulado_en.is_(None)).count(),
        'planes': PlanMejoramiento.query.filter_by(ficha_id=ficha.id, estado='pendiente').count(),
    }


def fila_resumen(ficha, datos, hoy):
    estados = Counter(etiqueta_estado(a.estado) for a in datos['aprendices'])
    vigentes = sum(1 for lista in datos['novedades'].values() if aplazamiento_vigente(lista, hoy))
    return (
        ficha.codigo, ficha.nombre_programa,
        ficha.fecha_fin.strftime('%d/%m/%Y') if ficha.fecha_fin else 'Sin fecha',
        len(datos['aprendices']),
        ', '.join(f'{estado}: {total}' for estado, total in sorted(estados.items())),
        datos['casos_activos'], datos['escalados'], datos['llamados'], datos['planes'], vigentes,
        sum(1 for e in datos['etapas'].values() if e.planeacion_avalada),
        sum(1 for r in datos['productiva'] if r['accion'] == ACCION_COMITE),
        sum(1 for r in datos['productiva'] if r['accion'] != ACCION_COMITE),
        len(datos['reintegros']),
    )


def filas_remisiones(ficha, datos):
    filas = []
    for r in datos['productiva']:
        principal = r['fundamentos'][0]
        accion = ('Remitir a comité' if r['accion'] == ACCION_COMITE
                  else 'Recomendación: cancelación por vía administrativa')
        filas.append((ficha.codigo, r['documento'], r['nombre'], r['estado_etiqueta'],
                      'Etapa productiva no culminada', accion, r['motivo'],
                      principal['referencia'], principal['pagina']))
    for aprendiz, r in datos['reintegros']:
        principal = r['fundamentos'][0]
        filas.append((ficha.codigo, aprendiz.documento, aprendiz.nombre_completo,
                      etiqueta_estado(aprendiz.estado), 'Reintegro no gestionado',
                      'Remitir a comité', r['motivo'], principal['referencia'], principal['pagina']))
    return filas


def filas_novedades(ficha, datos):
    from app.models.novedades import CAUSAS_APLAZAMIENTO

    por_id = {a.id: a for a in datos['aprendices']}
    filas = []
    for aprendiz_id, lista in datos['novedades'].items():
        aplazamiento = ultimo_aplazamiento(lista)
        # Quien ya pidió el reintegro a tiempo no tiene una novedad pendiente.
        if not aplazamiento or aprendiz_id not in por_id or tiene_reintegro(lista, aplazamiento):
            continue
        aprendiz = por_id[aprendiz_id]
        fechas = fechas_reintegro(aplazamiento)
        filas.append((
            ficha.codigo, aprendiz.documento, aprendiz.nombre_completo,
            CAUSAS_APLAZAMIENTO.get(aplazamiento.causa, aplazamiento.causa or ''),
            aplazamiento.fecha_inicio.strftime('%d/%m/%Y') if aplazamiento.fecha_inicio else '',
            fechas['fin'].strftime('%d/%m/%Y'), fechas['aviso'].strftime('%d/%m/%Y'),
            fechas['limite'].strftime('%d/%m/%Y'),
            'Sí' if reintegro_tardio(lista, aplazamiento) else 'No',
        ))
    return filas


def _hoja(libro, titulo, columnas, filas, primera=False):
    hoja = libro.active if primera else libro.create_sheet()
    hoja.title = titulo
    hoja.append(columnas)
    for celda in hoja[1]:
        celda.font = Font(bold=True, color='FFFFFF')
        celda.fill = PatternFill('solid', fgColor=VERDE_SENA)
        celda.alignment = Alignment(wrap_text=True, vertical='top')
    for fila in filas:
        hoja.append(fila)
    for indice, columna in enumerate(columnas, start=1):
        largo = max([len(str(columna))] + [len(str(f[indice - 1])) for f in filas])
        hoja.column_dimensions[get_column_letter(indice)].width = min(max(largo + 2, 12), 60)
    hoja.freeze_panes = 'A2'
    return hoja


def construir_reporte(fichas, hoy=None):
    """Bytes de un libro .xlsx con el estado de las fichas indicadas."""
    hoy = hoy or date.today()
    resumen, remisiones, novedades = [], [], []
    for ficha in sorted(fichas, key=lambda f: f.codigo):
        datos = _datos_ficha(ficha, hoy)
        resumen.append(fila_resumen(ficha, datos, hoy))
        remisiones.extend(filas_remisiones(ficha, datos))
        novedades.extend(filas_novedades(ficha, datos))
    libro = Workbook()
    _hoja(libro, 'Resumen por ficha', COLUMNAS_RESUMEN, resumen, primera=True)
    _hoja(libro, 'Remisiones', COLUMNAS_REMISIONES, remisiones)
    _hoja(libro, 'Aplazamientos', COLUMNAS_NOVEDADES, novedades)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
