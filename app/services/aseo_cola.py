"""Prioridad compartida del calendario, las suplencias y las reposiciones de aseo."""

import random
from datetime import date
from itertools import combinations


def _fecha_referencia(contador, ultima_programada):
    fechas = [fecha for fecha in (contador.ultima_vez_aseo, ultima_programada) if fecha]
    return max(fechas, default=date.min)


def _conflicto_restante(candidato, candidatos, historial):
    restantes = [aprendiz.id for aprendiz in candidatos if aprendiz.id != candidato.id]
    if not 2 <= len(restantes) <= 6:
        return 0
    return sum(historial.get(tuple(sorted(pareja)), 0) for pareja in combinations(restantes, 2))


def _desempatar_parejas(candidatos, companero_id, historial, anticipar):
    repeticiones = {
        aprendiz.id: historial.get(tuple(sorted((companero_id, aprendiz.id))), 0)
        for aprendiz in candidatos
    }
    minimo = min(repeticiones.values())
    empatados = [aprendiz for aprendiz in candidatos if repeticiones[aprendiz.id] == minimo]
    if anticipar and len(empatados) > 1:
        conflictos = {
            aprendiz.id: _conflicto_restante(aprendiz, candidatos, historial)
            for aprendiz in empatados
        }
        minimo = min(conflictos.values())
        empatados = [aprendiz for aprendiz in empatados if conflictos[aprendiz.id] == minimo]
    return empatados


def elegir_por_cola_justa(
    candidatos,
    contadores,
    cargas_prog,
    ultima_prog,
    rng=None,
    companero_id=None,
    historial_parejas=None,
    excluir_ids=None,
    evitar_ids=None,
    anticipar_parejas=False,
):
    """Elige por carga, descanso y cumplimientos antes de rotar parejas o sortear."""
    if not candidatos:
        return None
    disponibles = [
        aprendiz for aprendiz in candidatos if not excluir_ids or aprendiz.id not in excluir_ids
    ] or list(candidatos)
    prioridades = {
        aprendiz.id: (
            contadores[aprendiz.id].veces_aseo + cargas_prog.get(aprendiz.id, 0),
            aprendiz.id in (evitar_ids or ()),
            contadores[aprendiz.id].veces_aseo,
        )
        for aprendiz in disponibles
    }
    prioridad_minima = min(prioridades.values())
    empatados = [
        aprendiz for aprendiz in disponibles if prioridades[aprendiz.id] == prioridad_minima
    ]
    if companero_id is not None and historial_parejas is not None and len(empatados) > 1:
        empatados = _desempatar_parejas(
            empatados, companero_id, historial_parejas, anticipar_parejas,
        )
    fechas = {
        aprendiz.id: _fecha_referencia(contadores[aprendiz.id], ultima_prog.get(aprendiz.id))
        for aprendiz in empatados
    }
    fecha_minima = min(fechas.values())
    empatados = [aprendiz for aprendiz in empatados if fechas[aprendiz.id] == fecha_minima]
    return (rng or random.SystemRandom()).choice(empatados)


def razon_eleccion(
    contador,
    programados,
    promedio,
    solo_asistentes,
    companero_nombre=None,
    veces_juntos=0,
):
    """Explica la carga observada y el orden de los criterios de asignación."""
    carga = contador.veces_aseo + programados
    partes = [
        f'Te eligió la cola justa porque tu carga era de {carga}: '
        f'{contador.veces_aseo} turno(s) cumplido(s) y {programados} programado(s).',
        'Con la misma carga se procura evitar sesiones consecutivas y se prioriza '
        'a quien tiene menos turnos cumplidos, antes de rotar compañeros.',
        f'El promedio de turnos cumplidos del grupo elegible era {promedio:.1f}.',
    ]
    if contador.ultima_vez_aseo:
        partes.append(f'Tu último aseo cumplido fue el {contador.ultima_vez_aseo.strftime("%d/%m/%Y")}.')
    else:
        partes.append('Todavía no has cumplido un turno de aseo.')
    if companero_nombre:
        partes.append(
            f'Tu compañero es {companero_nombre}; habían compartido '
            f'{veces_juntos} turno(s) antes de esta asignación.'
        )
    partes.append(
        'Entre personas con la misma prioridad se rotan compañeros y se favorece '
        'a quien lleva más tiempo sin turno. Si el empate continúa, se realiza un sorteo.'
    )
    if solo_asistentes:
        partes.append('La asistencia registrada para esa sesión te marcaba como presente.')
    return ' '.join(partes)
