# Cortes compartidos por ficha

## Decisión

El corte dejó de representarse únicamente con `ConfiguracionRanking.inicio_corte`.
La entidad `Corte` identifica un periodo independiente dentro de una ficha, con
su instructor creador, nombre, fechas y bandera `compartido`.

`Tarea`, `SesionAsistencia` y `PuntajeHistorico` conservan su `ficha_id` y
además pueden guardar `corte_id`. Los registros antiguos se migran a un corte
inicial compartido de cada ficha. Los datos creados antes de esta capacidad y
las pruebas que construyen modelos sin corte siguen siendo compatibles porque
la columna es nullable durante la transición.

## Acceso

- El creador y los administradores pueden modificar su corte.
- Un instructor vinculado a la ficha puede consultar un corte compartido.
- Un corte privado solo queda visible para su creador y administradores.
- La consulta explícita de un `corte_id` filtra tareas, sesiones, entregas,
  estadísticas y ranking; no se mezclan periodos.
- Cada corte tiene ciclo de vida: `activo`, `cerrado` o `archivado`.
- Los cortes cerrados y archivados permanecen disponibles para consulta,
  exportación e histórico, pero no aceptan nuevas tareas, ediciones ni
  registros de asistencia.
- Solo el creador o un administrador puede cambiar el estado. Reactivar un
  corte cerrado cierra automáticamente el corte activo anterior del mismo
  instructor y ficha; un corte archivado no se reactiva.

La resolución del corte activo vive en `app/services/cortes.py`. Las rutas de
instructor y ranking no duplican la regla de visibilidad: validan el corte con
ese servicio y pasan el identificador a las consultas de dominio.

## Migración

`h29corte_tareas_asistencia_compartidas` crea la tabla `cortes`, añade las
relaciones opcionales y reemplaza la unicidad de asistencia por
`(corte_id, fecha)`. Esto permite que dos instructores registren una sesión en
la misma fecha dentro de cortes distintos, sin duplicar la sesión de un mismo
corte. `i30ciclo_vida_cortes` agrega el estado y clasifica como cerrados los
cortes históricos que ya tenían `fecha_fin`.
