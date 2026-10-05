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

## Servicio de aseo heredado

- Propietario: equipo de mantenimiento de Panel de Instructores.
- Archivo: `app/services/aseo.py`.
- Motivo: el servicio ya excedía el presupuesto modular antes de corregir
  el desempate de turnos. La selección duplicada y la explicación se extrajeron
  a `app/services/aseo_cola.py`; el archivo heredado se redujo en esta iteración.
- Deuda: permanecen en el servicio la generación, los contadores, las reposiciones
  y los intercambios. La corrección no autoriza crecimiento adicional ni rebaja
  las compuertas de pruebas o modularidad.
- Plan: separar esos casos de uso gradualmente con pruebas de sus transacciones
  y contratos. La decisión de esta extracción está en `cola-equitativa-aseo.md`.
