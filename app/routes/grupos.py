from flask import Blueprint, abort, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy import func
from app import db
from app.models.ficha import Ficha
from app.models.grupo import Grupo
from app.models.aprendiz import Aprendiz, ESTADOS_EN_FORMACION
from app.models.insignia import Insignia, InsigniaOtorgada
from app.services.permisos import puede_gestionar_ficha
from app.services.grupo_service import crear_grupos_aleatorios, archivar_grupos_de_ficha

grupos_bp = Blueprint('grupos', __name__, template_folder='../templates/grupos')

@grupos_bp.route('/fichas/<int:ficha_id>/grupos', methods=['GET'])
@login_required
def listar_grupos(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha or not puede_gestionar_ficha(ficha):
        abort(404)

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
    if not ficha or not puede_gestionar_ficha(ficha):
        abort(404)

    try:
        tamano_grupo = int(request.form.get('tamano_grupo', 3))
        aprendiz_ids = request.form.getlist('aprendices_ids[]')
        
        if not aprendiz_ids:
            flash('Debe seleccionar al menos un aprendiz.', 'error')
            return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))
        
        if tamano_grupo < 2:
            flash('El tamaño del grupo debe ser al menos 2.', 'error')
            return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

        try:
            ids_seleccionados = [int(aprendiz_id) for aprendiz_id in aprendiz_ids]
        except (TypeError, ValueError):
            flash('La selección de aprendices no es válida.', 'error')
            return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

        ids_unicos = set(ids_seleccionados)
        aprendices_ficha = Aprendiz.query.filter(
            Aprendiz.ficha_id == ficha.id,
            Aprendiz.id.in_(ids_unicos),
        ).all()
        if len(aprendices_ficha) != len(ids_unicos) or len(ids_unicos) != len(ids_seleccionados):
            flash('Selecciona aprendices distintos que pertenezcan a esta ficha.', 'error')
            return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

        # Archivar los grupos anteriores solo después de validar la selección.
        archivar_grupos_de_ficha(ficha_id)

        crear_grupos_aleatorios(ficha_id, ids_seleccionados, tamano_grupo)
        
        flash('Grupos generados exitosamente.', 'success')
    except ValueError as e:
        flash(str(e), 'error')

    return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

@grupos_bp.route('/fichas/<int:ficha_id>/grupos/otorgar_insignia', methods=['POST'])
@login_required
def otorgar_insignia_grupo(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha or not puede_gestionar_ficha(ficha):
        abort(404)

    grupo_id = request.form.get('grupo_id')
    insignia_id = request.form.get('insignia_id')

    if not grupo_id or not insignia_id:
        flash('Faltan datos para otorgar la insignia.', 'error')
        return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

    try:
        grupo_id = int(grupo_id)
        insignia_id = int(insignia_id)
    except (TypeError, ValueError):
        flash('El grupo y la insignia seleccionados no son válidos.', 'error')
        return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

    grupo = Grupo.query.filter_by(
        id=grupo_id, ficha_id=ficha.id, activo=True
    ).first()
    insignia = Insignia.query.filter_by(
        id=insignia_id, ficha_id=ficha.id, activa=True
    ).first()
    if not grupo or not insignia:
        flash('El grupo y la insignia deben pertenecer a esta ficha.', 'error')
        return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

    ya_otorgada = InsigniaOtorgada.query.filter_by(
        grupo_id=grupo.id, insignia_id=insignia.id
    ).first()
    if ya_otorgada:
        flash('Esta insignia ya fue otorgada a este grupo.', 'info')
        return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

    io = InsigniaOtorgada(
        grupo_id=grupo.id,
        insignia_id=insignia.id,
    )
    db.session.add(io)
    db.session.commit()

    flash('Insignia otorgada al grupo correctamente.', 'success')
    return redirect(url_for('grupos.listar_grupos', ficha_id=ficha_id))

@grupos_bp.route('/fichas/<int:ficha_id>/grupos/podio', methods=['GET'])
@login_required
def podio_grupos(ficha_id):
    ficha = db.session.get(Ficha, ficha_id)
    if not ficha or not puede_gestionar_ficha(ficha):
        abort(404)

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

