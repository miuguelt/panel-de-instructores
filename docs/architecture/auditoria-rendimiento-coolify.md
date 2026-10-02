# Auditoría de rendimiento en Coolify

Fecha: 1 de octubre de 2026. Páginas reportadas: `/instructor/` y `/instructor/fichas/2/aprendices`, en `https://control.enlinea.sbs/`.

## Resultado y alcance

Se confirmaron dos problemas: el indicador podía cubrir una página ya recibida mientras esperaba JavaScript externo, y el tablero del instructor hacía trabajo costoso de Excel y comparación de textos antes de responder. La base de producción ya es PostgreSQL. Redis está disponible; una conexión correcta a Redis no almacena automáticamente los resultados de las páginas.

Se revisaron plantillas, scripts de carga, consultas de aprendices, tareas y juicios, recomendaciones, planeación, TyT, archivos, conexiones, Gunicorn y Docker Compose. Además de las pruebas sintéticas locales, se inspeccionaron el navegador autenticado, los registros y el servidor real mediante la consola de Coolify. La llave SSH disponible estaba cifrada y el agente SSH no estaba habilitado; la consola autenticada permitió completar el diagnóstico.

Durante la revisión se desplegó la revisión `3b2605b937cea940c21cdd39ede608b873a1e447`, que incluye los ajustes previos de carga, consultas e instrumentación. Se verificaron HTMX local y `Server-Timing` en producción. Las optimizaciones adicionales de Python descritas más adelante permanecen locales. Se compararon temporalmente en un proceso de diagnóstico independiente del servidor, con transacción PostgreSQL de solo lectura; no se reemplazaron archivos ni procesos de Gunicorn.

## Evidencia del servidor real

| Comprobación | Resultado observado |
| --- | --- |
| Registro de `/instructor/` | 58,793732 s antes de completar la respuesta |
| Registro de aprendices de la ficha 2 | 1,121919 s |
| CPU y memoria del servidor | 6 núcleos; 11.960 MiB de RAM; 6.836 MiB disponibles |
| Disco principal | 24 % ocupado; 213 GB disponibles |
| Swap y espera de disco | 2 MiB de swap usados; `vmstat`: 0–2 % de espera de disco en las muestras |
| Conexión PostgreSQL desde el contenedor | 0,131 s |
| Bloqueos PostgreSQL | Ninguna sesión bloqueada en la muestra |
| Tamaño de la base | 53.656.599 bytes, aproximadamente 51 MiB |
| Procesos y hilos web configurados | 3 procesos × 8 hilos |

