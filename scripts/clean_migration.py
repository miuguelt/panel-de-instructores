import os

path = 'migrations/versions/dfe8ae6bc6d3_add_turnoatencion.py'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

ignorar = ['usuarios', 'personas', 'fincas', 'finca_cultivo', 'productos', 'roles', 'categorias', 'registros_acceso', 'cultivos', 'perfiles']

new_lines = []
skip = False
for line in lines:
    # Si empieza batch_alter_table con tabla a ignorar, skip
    if "with op.batch_alter_table(" in line:
        ignorar_match = any([f"'{t}'" in line for t in ignorar])
        if ignorar_match:
            skip = True
            continue
    
    # Si estamos saltando y encontramos de-identación, dejamos de saltar a menos que sea una llamada encadenada
    if skip:
        # En alembic, batch_alter_table se cierra cuando se vuelve a la indentación de 4 espacios
        if line.startswith("    ") and not line.startswith("        ") and "batch_op." not in line:
            skip = False
        else:
            continue
    
    # Si es drop_table
    if "op.drop_table" in line:
        if any([f"'{t}'" in line for t in ignorar]):
            continue
    
    # Si es create_table (downgrade)
    if "op.create_table" in line:
        if any([f"'{t}'" in line for t in ignorar]):
            skip = True
            continue
    
    new_lines.append(line)

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
