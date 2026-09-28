from app import db
from app.models.atencion import TurnoAtencion
from datetime import datetime

class AtencionService:
    @staticmethod
    def solicitar_turno(ficha_id, aprendiz_id, motivo=None):
        # Verificar si ya tiene un turno en espera o en atención
        turno_existente = TurnoAtencion.query.filter_by(
            ficha_id=ficha_id,
            aprendiz_id=aprendiz_id
        ).filter(TurnoAtencion.estado.in_(['esperando', 'en_atencion'])).first()
        
        if turno_existente:
            return turno_existente
            
        nuevo_turno = TurnoAtencion(
            ficha_id=ficha_id,
            aprendiz_id=aprendiz_id,
            motivo=motivo,
            estado='esperando'
        )
        db.session.add(nuevo_turno)
        db.session.commit()
        return nuevo_turno

    @staticmethod
    def obtener_fila(ficha_id):
        # Retornar los turnos ordenados por fecha de creación
        return TurnoAtencion.query.filter_by(
            ficha_id=ficha_id
        ).filter(TurnoAtencion.estado.in_(['esperando', 'en_atencion'])).order_by(TurnoAtencion.creado_en.asc()).all()

    @staticmethod
    def obtener_turno_actual_aprendiz(ficha_id, aprendiz_id):
        return TurnoAtencion.query.filter_by(
            ficha_id=ficha_id,
            aprendiz_id=aprendiz_id
        ).filter(TurnoAtencion.estado.in_(['esperando', 'en_atencion'])).first()

    @staticmethod
    def cambiar_estado(turno_id, nuevo_estado):
        turno = db.session.get(TurnoAtencion, turno_id)
        if not turno:
            return None
            
        turno.estado = nuevo_estado
        if nuevo_estado == 'en_atencion' and not turno.atendido_en:
            turno.atendido_en = datetime.utcnow()
        elif nuevo_estado in ['atendido', 'cancelado', 'ausente']:
            turno.completado_en = datetime.utcnow()
            
        db.session.commit()
        return turno
