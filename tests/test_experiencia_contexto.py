"""El inicio guía al aprendiz con sus entregas y resultados reales."""

from datetime import datetime, timezone
from types import SimpleNamespace as Objeto

from app.features.experiencia_aprendiz.context import construir_experiencia, estado_evidencia


AHORA = datetime(2026, 10, 7, 15)
PREFERENCIAS = {'weeklyGoal': 2, 'notificationMode': 'all', 'rankingVisible': True,
                'reducedMotion': False, 'density': 'comfortable', 'resume': None}


def item(identificador=1, estado='pendiente', fecha=None, entrega=None, aula=False, grupo=None):
    return {'tarea': Objeto(id=identificador, titulo=f'Actividad {identificador}',
                           es_actividad_clase=aula),
            'estado': estado, 'limite_efectivo': fecha, 'entrega': entrega, 'grupo': grupo}


def entrega(estado='pendiente', fecha=AHORA, feedback=None, aula=False):
    return Objeto(estado_revision=estado, fecha_entrega=fecha, calificada=estado != 'pendiente',
                  feedback=feedback, registrada_por_instructor=aula)


def construir(tareas=None, preferencias=None, grupos=None, grupo=None, competencias=None, hitos=None):
    return construir_experiencia(tareas or [], grupos or [], {'aprobados': 3, 'total': 5},
                                 competencias or [], grupo, preferencias or PREFERENCIAS, 2,
                                 hitos or [], ahora=AHORA)


def test_correccion_tiene_prioridad_y_orienta_al_feedback_sin_confundir_con_juicio():
    corregir = item(2, 'correccion', entrega=entrega('rechazada', feedback='Explica la decisión.'))
    datos = construir([item(1, fecha=datetime(2026, 10, 8)), corregir])
    assert datos['next_action']['taskId'] == 2
    assert 'comentarios' in datos['next_action']['reason']
    assert datos['evidence'] == {'submitted': 1, 'review': 0, 'changes': 1, 'approved': 0}
    assert datos['progress'] == {'approved': 3, 'total': 5, 'pct': 60}


def test_prioriza_plazo_efectivo_y_resuelve_empate_por_id():
    datos = construir([item(4), item(3, fecha=datetime(2026, 10, 10)),
                       item(2, fecha=datetime(2026, 10, 8)), item(1, fecha=datetime(2026, 10, 8))])
    assert datos['next_action']['taskId'] == 1
    assert '07/10/2026' in datos['next_action']['reason']  # UTC se muestra en Colombia.


def test_actividad_en_clase_indica_consultar_sin_inventar_subida():
    datos = construir([item(aula=True)])
    assert datos['next_action']['button'] == 'Consultar actividad'
    assert 'instructor' in datos['next_action']['reason']
    assert datos['weekly']['count'] == 0


def test_feedback_y_espera_son_acciones_distintas_y_vacio_tiene_orientacion():
    revisada = item(2, 'entregada', entrega=entrega('aprobada', feedback='Buen avance.'))
    datos = construir([revisada])
    assert datos['next_action']['button'] == 'Leer comentarios'
    assert datos['evidence']['approved'] == 1
    pendiente = construir([item(3, 'entregada', entrega=entrega())])
    assert pendiente['next_action']['button'] == 'Consultar entrega'
    assert 'revisión' in pendiente['next_action']['reason']
    reenviada = construir([item(4, 'entregada', entrega=entrega(feedback='Comentario anterior.'))])
    assert reenviada['next_action']['button'] == 'Consultar entrega'
    vacio = construir()
    assert vacio['next_action']['tab'] == 'juicios'
    assert vacio['next_action']['taskId'] is None


