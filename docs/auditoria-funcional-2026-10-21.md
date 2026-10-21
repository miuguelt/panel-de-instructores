# Auditoría funcional y de pruebas del panel de instructores

Fecha: 21 de octubre de 2026.

La revisión abarca las rutas, los servicios, los modelos, TyT, las funciones de
personalización y experiencia, los módulos JavaScript, las plantillas y los
procesos de arranque e importación. El inventario estático permite ubicar las
funciones; la revisión manual se concentra en permisos, validación, cálculos,
transacciones, archivos, respuestas y recuperación de errores. Ninguno de esos
dos pasos, por separado, certifica todos los resultados posibles.

## Problemas corregidos

| Área | Problema comprobado | Resultado de la corrección |
| --- | --- | --- |
| Aislamiento | Un turno o una tarea de otra ficha podía usarse desde una ruta autorizada para una ficha distinta. | Se comprueba la pertenencia del registro antes de leerlo o modificarlo. |
| Identidad | El documento enviado por un formulario podía contradecir al aprendiz de la sesión. | Se rechaza el conflicto antes de guardar soportes o intercambios. |
| Transacciones | Se archivaban grupos, cambiaban turnos o eliminaban archivos antes de completar el registro relacionado. | Se confirma la operación completa y se conservan los datos anteriores ante una falla. |
| Rendimiento | Con una sola medición se inventaba un punto anterior y una tendencia. | Se conserva el único registro real y se indica que aún no hay tendencia. |
| Indicadores | Un SPI de cero se reemplazaba por uno y la cobertura de horas se mostraba completa sin denominador. | Se conserva el cero y se informa la ausencia de referencia cuando corresponde. |
| Historial | La reconstrucción de un reporte podía usar la fecha de importación como fecha del juicio académico. | Se conserva la fecha del juicio y se comprueba la lectura del documento de identidad. |
| Validación | Se aceptaban valores no finitos, desbordamientos, tipos JSON incorrectos y fechas imposibles. | Se rechazan antes de modificar los datos y se devuelve un mensaje accionable. |
| Recuperación | Algunos metadatos no coincidían con el parser y podían quedar archivos huérfanos. | Se usan las claves reales del parser, se valida el programa y se limpian únicamente archivos nuevos no confirmados. |
| Interfaz | Había formularios bloqueados, HTML interpretado desde datos, eventos duplicados y un formulario sin CSRF. | Se permiten reintentos, los textos se presentan literalmente y se incorpora el token requerido. |
| Importaciones | Un indicador secundario podía convertir una importación guardada en un error; las consultas podían agotarse sin avisar. | El trabajo conserva su resultado, informa advertencias y ofrece consultar o actualizar la vista. |
| Configuración | Existían valores de respaldo fijos para conexión, sesión e identidad del administrador. | La conexión y el correo se exigen desde el entorno; una clave de sesión ausente se sustituye por una clave aleatoria temporal y se señala la configuración pendiente. |
| Diagnóstico | El estado público de salud podía incluir el texto interno de una falla de conexión. | Se informa la indisponibilidad y la clase del error sin publicar detalles de la conexión. |
| Mantenimiento | El archivo de rutas de planeación superaba el límite de tamaño del proyecto. | Sus funciones de apoyo se trasladan a un módulo independiente; se conservan los contratos HTTP y sus pruebas. |

## Qué comprueban las pruebas

- Las pruebas de integración ejecutan las rutas y los servicios de producción
  contra una base SQLite real, archivos temporales y documentos XLSX o PDF
  generados para la prueba. No consultan registros académicos operativos.
- Las regresiones de atomicidad utilizan restricciones y disparadores SQLite
  para provocar fallas reales de persistencia. Se comprueban el registro, el
  archivo y la conservación del estado anterior.
- La prueba de asignación del rol administrativo ahora importa un XLSX real:
  comprueba el juicio guardado, el rol y los bytes del archivo original. Antes
  reemplazaba el parser, la importación y el versionado por resultados preparados.
- La recuperación desde disco debe producir una versión. Se retiró una
  condición que permitía omitir todas las aserciones si no se recuperaba nada.
- La prueba del historial dejó de exigir un punto inventado. Ahora exige un
  solo punto y una diferencia de cero cuando existe una única medición.
- La atención se comprueba con CSRF habilitado: un envío sin token conserva el
  turno y el envío con el token leído del formulario cambia su estado.
- Los cinco ordenamientos de equidad se comprueban en las tres vistas con
  resultados diferentes, fechas ausentes y métricas visibles. El historial y
  el PDF comprueban el orden de las competencias y el aislamiento entre
  aprendices. Las fases adicionales se leen de un XLSX real y conservan sus
  horas y resultados.
- Las pruebas de navegador de la auditoría ejecutan scripts y fragmentos Jinja
  vigentes. Las respuestas HTTP controladas aíslan el contrato del cliente;
  las pruebas de servidor comprueban por separado su persistencia.
- Los dobles de prueba se usan para fallas externas o de infraestructura y para
  pruebas unitarias de coordinación. Una prueba con ese límite no se presenta
  como certificación de un servicio externo funcionando.

## Medición y ejecución continua

