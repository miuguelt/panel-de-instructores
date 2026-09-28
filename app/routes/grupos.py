from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from sqlalchemy import func
from app import db
from app.models.ficha import Ficha
from app.models.grupo import Grupo, GrupoAprendiz
from app.models.aprendiz import Aprendiz, ESTADOS_EN_FORMACION
from app.models.insignia import Insignia, InsigniaOtorgada
from app.services.grupo_service import crear_grupos_aleatorios, archivar_grupo, archivar_grupos_de_ficha

grupos_bp = Blueprint('grupos', __name__, template_folder='../templates/grupos')

@grupos_bp.route('/fichas/<int:ficha_id>/grupos', methods=['GET'])
@login_required
def listar_grupos(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.dashboard'))

    # Obtener grupos activos
    grupos = Grupo.query.filter_by(ficha_id=ficha_id, activo=True).order_by(Grupo.creado_en.desc()).all()
    
    # Aprendices disponibles para agrupar
    aprendices = ficha.aprendices.filter(Aprendiz.estado.in_(ESTADOS_EN_FORMACION)).order_by(Aprendiz.nombre).all()

    # Obtener insignias disponibles para la ficha
    insignias = Insignia.query.filter_by(ficha_id=ficha_id, activa=True).order_by(Insignia.nombre).all()

    return render_template('listar_grupos.html', ficha=ficha, grupos=grupos, aprendices=aprendices, insignias=insignias)

@grupos_bp.route('/fichas/<int:ficha_id>/grupos/generar', methods=['POST'])
@login_required
def generar_grupos(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        return jsonify({'error': 'Ficha no encontrada'}), 404

    try:
        tamano_grupo = int(request.form.get('tamano_grupo', 3))
        aprendiz_ids = request.form.getlist('aprendices_ids[]')
        
        # Validar
        if not aprendiz_ids:
            flash('Debe seleccionar al menos un aprendiz.', 'error')
            return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))
        
        if tamano_grupo < 2:
            flash('El tamaño del grupo debe ser al menos 2.', 'error')
            return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

        # Archivar los activos anteriores
        archivar_grupos_de_ficha(ficha_id)

        # Convertir a ints
        aprendiz_ids = [int(a_id) for a_id in aprendiz_ids]

        crear_grupos_aleatorios(ficha_id, aprendiz_ids, tamano_grupo)
        
        flash('Grupos generados exitosamente.', 'success')
    except Exception as e:
        flash(f'Error al generar grupos: {str(e)}', 'error')

    return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

@grupos_bp.route('/fichas/<int:ficha_id>/grupos/otorgar_insignia', methods=['POST'])
@login_required
def otorgar_insignia_grupo(ficha_id):
    grupo_id = request.form.get('grupo_id')
    insignia_id = request.form.get('insignia_id')

    if not grupo_id or not insignia_id:
        flash('Faltan datos para otorgar la insignia.', 'error')
        return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

    # Verificar si el grupo ya tiene la insignia (opcional: depende si pueden tener varias iguales)
    # Por ahora dejamos que puedan tener varias a menos que la DB de error.
    
    io = InsigniaOtorgada(
        grupo_id=grupo_id,
        insignia_id=insignia_id
    )
    db.session.add(io)
    db.session.commit()

    flash('Insignia otorgada al grupo correctamente.', 'success')
    return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

@grupos_bp.route('/fichas/<int:ficha_id>/grupos/podio', methods=['GET'])
@login_required
def podio_grupos(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        flash('Ficha no encontrada.', 'error')
        return redirect(url_for('instructor.dashboard'))

    # Calcular podio: sumar el número de insignias otorgadas a cada grupo activo
    grupos_query = db.session.query(
        Grupo, 
        func.count(InsigniaOtorgada.id).label('total_insignias')
    ).outerjoin(
        InsigniaOtorgada, Grupo.id == InsigniaOtorgada.grupo_id
    ).filter(
        Grupo.ficha_id == ficha_id,
        Grupo.activo == True
    ).group_by(
        Grupo.id
    ).order_by(
        func.count(InsigniaOtorgada.id).desc()
    ).all()

    return render_template('podio_grupos.html', ficha=ficha, ranking_grupos=grupos_query)