Las muestras no muestran falta de RAM, disco ni un bloqueo de PostgreSQL. No constituyen una prueba de capacidad durante todos los picos de tráfico. Mientras se ejecutaba el análisis lento, el proceso Python de diagnóstico consumió aproximadamente el 97 % de un núcleo. Los estados de espera y los bloqueos se consultaron mediante las vistas de actividad y `pg_blocking_pids`, descritos en la [documentación de PostgreSQL](https://www.postgresql.org/docs/current/monitoring-stats.html).

### Causa del tiempo del tablero

Se perfiló `_dashboard_inner` con las 12 fichas de la cuenta administradora y los datos reales, sin imprimir contenido de aprendices. El perfil tomó 240,53 segundos por la sobrecarga de `cProfile`; esa duración no representa una petición normal. Los tiempos acumulados se superponen y no deben sumarse.

| Recorrido | Llamadas | Tiempo acumulado con perfilador |
| --- | ---: | ---: |
| Seguimiento de fases | 12 | 229,63 s |
| Análisis con planeación | 6 | 222,76 s |
| Búsqueda de juicios por RAP | 456 | 109,34 s |
| `SequenceMatcher.ratio` | 31.956 | 98,99 s |
| Consulta de última versión | 29 | 96,24 s |
| Lectura de metadatos de Excel | 39 | 93,49 s |

Consultar la última versión del reporte podía activar la búsqueda de archivos originales en disco. La lectura de sus metadatos recorría todas las filas y también construía registros de juicios, aunque solo se necesitaban los encabezados. El análisis de planeación comparaba textos de RAP mediante alineamientos costosos, y tanto ese análisis como TyT normalizaban repetidamente los mismos textos. Este trabajo ocurre dentro de la respuesta web y explica las esperas largas aunque `/health` responda rápido.

## Qué dicen los registros entregados

El último número del registro es tiempo en **microsegundos**, según `--access-logformat '%(m)s %(U)s %(s)s %(D)s'` en `docker-entrypoint.sh`. La definición de `D` está en la [documentación de Gunicorn](https://gunicorn.org/reference/settings/).

| Solicitud reportada | Tiempo del servidor |
| --- | ---: |
| `/instructor/fichas/10/tareas` | 13,98 s y 8,60 s |
| `/instructor/fichas/3/tareas` | 21,20 s y 9,19 s |
| `/instructor/fichas/3/juicios` | 19,80 s |
| `/aprendiz/2/panel` | 1,87 s y 3,94 s |

Estos números no son tamaños del HTML. Un `200` confirma que el servidor completó la respuesta, aunque haya tardado demasiado. Los `/health` rápidos comprueban que el proceso responde; no ejecutan el análisis ni renderizan las tablas de las páginas lentas. Los `302` de inicio y login no bastan para demostrar un bucle de redirecciones. El aviso de openpyxl sobre una extensión desconocida tampoco demuestra un bloqueo: es una advertencia del lector de Excel.

## Hallazgos corregidos

### 1. Indicador visible mientras el navegador espera un CDN

`base.html` entregaba el indicador visible. Su script se ejecutaba después de analizar el HTML. En aprendices había además un script de QR desde cdnjs sin `defer`: una descarga pendiente detenía el análisis del documento y podía impedir que el script del indicador lo ocultara. Mover el indicador antes de HTMX, como se hizo en el ajuste anterior, no resolvía ese bloqueo del cuerpo del documento.

Cambios aplicados:

- El HTML inicial entrega el indicador con `hidden` y `aria-hidden="true"`. El contenido queda disponible incluso si JavaScript falla.
- El indicador se activa en navegaciones y envíos internos. Omite las rutas de descarga reconocidas, `/archivo`, anclas de la misma página y el `beforeunload` de una descarga.
- HTMX 2.0.4 y QRCode.js 1.0.0 se sirven desde `app/static/vendor`, con sus licencias y un manifiesto SHA-256.
- QRCode.js se carga con `defer` y el directorio se inicializa después de `DOMContentLoaded`, conservando búsqueda, proyección y descarga del QR.

Los scripts de Lucide en las vistas de grupos siguen siendo externos y diferidos. Ya no condicionan la visibilidad del indicador inicial. Las fuentes de Google tienen una fuente de respaldo y se solicitan sin bloquear el procesamiento del HTML.

En un navegador de prueba aislado se cargó el HTML real de la versión anterior. La respuesta llegó en 807 ms; al retrasar deliberadamente la descarga de HTMX desde unpkg, el indicador continuó visible a los 61 segundos. Al liberar la descarga desapareció. Esto demuestra el mecanismo del bloqueo; no demuestra que unpkg haya fallado en la petición original del usuario. Los scripts diferidos y `DOMContentLoaded` se relacionan como explica [MDN](https://developer.mozilla.org/en-US/docs/Web/API/Document/DOMContentLoaded_event).

### 2. Demasiadas consultas para el tablero de tareas

El tablero leía relaciones de grupos por cada tarea. El evaluador consultaba el número de entregas una vez por cada tarea próxima a vencer. La ruta obtenía recomendaciones de todos los módulos y la plantilla las volvía a solicitar.

Ahora se precargan grupos, responsables y cortes; los conteos de entregas se agrupan en una consulta; y la plantilla recibe las recomendaciones que ya preparó la ruta. La carga de relaciones en conjunto evita consultas por objeto, como explica [SQLAlchemy sobre `selectinload`](https://docs.sqlalchemy.org/en/20/tutorial/orm_related_objects.html).

### 3. Cálculos de planeación en páginas que no los muestran

Las recomendaciones de tareas y juicios también calculaban fases. Cuando existe una planeación, ese recorrido puede leer el Excel y construir el análisis que combina unidades, aprendices y juicios. Se repetía parte del recorrido al renderizar las alertas de la plantilla. La caché del Excel parseado no evitaba reconstruir todo el análisis.

`obtener_recomendaciones_ficha` admite ahora categorías. Las páginas de tareas y juicios piden solo su módulo. Los demás módulos también solicitan su categoría desde el helper de plantilla. El llamado sin categorías conserva todas las recomendaciones para las vistas generales. La cache del helper dura una petición y distingue ficha y categoría.

### 4. El directorio cargaba cada juicio para obtener solo conteos

Aprendices materializaba todos los registros de juicios en Python para calcular cantidades y porcentajes. Ahora PostgreSQL devuelve un agregado por aprendiz con `COUNT`, `SUM` y `GROUP BY`. Se conservan los filtros por estado, los aprendices sin juicios, los porcentajes y la regla histórica de aprobación del directorio.

La diferencia entre tiempo de consulta, transferencia y materialización de objetos es relevante para este caso; [SQLAlchemy documenta cómo distinguirlos al perfilar](https://docs.sqlalchemy.org/en/20/faq/performance.html).

### 5. Comparación de RAP y normalización repetida

La búsqueda conserva la prioridad de código, texto exacto y un único candidato con similitud mínima del 90 %. Antes de construir `SequenceMatcher` se calculan cotas por longitud y cantidad de caracteres comunes. Si una cota es inferior al umbral, el candidato no puede cumplirlo. La búsqueda termina al encontrar un segundo candidato válido, porque el resultado ya es ambiguo. Estas cotas corresponden a las propiedades de `real_quick_ratio` y `quick_ratio` documentadas en [Python](https://docs.python.org/3.12/library/difflib.html).

Se reutilizan las transformaciones puras de texto de RAP y TyT mediante dos cachés acotadas a 4.096 entradas. La entrada se convierte a texto antes de consultar la caché, por lo que un valor mutable actualizado conserva su comportamiento. Los resultados de avance siguen calculándose con los juicios actuales.

### 6. Metadatos y recuperación de archivos dentro de una lectura de fases

La lectura de metadatos procesa como máximo las primeras 20 filas, que son las que consume el extractor de encabezados. El lector completo sigue procesando todos los juicios. Los libros XLS y XLSX liberan sus recursos también cuando ocurre un error, y se restaura la posición del archivo recibido. XLS usa carga bajo demanda para esta operación; [xlrd documenta esa opción y la liberación de recursos](https://xlrd.readthedocs.io/en/latest/on_demand.html).

El seguimiento de fases consulta la versión registrada con `recuperar_reporte=False`. Así evita reconstruir archivos o buscar reportes heredados al abrir el tablero. Las rutas que necesitan recuperar o descargar el reporte mantienen el comportamiento existente. Se probaron el análisis de fases con una planeación real de prueba, la ausencia de recuperación y la conservación de la importación completa en ambos formatos.

## Mediciones antes y después

### Comparación con los datos de producción

Se ejecutó el mismo tablero, con la misma cuenta y los mismos datos, antes y después de instalar las funciones corregidas únicamente en un proceso independiente de diagnóstico. Se vació la caché del Excel de planeación antes de cada cálculo y se usó una transacción de solo lectura. La salida no incluyó nombres, documentos, credenciales ni contenido del HTML.

| Comparación | Antes | Después | Verificación del contenido |
| --- | ---: | ---: | --- |
| Cotas iniciales y lectura acotada de metadatos | 76,110 s | 13,946 s | HTML idéntico |
| Conjunto final, incluido TyT y consulta de versiones sin recuperación | 71,192 s | 9,281 s | HTML idéntico: 563.101 bytes |

La segunda comparación redujo el tiempo aproximadamente un 87 %. Cada fila corresponde a una pareja de ejecuciones, con variación del entorno y posible reutilización de cachés del sistema operativo. No mide latencia de red, navegador, cola de Gunicorn, percentil 95 ni concurrencia. Los 9,28 segundos restantes siguen siendo altos para una navegación habitual. En esta revisión se implementó una segunda etapa: extraer planeación y programa PDF una vez por versión, guardar esa extracción en PostgreSQL y reutilizar snapshots de fases y panorama. La vigencia se asocia al día, revisión de datos, algoritmo y huella de los archivos. Las cargas encolan el precálculo al worker; la primera visita también puede construirlo si Redis no está disponible.

Las mediciones de 9,28 segundos son anteriores a esta segunda etapa. El código nuevo y sus pruebas están locales en esta revisión; no se han medido contra Coolify ni se han desplegado.

### Extracciones documentales y snapshots persistentes

`archivos_ficha_versiones` conserva el original en el volumen y la extracción estructurada en PostgreSQL. El panel consulta primero la extracción persistida y no vuelve a abrir el Excel/PDF en visitas posteriores. Los juicios evaluativos ya residen como filas relacionales. Los cálculos del panorama y las fases se guardan en `resultados_calculados_ficha`, con revisión, fecha de corte, versión del algoritmo y huella de las fuentes. Los cambios ORM en ficha, aprendices, juicios y documentos suben la revisión. La importación masiva queda cubierta al confirmar el estado de la versión del reporte.

El worker precalienta panorama y fases después de una carga. Las fases no se pueden congelar en el día de la carga porque el tiempo lectivo avanza; el sistema crea una nueva clave al cambiar el día local de Bogotá. Si Redis falla, el resultado se calcula en la primera visita y queda guardado. Para archivos antiguos se agregó `scripts/backfill_documentos_persistidos.py`, que conserva los originales e informa cuáles faltan o no se pueden leer.

Las páginas autenticadas se entregan con `Cache-Control: private, no-store`. Se eliminó la precarga de HTML al pasar el puntero, que ejecutaba rutas antes del clic. Los recursos estáticos conservan caché pública de un año y su versión ahora es un SHA-256 del contenido; así cambian de URL aunque la fecha de modificación del archivo no cambie.

### Comparación sintética local

Prueba local con SQLite en memoria: 27 aprendices, 76 juicios por aprendiz (2.052 en total), 40 sesiones y 20 tareas que vencen en 24 horas. Cada petición usa su propio contexto y sesión ORM. Se calentó cada página una vez y se midieron tres peticiones completas. Las medianas incluyen renderizado; no incluyen red ni navegador. No se cargó un Excel de planeación en este conjunto.

| Página | Consultas antes → después | Mediana local antes → después |
| --- | ---: | ---: |
| Aprendices | 7 → 7 | 36,43 → 18,72 ms |
| Tareas | 85 → 14 | 62,96 → 21,05 ms |
| Juicios | 61 → 7 | 273,23 → 137,01 ms |

En aprendices el beneficio viene de reducir los registros transferidos y los objetos creados, aunque el número de consultas sea igual. En tareas y juicios se elimina alrededor del 84 % y del 89 % de las consultas del caso medido. Los tiempos muestran variación entre ejecuciones; no son una promesa de esos tiempos en producción.

El HTML sintético de juicios todavía pesa unos 818 KB sin comprimir y el directorio unos 254 KB. Las tablas y formularios completos siguen teniendo un costo de renderizado y de DOM. Una futura carga de detalles bajo demanda puede reducirlo, si los tiempos de producción después de estos cambios siguen excediendo el objetivo acordado.

## Base de datos y Redis

`config.py` usa `DATABASE_URL` para PostgreSQL y el arranque del contenedor espera una conexión mediante psycopg2. La base local confirmó PostgreSQL 18.4. Una consulta de solo lectura con `EXPLAIN (ANALYZE, BUFFERS)` sobre el nuevo agregado, en esa base local con 2.025 juicios y 27 aprendices, tardó 3,39 ms de ejecución. Esta cifra corresponde al entorno local y no permite afirmar que la base de Coolify responda igual. [PostgreSQL explica cómo interpretar estos planes](https://www.postgresql.org/docs/current/using-explain.html).

Ya existen índices para ficha y aprendiz en juicios, ficha e instructor en tareas y tarea en entregas. No se agregaron índices sin un plan de producción que demuestre su necesidad. Tampoco se requiere una migración de motor para aplicar estas correcciones.

Redis sostiene la cola de importaciones y el limitador de solicitudes. No almacena automáticamente los resultados de todas las páginas. Una conexión correcta a Redis no evita las consultas repetidas ni el análisis de Excel. Las importaciones ya tienen un worker separado y el timeout de lectura de la cola supera el bloqueo de `BLPOP`.

En producción se observaron 3 procesos de Gunicorn con 8 hilos por proceso. Sin overrides de pool, el código permite 4 conexiones y hasta 2 adicionales por proceso: un máximo de 18 conexiones frente a 24 hilos web. La espera del pool es de hasta 10 segundos y se verifica cada conexión al reutilizarla. No se observó saturación del pool en las muestras. Aumentar hilos no acelera por sí solo el trabajo de Python que consume CPU; puede aumentar la competencia y la espera de conexiones. Cualquier ajuste debe medirse con tráfico representativo.

## Instrumentación para comprobar producción

Se agregó `app/http_timing.py`, sin consultar datos adicionales. Las respuestas dinámicas incluyen:

```text
Server-Timing: app;dur=<MILISEGUNDOS>, sql;dur=<MILISEGUNDOS>, sql_queries;desc="<CONTEO>"
```

Si el tiempo supera `HTTP_SLOW_REQUEST_MS` (1.000 por defecto), aparece un registro `HTTP lento` con método, patrón de ruta, estado, tiempo total, tiempo SQL, cantidad de consultas y tamaño disponible. No se registran parámetros de URL, texto SQL, datos de aprendices ni credenciales. Los archivos estáticos conservan su caché y las descargas conservan el streaming.

`app` mide desde el inicio del procesamiento Flask hasta terminar los hooks de respuesta que se ejecutan antes del registro. `sql` mide la ejecución del cursor: no incluye toda la lectura de resultados, la materialización ORM, la espera de pool ni todos los viajes de red del driver. El tiempo de envío de un stream y la espera anterior a entrar a Flask tampoco quedan incluidos. La diferencia entre ambos tiempos orienta el perfilado; no identifica por sí sola una causa única.

`/health` incorpora `database_engine`, sin exponer la URI. El `200` del healthcheck se conserva y el estado detallado sigue en el JSON.

## Comprobaciones y aplicación en Coolify

La comprobación pública encontró `/health` conectado, `database_engine=postgresql`, Redis configurado y ningún error de arranque. Después del despliegue observado, `/login` respondió en 1,299 segundos con `app;dur=411.18` y `sql;dur=0.00`, y sirvió HTMX local. El navegador autenticado abrió el directorio de aprendices con el indicador oculto; su registro de servidor tardó 1,12 segundos.

Para aplicar las optimizaciones adicionales de RAP, TyT, metadatos y fases, se debe publicar esta revisión, reconstruir la imagen y desplegarla desde el flujo habitual de Coolify. Reiniciar la imagen anterior no incorpora estos archivos. El ajuste previo del indicador y la instrumentación ya se verificó desplegado; este diagnóstico no realizó un despliegue adicional.

Después del despliegue:

1. Conservar la variable Redis confirmada. Revisar `/health`: `status`, `database` y `database_engine` deben describir el estado esperado.
2. Abrir aprendices, tareas y juicios con una sesión de instructor. Revisar `Server-Timing` en la pestaña de red del navegador y los registros `HTTP lento`.
3. Si `sql` concentra la demora, medir red hacia PostgreSQL, consultas activas, bloqueos y planes de las consultas señaladas. Si predominan otros tiempos, perfilar CPU, renderizado, materialización, disco y espera de conexiones. Si Gunicorn registra mucho más tiempo que Flask, revisar espera y envío de respuesta.

Criterio de verificación propuesto: el contenido no queda cubierto al fallar un script, las funciones de QR y búsqueda se conservan y las consultas de tareas no crecen por tarjeta. El objetivo de latencia bajo carga debe acordarse con el tamaño de las fichas y los recursos del servidor.

## Cómo evitar que otras aplicaciones se vuelvan lentas

1. Registrar tiempo HTTP, tiempo SQL y número de consultas por ruta. Revisar el percentil 95 con tráfico real; un healthcheck rápido no representa todas las páginas.
2. Procesar importaciones, reconstrucciones de archivos y análisis extensos en workers. Una lectura de página debe usar resúmenes preparados y consultar su vigencia.
3. Evitar consultas por cada tarjeta o fila. Agrupar conteos, precargar relaciones y paginar tablas; cargar formularios y detalles cuando se solicitan.
4. Mantener las dependencias esenciales de la interfaz disponibles localmente. Un error de JavaScript debe permitir leer la página y mostrar cómo continuar.
5. Acotar las cachés y definir su invalidación cuando dependen de datos. Una caché de texto puro es distinta de una instantánea de juicios que puede quedar desactualizada.
6. Medir CPU, memoria, disco, bloqueos y conexiones durante la demora antes de aumentar recursos o cambiar de motor de base de datos.
7. Probar cada cambio con datos representativos, una primera petición sin caché y usuarios concurrentes. Comparar resultados y efectos, además del tiempo.

## Pruebas

Las regresiones se escribieron y fallaron antes de las correcciones. Se probaron agregados y resultados reales, alertas equivalentes, ausencia de análisis ajeno al módulo, consultas acotadas, integridad y caché de librerías, registros HTTP sin datos privados, descargas por stream y liberación de aplicaciones descartadas por la instrumentación. Las 15 nuevas pruebas de `test_rendimiento_planeacion.py` comprueban equivalencia y límites del emparejamiento, reutilización del texto, archivos XLS/XLSX, errores y lectura de fases sin recuperación. Estas pruebas pertenecen a la suite y al flujo de CI existente.

Resultado de la verificación final:

- Python: 587 pruebas aprobadas y una omisión preexistente en `test_fases_dashboard.py`, que depende de una ficha ausente en su base de prueba. Cobertura total: 82,81 %, por encima del umbral existente de 75 %. La suite completa tardó 560,97 segundos.
- Compuerta de funciones de Python: 609 de 609 ejecutadas, 100 %.
- JavaScript: 34 pruebas aprobadas; cobertura de funciones del 100 % en los módulos incluidos por las pruebas. El indicador tiene cobertura del 100 % de líneas y funciones.
- Navegador: 5 pruebas aprobadas, incluidas las tres regresiones de carga del directorio. Se regeneraron las páginas de prueba con datos sintéticos y se ejecutaron con `PANEL_TEST_BROWSER_CHANNEL=chrome` en Windows; CI instala Chromium con Playwright. La primera ejecución sin ese ajuste falló porque el Chromium de Playwright no estaba instalado, antes de ejecutar el comportamiento de las páginas.
- Consulta PostgreSQL de solo lectura y `git diff --check`: completados correctamente.

No se modificaron los umbrales ni se agregaron omisiones para obtener resultados favorables. Las pruebas heredadas de archivos pueden dejar XLSX sin seguimiento en `uploads`; esos archivos requieren revisión antes de preparar una publicación y se conservaron junto con los cambios de otras tareas presentes en el workspace.

La compuerta global `Test-DevBrainLegalLifecycle.ps1`, ejecutada en modo `Audit` según las reglas del workspace, terminó con cuatro advertencias y sin bloqueadores. Faltan los dos archivos de estado legal del proyecto y la revisión registrada de los archivos señalados por el detector. Este resultado no certifica una liberación; queda documentado para el flujo de publicación y no explica la demora de la aplicación. Evidencia local: `test-results/legal_audit_coolify.json`.
