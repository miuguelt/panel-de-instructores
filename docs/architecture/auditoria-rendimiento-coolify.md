# Auditoría de rendimiento en Coolify

Fecha: 1 de octubre de 2026. Página reportada: `/instructor/fichas/2/aprendices`.

## Resultado y alcance

Se encontraron y corrigieron dos fuentes de demora en el código: el bloqueo inicial del navegador por scripts externos y consultas y cálculos repetidos al construir páginas. La aplicación está configurada para PostgreSQL. Cambiar de motor no resuelve estos problemas. Se conserva `REDIS_URL=redis://redis:6379/0`, confirmada por el operador.

Se revisaron plantillas, scripts de carga, consultas de aprendices, tareas y juicios, recomendaciones, análisis de planeación, configuración de conexiones, compresión, caché de estáticos, Gunicorn, importaciones y Docker Compose. Las mediciones con datos autenticados se realizaron en una base sintética aislada. Las comprobaciones públicas de producción no incluyeron una sesión de instructor. Por eso aún no se atribuye una proporción exacta de los 20 segundos observados a CPU, consultas, disco, red o espera de conexiones en el servidor de Coolify.

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

### 2. Demasiadas consultas para el tablero de tareas

El tablero leía relaciones de grupos por cada tarea. El evaluador consultaba el número de entregas una vez por cada tarea próxima a vencer. La ruta obtenía recomendaciones de todos los módulos y la plantilla las volvía a solicitar.

