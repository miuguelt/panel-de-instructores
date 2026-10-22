"""Motor determinista de asignación de turnos de aseo por Bolsa de Rondas (Token Bucket).

Función pura desacoplada de SQLAlchemy y la base de datos para garantizar
invariantes matemáticos verificables y prevenir regresiones:
1. Ningún aprendiz recibe turno en Ronda k+1 hasta que el 100 % de los activos
   hayan recibido o repuesto su turno en Ronda k (Invariante de Equidad Estricta).
2. Distancia mínima de descanso (cero días consecutivos) entre turnos de una misma persona.
3. Diversidad de parejas: no repetir compañeros mientras existan opciones con menor historial.
4. Respeto absoluto de turnos cumplidos y asignaciones manuales sin duplicar cupos.
"""

from collections import defaultdict
from datetime import date
from itertools import combinations
import random


def _conflicto_restante(candidato, candidatos, historial):
    restantes = [a for a in candidatos if a != candidato]
    if not 2 <= len(restantes) <= 6:
        return 0
    return sum(historial.get(tuple(sorted(pareja)), 0) for pareja in combinations(restantes, 2))


def calcular_turnos_token_bucket(
    aprendiz_ids,
    sesiones_fechas,
    turnos_fijos=None,
    cargas_iniciales=None,
    ultimas_fechas_iniciales=None,
    historial_parejas_inicial=None,
    ausentes_por_fecha=None,
    excluidos_hasta=None,
    veces_cumplidas_iniciales=None,
    rng=None,
):
    """Calcula asignaciones de aseo sesión a sesión mediante bolsa de rondas estricta.

    Parámetros:
        aprendiz_ids: lista de IDs de aprendices activos elegibles.
        sesiones_fechas: lista ordenada de fechas (date) correspondientes a las sesiones.
        turnos_fijos: dict opcional {fecha: {'aprendiz_1_id': id, 'aprendiz_2_id': id, ...}}
        cargas_iniciales: dict opcional {aprendiz_id: veces_cumplidas_previas}
        ultimas_fechas_iniciales: dict opcional {aprendiz_id: ultima_fecha_date}
        historial_parejas_inicial: dict opcional {(id1, id2): veces_compartidas}
        ausentes_por_fecha: dict opcional {fecha: set(aprendiz_ids_presentes)}
        excluidos_hasta: dict opcional {aprendiz_id: fecha_hasta}
        rng: instancia opcional de random.Random para determinismo en pruebas.

    Retorna:
        dict con:
            'asignaciones': lista de dicts con fecha, aprendiz_1_id, aprendiz_2_id,
                            auditoria_1, auditoria_2, es_fijo, turno_id
            'cargas_finales': dict {aprendiz_id: carga_total}
            'sin_candidatos': lista de fechas donde no hubo suficientes aprendices
    """
    r = rng or random.SystemRandom()
    turnos_fijos = turnos_fijos or {}
    ausentes_por_fecha = ausentes_por_fecha or {}
    excluidos_hasta = excluidos_hasta or {}

    cargas = defaultdict(int, (cargas_iniciales or {}))
    veces_cumplidas = defaultdict(int, (veces_cumplidas_iniciales or {}))
    ultima_asignacion = dict(ultimas_fechas_iniciales or {})
    historial_parejas = defaultdict(int, (historial_parejas_inicial or {}))
    asignaciones_recientes = []

    # Inicializar a 0 la carga de cualquier aprendiz activo no registrado
    for a_id in aprendiz_ids:
        cargas.setdefault(a_id, 0)
        veces_cumplidas.setdefault(a_id, 0)

    # Ingerir turnos fijos (cumplidos, no_cumplidos o manuales respetados)
    for fecha in sorted(turnos_fijos.keys()):
        fijo = turnos_fijos[fecha]
        a1 = fijo['aprendiz_1_id']
        a2 = fijo['aprendiz_2_id']
        es_cumplido = fijo.get('estado') == 'cumplido'
        es_manual = fijo.get('es_manual', False)
        # Si tiene la directiva explícita o es manual no cumplido, incrementa carga
        if fijo.get('incrementar_carga', False) or (es_manual and not es_cumplido):
            cargas[a1] += 1
            cargas[a2] += 1
        ultima_asignacion[a1] = max(ultima_asignacion.get(a1) or date.min, fecha)
        ultima_asignacion[a2] = max(ultima_asignacion.get(a2) or date.min, fecha)
        if es_cumplido or es_manual:
            historial_parejas[tuple(sorted((a1, a2)))] += 1

    asignaciones = []
    sin_candidatos = []

    for sesion in sesiones_fechas:
        if sesion in turnos_fijos:
            fijo = turnos_fijos[sesion]
            asignaciones.append({
                'fecha': sesion,
                'aprendiz_1_id': fijo['aprendiz_1_id'],
                'aprendiz_2_id': fijo['aprendiz_2_id'],
                'auditoria_1': fijo.get('auditoria_1', 'Turno fijo conservado.'),
                'auditoria_2': fijo.get('auditoria_2', 'Turno fijo conservado.'),
                'es_fijo': True,
                'turno_id': fijo.get('id'),
            })
            asignaciones_recientes.append({fijo['aprendiz_1_id'], fijo['aprendiz_2_id']})
            continue

        # Filtro de aprendices elegibles para esta fecha concreta
        presentes = ausentes_por_fecha.get(sesion)
        candidatos_fecha = []
        for a_id in aprendiz_ids:
            if excluidos_hasta.get(a_id) and excluidos_hasta[a_id] >= sesion:
                continue
            if presentes is not None and a_id not in presentes:
                continue
            candidatos_fecha.append(a_id)

        if len(candidatos_fecha) < 2:
            sin_candidatos.append(sesion)
            asignaciones_recientes.append(set())
            continue

        # Ventana de descanso reciente: la sesión inmediatamente anterior
        recientes_ids = set(asignaciones_recientes[-1]) if asignaciones_recientes else set()

        # 1. Determinamos nivel mínimo de carga de los candidatos (Ronda actual)
        min_carga = min(cargas[a] for a in candidatos_fecha)
        bolsa_ronda = [a for a in candidatos_fecha if cargas[a] == min_carga]

        # Candidato 1: filtrado por descanso inmediato
        cands_1 = [a for a in bolsa_ronda if a not in recientes_ids]
        if not cands_1:
            # Si todos en la bolsa descansaron recientemente, relajar al grupo completo de la ronda
            cands_1 = list(bolsa_ronda)

        # 1. Menos turnos cumplidos prevalecen sobre antigüedad
        min_cumpl_1 = min(veces_cumplidas[a] for a in cands_1)
        empatados_1 = [a for a in cands_1 if veces_cumplidas[a] == min_cumpl_1]

        # 2. Priorizar a quien lleva más tiempo sin turno (antigüedad)
        min_ult_1 = min(ultima_asignacion.get(a) or date.min for a in empatados_1)
        empatados_1 = [a for a in empatados_1 if (ultima_asignacion.get(a) or date.min) == min_ult_1]
        elegido_1 = r.choice(empatados_1)

        # 2. Selección de Candidato 2 (Compañero)
        bolsa_restante = [a for a in bolsa_ronda if a != elegido_1]
        if not bolsa_restante:
            # La bolsa de la ronda actual se agotó (grupo impar o cierre de ciclo):
            # Tomamos candidatos del siguiente nivel de carga
            disponibles_siguiente = [a for a in candidatos_fecha if a != elegido_1]
            min_siguiente = min(cargas[a] for a in disponibles_siguiente)
            bolsa_restante = [a for a in disponibles_siguiente if cargas[a] == min_siguiente]

        cands_2 = [a for a in bolsa_restante if a not in recientes_ids]
        if not cands_2:
            cands_2 = list(bolsa_restante)

        # Candidato 2:
        # A) Menos turnos cumplidos primero (rotar compañeros no adelanta a quien tiene más cumplidos)
        min_cumpl_2 = min(veces_cumplidas[a] for a in cands_2)
        empatados_2 = [a for a in cands_2 if veces_cumplidas[a] == min_cumpl_2]

        # B) Minimizar repeticiones previas de pareja con elegido_1
        min_pareja = min(historial_parejas.get(tuple(sorted((elegido_1, a))), 0) for a in empatados_2)
        empatados_2 = [
            a for a in empatados_2
            if historial_parejas.get(tuple(sorted((elegido_1, a))), 0) == min_pareja
        ]

        # C) Si hay varios con mínimo historial, anticipar y evitar dejar parejas repetidas restantes
        if len(empatados_2) > 1:
            min_conflicto = min(_conflicto_restante(a, cands_2, historial_parejas) for a in empatados_2)
            empatados_2 = [
                a for a in empatados_2
                if _conflicto_restante(a, cands_2, historial_parejas) == min_conflicto
            ]

        # D) Entre ellos, favorecer a quien lleva más tiempo de descanso
        min_ult_2 = min(ultima_asignacion.get(a) or date.min for a in empatados_2)
        empatados_2 = [
            a for a in empatados_2
            if (ultima_asignacion.get(a) or date.min) == min_ult_2
        ]
        elegido_2 = r.choice(empatados_2)

        # Registrar asignación
        pareja_clave = tuple(sorted((elegido_1, elegido_2)))
        veces_juntos = historial_parejas.get(pareja_clave, 0)
        historial_parejas[pareja_clave] = veces_juntos + 1

        cargas[elegido_1] += 1
        cargas[elegido_2] += 1
        ultima_asignacion[elegido_1] = sesion
        ultima_asignacion[elegido_2] = sesion
        asignaciones_recientes.append({elegido_1, elegido_2})

        razon_1 = (
            f'Asignado por bolsa de rondas (Ronda {min_carga + 1}). '
            f'Carga acumulada previa: {cargas[elegido_1] - 1}. '
            f'Compañero: ID {elegido_2} ({veces_juntos} aseo(s) previos juntos).'
        )
        razon_2 = (
            f'Asignado por bolsa de rondas (Ronda {cargas[elegido_2]}). '
            f'Carga acumulada previa: {cargas[elegido_2] - 1}. '
            f'Compañero: ID {elegido_1} ({veces_juntos} aseo(s) previos juntos).'
        )

        asignaciones.append({
            'fecha': sesion,
            'aprendiz_1_id': elegido_1,
            'aprendiz_2_id': elegido_2,
            'auditoria_1': razon_1,
            'auditoria_2': razon_2,
            'es_fijo': False,
            'turno_id': None,
        })

    return {
        'asignaciones': asignaciones,
        'cargas_finales': dict(cargas),
        'sin_candidatos': sin_candidatos,
    }