def test_semana_colombiana_excluye_futuro_aula_y_limite_anterior():
    tareas = [item(1, 'entregada', entrega=entrega(fecha=datetime(2026, 10, 5, 5))),
              item(2, 'entregada', entrega=entrega(fecha=datetime(2026, 10, 5, 4, 59))),
              item(3, 'entregada', entrega=entrega(fecha=datetime(2026, 10, 8))),
              item(4, 'entregada', entrega=entrega(aula=True)),
              item(5, 'correccion', entrega=entrega('rechazada'))]
    datos = construir(tareas)
    assert datos['weekly']['count'] == 2
    assert datos['weekly']['percent'] == 100
    assert datos['weekly']['start'] == '2026-10-05'
    assert datos['weekly']['end'] == '2026-10-11'
    assert construir(tareas, {**PREFERENCIAS, 'weeklyGoal': 0})['weekly']['percent'] == 0
    assert construir(tareas, {**PREFERENCIAS, 'weeklyGoal': 1})['weekly']['percent'] == 100
    assert construir(tareas[:1], {**PREFERENCIAS, 'weeklyGoal': 8})['weekly']['percent'] == 13


def test_cooperacion_se_limita_al_grupo_actual_y_no_inventa_retos():
    grupo = Objeto(id=1, nombre='Equipo Uno')
    otro = Objeto(id=2, nombre='Equipo Dos')
    trabajos = [item(10, 'entregada', entrega=entrega(), grupo=grupo),
                item(11, 'correccion', entrega=entrega('rechazada'), grupo=grupo),
                item(12, 'entregada', entrega=entrega(), grupo=otro)]
    datos = construir(grupos=trabajos, grupo=grupo)
    assert datos['team'] == {'name': 'Equipo Uno', 'completed': 1, 'total': 2, 'pct': 50}
    assert datos['next_action']['tab'] == 'grupo'
    assert datos['next_action']['taskId'] is None
    assert construir(grupo=grupo)['team'] is None


def test_hitos_son_permanentes_competencias_tienen_progreso_y_resume_invalido_se_descarta():
    competencias = [{'nombre': 'Programación', 'aprobados': 2, 'total': 3},
                    {'nombre': 'Sin resultados', 'aprobados': 0, 'total': 0}]
    prefs = {**PREFERENCIAS, 'resume': {'tab': 'evidencias', 'taskId': 999}}
    datos = construir(competencias=competencias, preferencias=prefs, hitos=['primera_entrega'])
    assert datos['milestones'][0]['title'] == 'Primer paso'
    assert datos['competencies'][0]['pct'] == 67
    assert datos['competencies'][1]['pct'] == 0
    assert datos['preferences']['resume'] is None
    assert prefs['resume']['taskId'] == 999
    validos = construir([item(1)], {**PREFERENCIAS, 'resume': {'tab': 'evidencias', 'taskId': 1}})
    assert validos['preferences']['resume']['taskId'] == 1
    assert construir(preferencias={**PREFERENCIAS, 'resume': {'tab': 'grupo', 'taskId': None}})['preferences']['resume']['tab'] == 'grupo'


def test_estados_de_evidencia_cubren_todos_los_resultados_observables():
    assert estado_evidencia(item())['title'] == 'Por entregar'
    assert estado_evidencia(item(estado='vencida'))['title'] == 'Plazo vencido'
    assert estado_evidencia(item(aula=True))['title'] == 'Actividad en clase'
    assert estado_evidencia(item(entrega=entrega()))['title'] == 'Recibida · En revisión'
    assert estado_evidencia(item(entrega=entrega('rechazada')))['title'] == 'Requiere ajustes'
    assert estado_evidencia(item(entrega=entrega('aprobada')))['title'] == 'Revisión aprobada'
    assert estado_evidencia(item(aula=True, entrega=entrega('aprobada', aula=True)))['title'] == 'Cumplimiento en clase'
    assert estado_evidencia(item(entrega=entrega('pendiente', feedback='Comentario preliminar')))['status'] == 'review'
    assert estado_evidencia(item(estado='retraso', entrega=entrega()))['status'] == 'review'


def test_fechas_con_zona_y_entregas_sin_fecha_no_distorsionan_la_meta():
    fechas = [item(1, 'entregada', entrega=entrega(fecha=AHORA.replace(tzinfo=timezone.utc))),
              item(2, 'entregada', entrega=entrega(fecha=None))]
    assert construir(fechas)['weekly']['count'] == 1
