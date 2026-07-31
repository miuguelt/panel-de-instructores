from app.models.instructor import Instructor
from app.models.ficha import Ficha
from app.models.aprendiz import Aprendiz
from app.models.asistencia import SesionAsistencia, RegistroAsistencia
from app.models.tarea import Tarea, Entrega
from app.models.alertas import (
    Alerta,
    ConfiguracionAlertas,
    ConfiguracionAlertasComite,
    Notificacion,
    PlanMejoramiento,
)
from app.models.ranking import ConfiguracionRanking, PuntajeHistorico
from app.models.insignia import Insignia, InsigniaOtorgada
from app.models.ficha_instructor import FichaInstructor
from app.models.juicio import JuicioEvaluativo, JuicioEvaluativoInstructor, FichaCompetenciaSeleccionada
from app.models.aseo import (
    ConfiguracionAseo,
    ContadorAseo,
    IntercambioAseo,
    TurnoAseo,
)
from app.models.material import MaterialFicha
from app.models.importacion import ImportacionJob
from app.models.observador import NotaObservador

__all__ = [
    'Instructor', 'Ficha', 'Aprendiz',
    'SesionAsistencia', 'RegistroAsistencia',
    'Tarea', 'Entrega', 'ConfiguracionAlertas', 'ConfiguracionAlertasComite',
    'Alerta', 'Notificacion', 'PlanMejoramiento',
    'ConfiguracionRanking', 'PuntajeHistorico',
    'Insignia', 'InsigniaOtorgada',
    'FichaInstructor', 'JuicioEvaluativo', 'JuicioEvaluativoInstructor',
    'FichaCompetenciaSeleccionada',
    'ConfiguracionAseo', 'ContadorAseo', 'TurnoAseo', 'IntercambioAseo',
    'MaterialFicha', 'ImportacionJob', 'NotaObservador',
]