Ahora se precargan grupos, responsables y cortes; los conteos de entregas se agrupan en una consulta; y la plantilla recibe las recomendaciones que ya preparó la ruta. La carga de relaciones en conjunto evita consultas por objeto, como explica [SQLAlchemy sobre `selectinload`](https://docs.sqlalchemy.org/en/20/tutorial/orm_related_objects.html).

### 3. Cálculos de planeación en páginas que no los muestran

Las recomendaciones de tareas y juicios también calculaban fases. Cuando existe una planeación, ese recorrido puede leer el Excel y construir el análisis que combina unidades, aprendices y juicios. Se repetía parte del recorrido al renderizar las alertas de la plantilla. La caché del Excel parseado no evitaba reconstruir todo el análisis.

`obtener_recomendaciones_ficha` admite ahora categorías. Las páginas de tareas y juicios piden solo su módulo. Los demás módulos también solicitan su categoría desde el helper de plantilla. El llamado sin categorías conserva todas las recomendaciones para las vistas generales. La cache del helper dura una petición y distingue ficha y categoría.

### 4. El directorio cargaba cada juicio para obtener solo conteos

Aprendices materializaba todos los registros de juicios en Python para calcular cantidades y porcentajes. Ahora PostgreSQL devuelve un agregado por aprendiz con `COUNT`, `SUM` y `GROUP BY`. Se conservan los filtros por estado, los aprendices sin juicios, los porcentajes y la regla histórica de aprobación del directorio.

La diferencia entre tiempo de consulta, transferencia y materialización de objetos es relevante para este caso; [SQLAlchemy documenta cómo distinguirlos al perfilar](https://docs.sqlalchemy.org/en/20/faq/performance.html).

## Mediciones antes y después

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

La configuración prevista de Gunicorn es 2 procesos con 4 hilos cada uno. El pool SQL tiene 4 conexiones y hasta 2 adicionales por proceso, espera hasta 10 segundos y verifica conexiones al reutilizarlas. La capacidad real de CPU, RAM, disco, conexiones y ubicación de la base de Coolify queda pendiente de medición. Aumentar procesos sin conocer esos recursos puede aumentar la competencia por memoria y conexiones.

## Instrumentación para comprobar producción

Se agregó `app/http_timing.py`, sin consultar datos adicionales. Las respuestas dinámicas incluyen:

```text
Server-Timing: app;dur=<MILISEGUNDOS>, sql;dur=<MILISEGUNDOS>, sql_queries;desc="<CONTEO>"
```

Si el tiempo supera `HTTP_SLOW_REQUEST_MS` (1.000 por defecto), aparece un registro `HTTP lento` con método, patrón de ruta, estado, tiempo total, tiempo SQL, cantidad de consultas y tamaño disponible. No se registran parámetros de URL, texto SQL, datos de aprendices ni credenciales. Los archivos estáticos conservan su caché y las descargas conservan el streaming.

`app` mide desde el inicio del procesamiento Flask hasta terminar los hooks de respuesta que se ejecutan antes del registro. `sql` mide la ejecución del cursor: no incluye toda la lectura de resultados, la materialización ORM, la espera de pool ni todos los viajes de red del driver. El tiempo de envío de un stream y la espera anterior a entrar a Flask tampoco quedan incluidos. La diferencia entre ambos tiempos orienta el perfilado; no identifica por sí sola una causa única.

`/health` incorpora `database_engine`, sin exponer la URI. El `200` del healthcheck se conserva y el estado detallado sigue en el JSON.

## Comprobaciones y aplicación en Coolify

La comprobación pública encontró `/health` conectado, Redis configurado y clave de sesión válida. `/login` y los estilos ya se sirven comprimidos. El directorio solicitado redirige al login cuando no hay una sesión autenticada; no se midió su tiempo real en producción.

Para aplicar los cambios, la imagen debe reconstruirse con esta revisión y desplegarse desde el flujo habitual de Coolify. Reiniciar una imagen anterior no incorpora los nuevos archivos. Los cambios permanecen locales hasta publicar y desplegar la revisión.

Después del despliegue:

1. Conservar la variable Redis confirmada. Revisar `/health`: `status`, `database` y `database_engine` deben describir el estado esperado.
2. Abrir aprendices, tareas y juicios con una sesión de instructor. Revisar `Server-Timing` en la pestaña de red del navegador y los registros `HTTP lento`.
3. Si `sql` concentra la demora, medir red hacia PostgreSQL, consultas activas, bloqueos y planes de las consultas señaladas. Si predominan otros tiempos, perfilar CPU, renderizado, materialización, disco y espera de conexiones. Si Gunicorn registra mucho más tiempo que Flask, revisar espera y envío de respuesta.

Criterio de verificación propuesto: el contenido no queda cubierto al fallar un script, las funciones de QR y búsqueda se conservan y las consultas de tareas no crecen por tarjeta. El objetivo de latencia bajo carga debe acordarse con el tamaño de las fichas y los recursos del servidor.

## Pruebas

Las regresiones se escribieron y fallaron antes de las correcciones. Se probaron agregados y resultados reales, alertas equivalentes, ausencia de análisis ajeno al módulo, consultas acotadas, integridad y caché de librerías, registros HTTP sin datos privados, descargas por stream y liberación de aplicaciones descartadas por la instrumentación. Chromium comprobó el directorio con CDN inaccesibles, QR y descarga PNG, scripts pendientes y JavaScript deshabilitado. Estas pruebas se incorporaron a la suite y al flujo de CI existente.

Resultado de la verificación final:

- Python: 572 pruebas aprobadas y una omisión preexistente en `test_fases_dashboard.py`, que depende de una ficha ausente en su base de prueba. Cobertura total: 82,75 %, por encima del umbral existente de 75 %.
- Compuerta de funciones de Python: 607 de 607 ejecutadas, 100 %.
- JavaScript: 34 pruebas aprobadas; cobertura de funciones del 100 % en los módulos incluidos por las pruebas. El indicador tiene cobertura del 100 % de líneas y funciones.
- Navegador: 5 pruebas aprobadas, incluidas las tres regresiones de carga del directorio. Se ejecutaron con Chrome sin interfaz en Windows; CI instala Chromium con Playwright.
- Consulta PostgreSQL de solo lectura y `git diff --check`: completados correctamente.

No se modificaron los umbrales ni se agregaron omisiones para obtener resultados favorables. Las pruebas heredadas de archivos pueden dejar XLSX sin seguimiento en `uploads`; esos archivos requieren revisión antes de preparar una publicación y se conservaron junto con los cambios de otras tareas presentes en el workspace.
