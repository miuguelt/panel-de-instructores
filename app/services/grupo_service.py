import random
from app import db
from app.models.grupo import Grupo, GrupoAprendiz
from app.models.aprendiz import Aprendiz
from app.models.ficha import Ficha


def crear_grupos_aleatorios(ficha_id, aprendiz_ids, tamano_grupo, prefijo_nombre="Grupo"):
    """
    Toma una lista de IDs de aprendices, los mezcla y arma grupos del tamaño especificado.
    Si sobran aprendices, se distribuyen equitativamente (uno a uno) entre los grupos ya formados.
    
    Retorna la lista de objetos Grupo creados.
    """
    if not aprendiz_ids or tamano_grupo <= 0:
        return []

    try:
        ids_seleccionados = [int(aprendiz_id) for aprendiz_id in aprendiz_ids]
    except (TypeError, ValueError) as exc:
        raise ValueError('La selección de aprendices no es válida.') from exc
    ids_unicos = set(ids_seleccionados)
    if len(ids_unicos) != len(ids_seleccionados):
        raise ValueError('Cada aprendiz solo puede asignarse a un grupo.')

    aprendices = Aprendiz.query.filter(
        Aprendiz.ficha_id == ficha_id,
        Aprendiz.id.in_(ids_unicos),
    ).all()
    if len(aprendices) != len(ids_unicos):
        raise ValueError('Todos los aprendices deben pertenecer a la ficha seleccionada.')
    if any(a.deshabilitado for a in aprendices):
        raise ValueError('No se pueden asignar aprendices deshabilitados a grupos.')

    # Mezclar aleatoriamente
    random.shuffle(aprendices)

    # Dividir en chunks iniciales
    chunks = [aprendices[i:i + tamano_grupo] for i in range(0, len(aprendices), tamano_grupo)]

    # Si hay más de un grupo y el último grupo tiene menos del tamaño requerido, se consideran "sobrantes"
    if len(chunks) > 1 and len(chunks[-1]) < tamano_grupo:
        sobrantes = chunks.pop()
        # Repartir los sobrantes uno a uno en los chunks existentes
        for i, aprendiz in enumerate(sobrantes):
            indice_grupo = i % len(chunks)
            chunks[indice_grupo].append(aprendiz)

    grupos_creados = []
    
    # Crear registros en base de datos
    for i, chunk in enumerate(chunks):
        nuevo_grupo = Grupo(
            ficha_id=ficha_id,
            nombre=f"{prefijo_nombre} {i + 1}"
        )
        db.session.add(nuevo_grupo)
        db.session.flush() # Para obtener el ID del grupo
        
        for aprendiz in chunk:
            rel = GrupoAprendiz(
                grupo_id=nuevo_grupo.id,
                aprendiz_id=aprendiz.id
            )
            db.session.add(rel)
        
        grupos_creados.append(nuevo_grupo)

    db.session.commit()
    return grupos_creados


def archivar_grupo(grupo_id):
    """
    Marca un grupo como inactivo.
    """
    grupo = db.session.get(Grupo, grupo_id)
    if grupo:
        grupo.activo = False
        db.session.commit()
        return True
    return False

def archivar_grupos_de_ficha(ficha_id):
    """
    Marca todos los grupos de una ficha como inactivos.
    Útil para "reiniciar" dinámicas de grupos.
    """
    Grupo.query.filter_by(ficha_id=ficha_id, activo=True).update({'activo': False})
    db.session.commit()


def desvincular_aprendiz_de_grupos(ficha_id, aprendiz_id):
    """
    Retira al aprendiz de cualquier grupo al que pertenezca en la ficha.
    """
    rels = (
        GrupoAprendiz.query
        .join(Grupo, Grupo.id == GrupoAprendiz.grupo_id)
        .filter(
            Grupo.ficha_id == ficha_id,
            GrupoAprendiz.aprendiz_id == aprendiz_id,
        )
        .all()
    )
    for rel in rels:
        db.session.delete(rel)
    db.session.flush()


