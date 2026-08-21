# Línea de tiempo de la planeación por trimestres

**Fecha:** 2026-08-18 · **Módulo:** `/instructor/fichas/<id>/planeacion`

## Problema

El módulo repetía información que Juicios y Estadísticas ya calculaban (estado de
aprendices, historial por instructor, avance por tipo de competencia) y no
respondía la única pregunta que le corresponde: **si la ficha va bien de tiempo**.
Las fechas se estimaban repartiendo horas sobre toda la duración de la ficha,
incluida la etapa productiva, e ignoraban la columna TRIMESTRE del GFPI-F-134.

## Decisión

Se separa el problema en cuatro responsabilidades, una por archivo, y la vista
solo consume el resultado compuesto.

| Módulo | Responsabilidad |
|---|---|
| `app/services/calendario_formacion.py` | Divide la ficha en trimestres lectivos más un bloque de etapa productiva. |
| `app/services/emparejamiento_juicios.py` | Regla única de correspondencia entre un RAP planeado y los juicios del reporte. |
| `app/services/linea_tiempo.py` | Ancla cada resultado a un trimestre, calcula cierre real y desfase, agrupa en fases y competencias. |
| `app/services/proyeccion_ficha.py` | Curva planeado contra real y proyección de cierre lectivo por ritmo de aprobación. |
| `app/services/diagnostico_planeacion.py` | Enumera los vacíos de datos que degradan la precisión. |
| `app/services/panorama_planeacion.py` | Compone las piezas y redacta el veredicto para la vista. |

Las dependencias apuntan en una sola dirección: `panorama` → los demás;
`linea_tiempo` → `calendario_formacion`; `analisis_planeacion` y `linea_tiempo`
→ `emparejamiento_juicios`. No hay ciclos y ninguno accede a la base de datos
salvo `analisis_planeacion`, lo que deja el resto probable con diccionarios.

### Modelo de tiempo

La duración lectiva no está declarada en ninguna parte: se deduce restando
`duracion_productiva_meses` de la duración total de la ficha. Para ADSO son 27
meses menos 6 de etapa productiva, es decir 21 meses lectivos que se dividen en
7 trimestres de 3 meses, la misma numeración que usa la planeación
(`Trimestre 1` a `Trimestre 7`). El último trimestre absorbe el residuo para que
la etapa lectiva termine exactamente donde empieza la productiva.

### Fecha real de ejecución

Los registros `POR EVALUAR` del Reporte de Juicios Evaluativos **no traen
fecha**; solo las aprobaciones la traen. Por eso la única marca de tiempo real
disponible es la primera aprobación de cada aprendiz por resultado. Un resultado
se considera cerrado cuando el 80 % de los aprendices con estado vigente lo
tiene aprobado, y la fecha de cierre es la del aprendiz que completa ese umbral.

### Trimestres no declarados

Cuando la columna TRIMESTRE viene vacía, la ubicación se estima con el orden de
las actividades del proyecto formativo (`AP01`…`AP13`): una actividad sin
declarar va después de la última ubicada. El resultado queda marcado como
estimado en la interfaz y aparece en el diagnóstico de datos faltantes; nunca se
presenta como dato del documento.

## Alternativas descartadas

- **Repartir horas linealmente sobre toda la ficha** (comportamiento anterior).
  Ignora el trimestre declarado y mete horas lectivas dentro de la etapa
  productiva, así que el atraso calculado no corresponde a nada verificable.
- **Usar la fecha del reporte como fecha de ejecución de todos los juicios.**
  Marcaría como ejecutado en la fecha de corte lo que sigue `POR EVALUAR`.
- **Inferir el trimestre por promedio de horas acumuladas.** Produce fronteras
  que no coinciden con las declaradas y vuelve incomparables las dos fuentes.

## Qué queda fuera del módulo

Estado de aprendices, historial por funcionario evaluador, avance por tipo de
competencia y tasa de aprobación por aprendiz siguen siendo responsabilidad de
Juicios y Estadísticas. Esta vista enlaza a esos módulos en vez de recalcularlos.

## Anexo 2026-08-19 · Contraste con el Programa de Formación

### Correspondencia entre planeación y programa

El PDF oficial nombra cada competencia dos veces: el encabezado del bloque trae
el nombre largo de la norma ("Establecer requisitos de la solución de software…")
y el campo `4.3 NOMBRE DE LA COMPETENCIA` trae el nombre corto
("ESPECIFICACIÓN DE REQUISITOS DEL SOFTWARE"). La planeación pedagógica usa el
corto. Extraer ambos es lo que permite emparejar: con solo el largo, 9 de 19
competencias aparecían como no planeadas.

El emparejamiento resuelve por prioridad y con exclusividad: código de norma,
nombre exacto, contención de texto y por último solapamiento de palabras. Dos
salvaguardas evitan asignaciones falsas:

- **Contención mínima de dos palabras.** Sin ella, "FISICA" queda contenida en
  "programas de actividad física" y se lleva la competencia de hábitos de vida
  saludable.
- **Dos palabras significativas en común como mínimo** para aceptar
  solapamiento. Los títulos de una sola palabra ("TIC", "INGLES") daban un
  solapamiento perfecto contra cualquier texto que los mencionara.

Una competencia oficial puede recibir **varios rótulos** de la planeación: ADSO
parte "Construcción del software" en dos filas y el inglés en dos. Sumarlos es
lo que hace que las horas cuadren; tomando solo el primero se reportaban horas
faltantes inexistentes (inglés aparecía con 64 h de 384).

La correspondencia resuelta se publica en `contraste['mapa_competencias']` para
que ningún consumidor vuelva a adivinar por parecido de nombres. Es lo que
permite que la ficha pedagógica abra desde el rótulo de la planeación: antes
resolvía 11 de 24 competencias, ahora 23 de 24 (la excepción es la etapa
práctica, que no tiene bloque curricular en el PDF).

### Verificación con la ficha 3235642

19 de 19 competencias emparejadas, 0 falsas ausencias. Las diferencias de horas
que quedan son reales y reconcilian con el total: +170 en Construcción del
software, +78 en Adopción de buenas prácticas, +10 en Inducción y −18 en
Análisis de la especificación suman las +240 h que la planeación tiene por
encima de las 3120 h lectivas del programa.

### Valor ganado y cierre de competencias miden cosas distintas

El SPI pondera por horas, así que una competencia grande en curso (1008 h) lo
empuja hacia arriba aunque queden competencias pequeñas vencidas sin cerrar. Se
corrigió que el valor planeado del trimestre en curso se prorratee por la parte
transcurrida —antes se comparaba el plan al cierre del trimestre contra lo
ganado a hoy, lo que inflaba el índice— y se renombraron las etiquetas para que
el indicador no se lea como un veredicto de cronograma.

### Módulos añadidos

| Módulo | Responsabilidad |
|---|---|
| `app/services/programa_formacion.py` | Lee el PDF oficial: horas por etapa, competencias, norma, resultados, conocimientos, criterios y perfil del instructor. |
| `app/services/contraste_programa.py` | Empareja planeación y programa, compara horas y cobertura, calcula la intensidad horaria. |
| `app/services/catalogo_pedagogico.py` | Arma la ficha pedagógica de cada competencia consumiendo la correspondencia ya resuelta. |
| `app/services/graficos_planeacion.py` | Coordenadas del radar curricular y de la matriz de carga por instructor. |
| `app/services/carga_documentos.py` | Carga unificada de los tres documentos en una sola transacción. |
