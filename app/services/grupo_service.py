import random
from app import db
from app.models.grupo import Grupo, GrupoAprendiz
from app.models.aprendiz import Aprendiz


def crear_grupos_aleatorios(ficha_id, aprendiz_ids, tamano_grupo, prefijo_nombre="Grupo"):
    """
    Toma una lista de IDs de aprendices, los mezcla y arma grupos del tamaño especificado.
    Si sobran aprendices, se distribuyen equitativamente (uno a uno) entre los grupos ya formados.
    
    Retorna la lista de objetos Grupo creados.
    """
    if not aprendiz_ids or tamano_grupo <= 0:
        return []

    # Validar que los aprendices existan y pertenezcan a la ficha (opcional pero recomendado)
    aprendices = Aprendiz.query.filter(Aprendiz.id.in_(aprendiz_ids)).all()
    if not aprendices:
        return []

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
