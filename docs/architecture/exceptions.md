# Excepciones de modularidad

## Archivos de rutas y ranking heredados

- Propietario: equipo de mantenimiento de Panel de Instructores.
- Archivos: `app/routes/instructor.py`, `app/routes/ranking.py` y
  `app/services/ranking.py`.
- Motivo: estos archivos ya superaban el presupuesto de tamaño antes de la
  funcionalidad de cortes. El cambio necesitó conectar permisos, consultas,
  asistencia, tareas y ranking para conservar una sola transacción y evitar
  separar el flujo a mitad de una operación.
- Excepción: se acepta el crecimiento acotado de esta iteración (separación de
  cortes y ciclo de vida), manteniendo la lógica reutilizable en
  `app/services/cortes.py`. El gate sigue reportando estos archivos porque ya
  excedían el umbral antes de este trabajo.
- Plan: extraer por rebanadas verticales los grupos de rutas de cortes,
  asistencia y ranking en una iteración posterior, con pruebas de contrato
  antes de mover cada grupo.