def editar_grupo(grupo_id, nombre, aprendiz_ids=None):
    """
    Actualiza el nombre y la asignación manual de aprendices para un grupo.

    Garantiza que:
    - El grupo exista y esté activo.
    - El nombre sea válido y no supere 100 caracteres.
    - Los aprendices pertenezcan a la misma ficha del grupo.
    - Si un aprendiz pertenecía a otro grupo activo de la misma ficha, se reasigna a este grupo.
    - Los aprendices desmarcados se retiran del grupo.
    - Los aprendices mantenidos conservan su registro.
    """
    grupo = db.session.get(Grupo, grupo_id)
    if not grupo or not grupo.activo:
        raise ValueError('El grupo no existe o se encuentra inactivo.')

    if not nombre or not str(nombre).strip():
        raise ValueError('El nombre del grupo no puede estar vacío.')
    nombre_limpio = str(nombre).strip()
    if len(nombre_limpio) > 100:
        raise ValueError('El nombre del grupo no puede superar los 100 caracteres.')

    if aprendiz_ids is None:
        aprendiz_ids = []

    try:
        ids_seleccionados = [int(aid) for aid in aprendiz_ids]
    except (TypeError, ValueError) as exc:
        raise ValueError('La selección de aprendices no es válida.') from exc

    ids_unicos = set(ids_seleccionados)
    if len(ids_unicos) != len(ids_seleccionados):
        raise ValueError('Cada aprendiz solo puede asignarse una vez al grupo.')

    if ids_unicos:
        aprendices_ficha = Aprendiz.query.filter(
            Aprendiz.ficha_id == grupo.ficha_id,
            Aprendiz.id.in_(ids_unicos),
        ).all()
        if len(aprendices_ficha) != len(ids_unicos):
            raise ValueError('Todos los aprendices deben pertenecer a la ficha seleccionada.')
        if any(a.deshabilitado for a in aprendices_ficha):
            raise ValueError('No se pueden asignar aprendices deshabilitados a grupos.')

    # 1. Desvincular de otros grupos activos de la misma ficha si estaban asignados
    if ids_unicos:
        rels_otros = (
            GrupoAprendiz.query
            .join(Grupo, Grupo.id == GrupoAprendiz.grupo_id)
            .filter(
                Grupo.ficha_id == grupo.ficha_id,
                Grupo.activo.is_(True),
                Grupo.id != grupo.id,
                GrupoAprendiz.aprendiz_id.in_(ids_unicos),
            )
            .all()
        )
        for rel in rels_otros:
            db.session.delete(rel)

    # 2. Desvincular aprendices que ya no pertenecen a este grupo
    rels_actuales = GrupoAprendiz.query.filter_by(grupo_id=grupo.id).all()
    existentes_ids = set()
    for rel in rels_actuales:
        if rel.aprendiz_id not in ids_unicos:
            db.session.delete(rel)
        else:
            existentes_ids.add(rel.aprendiz_id)

    # 3. Vincular aprendices nuevos a este grupo
    for aid in ids_unicos:
        if aid not in existentes_ids:
            db.session.add(GrupoAprendiz(grupo_id=grupo.id, aprendiz_id=aid))

    grupo.nombre = nombre_limpio
    db.session.commit()
    return grupo


def crear_grupo_manual(ficha_id, nombre, aprendiz_ids=None):
    """
    Crea un nuevo grupo de forma manual para una ficha y opcionalmente asigna aprendices.
    """
    if not nombre or not str(nombre).strip():
        raise ValueError('El nombre del grupo no puede estar vacío.')
    nombre_limpio = str(nombre).strip()
    if len(nombre_limpio) > 100:
        raise ValueError('El nombre del grupo no puede superar los 100 caracteres.')

    ficha = db.session.get(Ficha, ficha_id)
    if not ficha:
        raise ValueError('La ficha especificada no existe.')

    nuevo_grupo = Grupo(
        ficha_id=ficha_id,
        nombre=nombre_limpio,
    )
    db.session.add(nuevo_grupo)
    db.session.flush()

    if aprendiz_ids:
        return editar_grupo(nuevo_grupo.id, nombre_limpio, aprendiz_ids)

    db.session.commit()
    return nuevo_grupo

