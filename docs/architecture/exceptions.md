# Excepciones de modularidad

## Controlador de personalización del aprendiz

- Propietario: equipo de mantenimiento de Panel de Instructores.
- Archivo: `app/static/js/aprendiz_personalizacion.js`.
- Motivo: sus 340 líneas contienen un único controlador público y funciones privadas para el ciclo de borrador, confirmación, foto y orden. Los efectos del editor comparten el mismo estado y no tienen consumidores independientes. Se revisó la cohesión; permanece por debajo del límite de 400 líneas.
- Verificación: pruebas observables de interfaz, cobertura del 100 % de funciones y recorrido de navegador con base de datos real de pruebas.
- Límite: nuevas capacidades con razones de cambio independientes se extraerán antes de ampliar este controlador. La excepción no reduce los umbrales de cobertura ni modifica el baseline.
- Registro de aplicación: `app/__init__.py` solo agrega una llamada de registro; el incremento de esta tarea es de una línea. El aviso del baseline incluye crecimiento anterior a esta iteración.

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
- Corrección de pendientes en días no permitidos: la limpieza se extrajo a
  `app/services/aseo_limpieza.py`, reduciendo el servicio heredado. Las rutas
  informan las eliminaciones sin aumentar su número de líneas.
- Plan: separar esos casos de uso gradualmente con pruebas de sus transacciones
  y contratos. La decisión de esta extracción está en `cola-equitativa-aseo.md`.

## Rutas heredadas del calendario de aseo

- Propietario: equipo de mantenimiento de Panel de Instructores.
- Archivo: `app/routes/aseo.py`.
- Motivo: el archivo ya superaba el presupuesto antes de esta mejora. Los
  formularios del instructor y del aprendiz tienen permisos y contratos
  independientes; esta iteración agrega la misma selección semanal a ambos
  y valida los valores recibidos antes de invocar el servicio de generación.
- Excepción: crecimiento acotado para pasar la selección semanal a la generación
  y ofrecer las mismas opciones en las dos vistas. La validación de los días
  vive en `app/services/aseo_calendario.py`; el cálculo de fechas sigue en
  `app/services/aseo.py`.
- Plan: extraer en una iteración posterior los controladores de generación y las
  vistas del calendario con pruebas independientes de sus permisos y rutas.
