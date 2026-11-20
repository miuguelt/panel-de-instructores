"""Estado de la ficha para la primera pantalla de la planeación.

Reúne en un solo diccionario lo que un instructor o coordinador busca al
abrir la ficha: las fechas clave, la fase esperada frente a la real, el avance
en una sola escala y el próximo hito. Todo se deriva del calendario y del
seguimiento de fases ya calculados; cuando falta un dato se devuelve ``None``
para que la plantilla lo declare, nunca un valor por defecto.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.services.seguimiento_fases import DIAS_POR_MES


FECHAS_CLAVE = (
    ('inicio', 'Inicio de la formación'),
    ('fin_lectiva', 'Fin de la etapa lectiva'),
    ('inicio_productiva', 'Inicio de la etapa productiva'),
    ('fin', 'Fin de la ficha'),
)

TONOS_SEGUIMIENTO = {
    'atrasado': 'danger',
    'al_dia': 'success',
    'adelantado': 'success',
    'completado': 'success',
}


ZONA_BOGOTA = ZoneInfo('America/Bogota')


def fecha_local(momento):
    """Día en Colombia de un instante guardado en UTC (las columnas sin zona son UTC)."""
    if momento is None:
        return None
    if not isinstance(momento, datetime):
        return momento
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(ZONA_BOGOTA).date()


def _dias(fecha, hoy):
    return (fecha - hoy).days if fecha else None


def _estado_fecha(dias):
    if dias is None:
        return 'sin_fecha'
    if dias < 0:
        return 'pasada'
    if dias == 0:
        return 'hoy'
    return 'futura'


def _fechas(calendario, hoy):
    fechas = []
    for clave, etiqueta in FECHAS_CLAVE:
        fecha = calendario.get(clave)
        dias = _dias(fecha, hoy)
        fechas.append({
            'clave': clave,
            'etiqueta': etiqueta,
            'fecha': fecha,
            'dias': dias,
            'estado': _estado_fecha(dias),
        })
    return fechas


def _fase(fase, hoy):
    if not fase:
        return None
    inicio = fase.get('inicio')
    fin = fase.get('fin')
    resumen = {
        'nombre': fase.get('nombre'),
        'icono': fase.get('icono'),
        'inicio': inicio,
        'fin': fin,
        'momento': 'sin_fecha',
        'dias_restantes': None,
        'dias_para_inicio': None,
        'dias_desde_fin': None,
    }
    if inicio and hoy < inicio:
        resumen['momento'] = 'por_iniciar'
        resumen['dias_para_inicio'] = (inicio - hoy).days
    elif fin and hoy > fin:
        resumen['momento'] = 'terminada'
        resumen['dias_desde_fin'] = (hoy - fin).days
    elif fin:
        resumen['momento'] = 'en_curso'
        resumen['dias_restantes'] = (fin - hoy).days
    return resumen


def _avance(calendario, seguimiento):
    resultados = (seguimiento or {}).get('resultados') or {}
    tiempo = calendario.get('porcentaje_lectiva')
    tono = TONOS_SEGUIMIENTO.get((seguimiento or {}).get('estado'), 'info')
    if not resultados.get('total'):
        return {'tiempo': tiempo, 'evaluados': None, 'cerrados': None,
                'brecha_puntos': None, 'tono': tono}
    cerrados = resultados.get('porcentaje_aprobados')
    return {
        'tiempo': tiempo,
        'evaluados': resultados.get('porcentaje_evaluados'),
        'cerrados': cerrados,
        'brecha_puntos': round(tiempo - cerrados, 1),
        'tono': tono,
    }


def _sin_evaluar(seguimiento):
    resultados = (seguimiento or {}).get('resultados') or {}
    if not resultados.get('total'):
        return None
    return max(resultados['total'] - (resultados.get('evaluados') or 0), 0)


def _rap_por_semana(semanas, sin_evaluar):
    """RAP que habría que evaluar cada semana para terminar en la etapa lectiva."""
    if sin_evaluar is None:
        return None
    if not sin_evaluar:
        return 0
    if not semanas:
        return None
    return round(sin_evaluar / semanas, 1)


def _ritmo_semanal_actual(seguimiento):
    """Convierte el ritmo mensual medido en los últimos 180 días a semanas."""
    ritmo = ((seguimiento or {}).get('proyeccion') or {}).get('ritmo_mensual')
    if ritmo is None:
        return None
    return round(ritmo * 7 / DIAS_POR_MES, 1)


def _proximo_hito(calendario, fase_esperada, hoy):
    candidatos = []
    bloque = calendario.get('bloque_actual')
    if bloque and bloque.get('etapa') == 'lectiva':
        candidatos.append((f"Fin del trimestre {bloque.get('etiqueta')}", bloque.get('fin')))
    if fase_esperada:
        candidatos.append((f"Fin de la fase {fase_esperada['nombre']}", fase_esperada['fin']))
    candidatos.extend((etiqueta, calendario.get(clave)) for clave, etiqueta in FECHAS_CLAVE[1:])

    vigentes = [(fecha, orden, etiqueta) for orden, (etiqueta, fecha) in enumerate(candidatos)
                if fecha and fecha >= hoy]
    if not vigentes:
        return None
    fecha, _orden, etiqueta = min(vigentes)
    return {'etiqueta': etiqueta, 'fecha': fecha, 'dias': (fecha - hoy).days}


def construir_estado_ficha(calendario, seguimiento_fases, hoy=None):
    """Devuelve fechas, fase, avance y próximo hito de la ficha."""
    hoy = hoy or date.today()
    calendario = calendario or {}
    seguimiento = seguimiento_fases or {}
    fase_esperada = _fase(seguimiento.get('fase_esperada'), hoy)
    fase_real = _fase(seguimiento.get('fase_real'), hoy)
    fases_coinciden = bool(fase_esperada and fase_real and fase_esperada['nombre'] == fase_real['nombre'])

    if not calendario.get('configurado'):
        return {
            'disponible': False,
            'fechas': [],
            'dias_para_fin_ficha': None,
            'dias_para_productiva': None,
            'semanas_lectivas_restantes': None,
            'fase_esperada': fase_esperada,
            'fase_real': fase_real,
            'fases_coinciden': fases_coinciden,
            'avance': None,
            'rap_sin_evaluar': _sin_evaluar(seguimiento_fases),
            'rap_por_semana': None,
            'rap_por_semana_actual': _ritmo_semanal_actual(seguimiento_fases),
            'proximo_hito': None,
        }

    dias_restantes = calendario.get('dias_restantes_lectiva')
    semanas = round(dias_restantes / 7, 1) if dias_restantes is not None else None
    return {
        'disponible': True,
        'fechas': _fechas(calendario, hoy),
        'dias_para_fin_ficha': _dias(calendario.get('fin'), hoy),
        'dias_para_productiva': _dias(calendario.get('inicio_productiva'), hoy),
        'semanas_lectivas_restantes': semanas,
        'fase_esperada': fase_esperada,
        'fase_real': fase_real,
        'fases_coinciden': fases_coinciden,
        'avance': _avance(calendario, seguimiento_fases),
        'rap_sin_evaluar': _sin_evaluar(seguimiento_fases),
        'rap_por_semana': _rap_por_semana(semanas, _sin_evaluar(seguimiento_fases)),
        'rap_por_semana_actual': _ritmo_semanal_actual(seguimiento_fases),
        'proximo_hito': _proximo_hito(calendario, fase_esperada, hoy),
    }
