"""Diagnóstico pedagógico y ruta de recuperación para la curva de rendimiento."""

from __future__ import annotations

from typing import Any, Dict, List


def generar_diagnostico_curva(
    supera_meta: bool,
    pt_actual: float,
    distancia_meta: float,
    dif: float,
    mejor_pt: float,
    tendencia: str,
) -> str:
    """Genera diagnóstico formativo empático en español de Colombia."""
    if supera_meta:
        return (
            f"Mantienes un promedio sobresaliente ({pt_actual} pts), superando la meta formativa en +{distancia_meta} pts. "
            "Tu constancia en asistencias y evidencias consolida tu perfil profesional."
        )
    if dif <= -10.0 and mejor_pt >= 70.0:
        return (
            f"Tu puntaje tuvo una variación de {dif} pts en la medición más reciente. Esto suele asociarse "
            "a la apertura de un nuevo corte evaluativo o evidencias pendientes por calificar. "
            f"Tu récord histórico de {mejor_pt} pts demuestra tu capacidad técnica para recuperarte rápidamente."
        )
    if not supera_meta:
        return (
            f"Te encuentras a {abs(distancia_meta)} pts de la meta aprobatoria del 70%. Al presentar tus "
            "evidencias pendientes y mantener tu asistencia regular, podrás volver a la zona aprobatoria."
        )
    return (
        f"Tu curva registra un promedio de {pt_actual} pts con tendencia {tendencia}. "
        "Continúa participando en las actividades de la ficha para fortalecer tu proceso."
    )


def obtener_ruta_recuperacion_formativa() -> List[Dict[str, str]]:
    """Devuelve los pasos accionables de la ruta de rescate y crecimiento."""
    return [
        {
            'paso': '1. Cargar evidencias pendientes',
            'detalle': 'Sube las evidencias programadas para sumar puntos directos a tu promedio.',
            'icono': '📋',
        },
        {
            'paso': '2. Asistencia al 100%',
            'detalle': 'La presencia puntual en cada sesión formativa garantiza tu puntaje base.',
            'icono': '⏱️',
        },
        {
            'paso': '3. Desafíos y retos de escuadrón',
            'detalle': 'Participa activamente en los retos grupales para ganar medallas de mérito formativo.',
            'icono': '🏆',
        },
    ]
