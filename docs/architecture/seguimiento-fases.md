# Seguimiento de fase y viabilidad de los resultados de aprendizaje

## Propósito

La sección **Fase actual** responde dos preguntas distintas sin mezclarlas:

1. ¿En qué fase debería estar el proyecto según el tiempo transcurrido?
2. ¿En qué fase efectiva está según los resultados de aprendizaje que ya tienen juicio?

Las fases canónicas son **ANÁLISIS, PLANEACIÓN, EJECUCIÓN y EVALUACIÓN**.
La fuente temporal es la Planeación Pedagógica GFPI-F-134. El Reporte de
Juicios Evaluativos aporta el avance observado. El Programa de Formación
Oficial valida la cobertura curricular y las horas, pero no reemplaza las fases
declaradas en la planeación.

## Estrategia de cálculo

La unidad de medición es un RAP planeado y emparejado con el reporte de
juicios.

### Fase esperada

Para cada fase se toma la fecha mínima y máxima de sus RAP. La fase esperada al
corte es la fase cuya ventana contiene la fecha de corte; si el corte está
antes de la primera ventana, es la primera fase futura; si está después de la
última, es la última fase planeada.

El número de RAP esperados se calcula de forma proporcional para no comparar el
plan al cierre de una fase con el avance de un día intermedio:

`RAP esperados = redondear(Σ fracción transcurrida de cada RAP)`

La fracción es 0 antes del inicio, 1 después del fin y, dentro de la ventana,
los días transcurridos divididos por los días planeados.

### Fase real

- Un RAP está **evaluado** cuando el reporte registra al menos un juicio
  efectivamente emitido para ese RAP. Las filas **POR EVALUAR**, **Pendiente**
  o **Sin evaluar** no cuentan.
- Un RAP está **cerrado** cuando el avance aprobado alcanza el 80 % de los
  aprendices vigentes analizados.
- La fase real es la primera fase planeada que todavía tiene un RAP sin cerrar.
  Si todas están cerradas, el proyecto se marca como completado.

Esta regla evita que una evaluación aislada de una fase futura haga parecer que
el proyecto ya abandonó una fase anterior incompleta.

### Ritmo y proyección

`brecha de RAP = RAP evaluados - RAP esperados`

El ritmo reciente cuenta RAP distintos evaluados con fecha en los últimos 180
días:

`ritmo mensual = RAP evaluados recientes / (180 / 30,44)`

La fecha proyectada se obtiene con los RAP pendientes:

`meses faltantes = RAP pendientes / ritmo mensual`

La fecha se compara con el fin de la ficha. Si no hay evaluaciones fechadas en
la ventana, el sistema muestra **Sin datos** y no inventa una fecha.

## Estados visibles

| Estado | Regla |
|---|---|
| Al día | La fase real coincide con la esperada y los RAP evaluados alcanzan el conteo esperado. |
| Atrasado | La fase real está antes de la esperada o hay menos RAP evaluados que los esperados. |
| Adelantado | La fase real está después de la esperada o hay más RAP evaluados que los esperados. |
| Completado | Todos los RAP planeados están cerrados. |
| Sin datos | No hay RAP planeados o no existen fechas recientes para proyectar el cierre. |

## Escenarios BDD y pruebas

- **Given** la fecha de corte está en el quinto trimestre, **When** las fases
  anteriores están cerradas, **Then** la fase esperada y la fase real se
  muestran como EJECUCIÓN.
- **Given** ANÁLISIS conserva RAP sin cerrar, **When** el calendario ya está
  en EJECUCIÓN, **Then** la fase real es ANÁLISIS y el estado es Atrasado.
- **Given** existen RAP evaluados con fecha en los últimos 180 días, **When**
  se proyecta el cierre, **Then** se informa el ritmo mensual y se compara la
  fecha contra el fin de la ficha.
- **Given** no existen evaluaciones fechadas recientes, **When** se proyecta
  el cierre, **Then** no se presenta una fecha falsa y el estado es Sin datos.

La lógica pura está en `app/services/seguimiento_fases.py`, se compone en
`app/services/panorama_planeacion.py` y la interfaz se encuentra en
`app/templates/instructor/_planeacion_panorama.html`.