El reporte de líneas se mantiene con el umbral existente del 75 %. La compuerta
de funciones incorpora un registro de invocaciones reales por prueba aprobada,
incluye callbacks `lambda` y los módulos de configuración, trabajador,
entrada web y creación de administrador. Crear un callback sin ejecutarlo no
cuenta como cubrirlo. El registro no almacena argumentos ni resultados.

El flujo de integración continua configurado ejecuta la suite Python, todas las pruebas JavaScript,
las pruebas de navegador y las compuertas de funciones de los módulos cliente
trabajados. Publica el reporte de cobertura y el registro de invocaciones.

## Límites y decisiones conservadas

Los umbrales institucionales, los estados académicos, los formatos admitidos y
las constantes de calendario se distinguen de datos inventados. No se modifican
por parecer números fijos: requieren el contrato del producto o la fuente
institucional correspondiente. Esta revisión no valida su vigencia normativa.

El acceso heredado del aprendiz por documento y la consulta pública de aseo
mantienen sus contratos actuales. Cambiar ese modelo de acceso requiere una
decisión general de autenticación y privacidad.

## Configuración local y credenciales

Con autorización del operador, se comprobó que PostgreSQL estaba detenido y
se ejecutó el arranque canónico de DevBrain. La credencial de Windows permitió
autenticar al rol exclusivo del panel. Se rotó la contraseña de ese rol y se
guardó una clave de sesión persistente. Las credenciales de los roles
compartidos conservaron sus valores.

Windows Credential Manager conserva los valores del panel. El archivo `.env`
local que necesita Flask quedó actualizado, excluido de Git y protegido con
permisos de la cuenta del operador y SYSTEM. Se comprobó la coincidencia entre
el almacén y la configuración local, la retirada de la contraseña anterior y
la carga de una clave de sesión persistente. Los valores no se incluyen en
este informe ni en los registros de diagnóstico.

La conexión y el estado de salud se verificaron contra PostgreSQL real. La
prueba de integración de TyT creó un esquema temporal y comprobó cálculo,
destinatarios, idempotencia y actualización. Finalmente revirtió la
transacción y confirmó que el esquema ya no existía. No modificó registros
académicos operativos.

## Evidencia de cierre

| Verificación | Resultado |
| --- | --- |
| Suite Python completa final | 1.103 pruebas aprobadas en 13 minutos y 51 segundos, después del último cambio de producción. |
| Regresiones enfocadas | 26 pruebas de callbacks y runtime, y 169 pruebas afectadas por la reorganización de planeación, aprobadas. También están incluidas en la suite final. |
| Funciones y callbacks Python | 811 de 811 invocados por pruebas aprobadas: 100 %. Incluye `app`, `config.py`, `worker.py`, `wsgi.py` y `seed_admin.py`. |
| Cobertura conjunta de líneas y ramas | 86,93 %, superior al umbral existente del 75 %. No equivale a cubrir todas las ramas. |
| JavaScript | 120 pruebas aprobadas. Los módulos nuevos de portapapeles e importaciones alcanzan el 100 % de funciones y líneas. |
| Navegador real | 41 pruebas aprobadas en Microsoft Edge, incluida la recuperación de sesión tras una redirección HTTP real. |
| PostgreSQL local | Conexión, health e integración con reversión aprobados. |
| Escaneo de secretos | 430 archivos de texto dentro de un árbol de 582 archivos versionados o nuevos no ignorados; ningún hallazgo del escáner canónico. No incluye archivos binarios ni el historial Git. |
| Modularidad | Sin errores en los archivos modificados; se conservan 32 advertencias de estructura heredada. |
| Índice de código | Índice del proyecto `adso` actualizado con la herramienta canónica. |

La cobertura combina la suite completa, las regresiones adicionales y 169
pruebas posteriores a la reorganización de planeación. Se retiraron los datos
anteriores de los archivos reorganizados antes de medirlos otra vez, para
evitar atribuir ejecución a líneas o funciones antiguas. Después se volvió a
ejecutar la suite completa de 1.103 casos sobre el código final y pasó. La
ejecución de CI incluye todas las pruebas juntas y aplica las mismas
compuertas. Su ejecución remota queda pendiente hasta publicar los cambios.

La verificación canónica rápida aprobó sus controles críticos de sintaxis y
modularidad. Su auditoría heurística emitió 15 avisos por valores de prueba y
una expresión regular, además de dos avisos de codificación en una copia
temporal de `xlwt`. Estos avisos se distinguen del escáner canónico de
credenciales. Se conservaron sus reglas y umbrales. Ese comando omite la suite
completa; las pruebas de esta entrega se ejecutaron con las herramientas
nativas descritas arriba.

Los registros locales están en `test-results/auditoria-suite-final.log`,
`test-results/auditoria-suite-completa.log`,
`test-results/auditoria-suplementos.log`,
`test-results/auditoria-planeacion-final.log`,
`test-results/auditoria-js-final.log`,
`test-results/auditoria-navegador-final.log`,
`test-results/auditoria-secretos.json` y
`test-results/function-calls.json`. El reporte de líneas y ramas está en
`coverage.xml`.
