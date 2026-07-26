from flask import Blueprint, jsonify, current_app
from flask_login import login_required
from app import db
from app.models.ficha import Ficha
from app.models.aprendiz import Aprendiz
from app.models.asistencia import RegistroAsistencia, SesionAsistencia
from app.services.permisos import puede_gestionar_ficha

api_bp = Blueprint('api', __name__)


@api_bp.route('/health')
def health():
    try:
        with db.engine.connect():
            pass
        return jsonify({'status': 'ok', 'database': 'connected'})
    except Exception:
        current_app.logger.exception('La verificación de salud no pudo conectar con la base de datos')
        return jsonify({'status': 'error', 'database': 'unavailable'}), 503


@api_bp.route('/fichas/<int:ficha_id>/resumen')
@login_required
def resumen_ficha(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not puede_gestionar_ficha(ficha):
        return jsonify({'error': 'No encontrado'}), 404

    total_aprendices = Aprendiz.query.filter_by(ficha_id=ficha_id).count()
    total_sesiones = SesionAsistencia.query.join(RegistroAsistencia).filter(SesionAsistencia.ficha_id == ficha_id).distinct().count()

    return jsonify({
        'ficha': ficha.codigo,
        'programa': ficha.nombre_programa,
        'total_aprendices': total_aprendices,
        'total_sesiones': total_sesiones,
    })
