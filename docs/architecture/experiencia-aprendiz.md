# Recorrido y motivación del aprendiz

Fecha: 7 de octubre de 2026.

## 01_PLAN: alcance y responsables

El inicio permite identificar una acción útil, entender el estado de las evidencias, seguir una meta semanal y recuperar los ajustes desde otra sesión. Se conservan la personalización visual, los juicios oficiales, los trabajos grupales y las rutas de entrega vigentes.

| Capa | Responsable | Entradas y salidas | Verificación |
| --- | --- | --- | --- |
| Datos y API | Módulo `experiencia_aprendiz` | Identidad de sesión, preferencias y revisión; estado confirmado e hitos permanentes | Persistencia, concurrencia, permisos, CSRF y reversibilidad |
| Proyección | `context.py` | Entregas, plazos efectivos, competencias y grupo; siguiente acción y progreso | Correcciones, fechas de Colombia, aula, grupos y estados vacíos |
| Interfaz | Parcial y controlador de experiencia | Estado del servidor; acciones y ajustes confirmados | Reintentos, conflictos, continuidad, teclado y adaptación |
| Avisos | Centro de notificaciones | Registros y modo de lectura; grupos por fecha y tema | Aislamiento, lectura idempotente, errores y contexto de pestaña |

Datos/API preceden la integración de interfaz. La proyección utiliza información académica ya consultada por el panel. Las suites existentes y CI verifican la integración completa.

## 02_PRD: aceptación observable

- Dada una evidencia devuelta, al abrir el panel aparece antes que otras actividades y su acción abre los ajustes solicitados.
- Dada una entrega recibida sin revisión, el aprendiz ve «Recibida · En revisión»; enviar y aprobar se distinguen.
- Dada una meta semanal, el progreso cuenta actividades individuales con envío registrado esta semana, incluyendo ajustes reenviados; cada actividad cuenta una sola vez. Las actividades de aula y los envíos futuros no incrementan la meta.
- Dado un hito alcanzado por cantidad de evidencias digitales distintas, permanece registrado aunque cambie el conteo. Su reconocimiento no cambia los juicios.
- Dado un grupo con trabajos asignados, el avance colectivo cuenta trabajos entregados y orienta a los trabajos existentes.
- Dados ajustes guardados, otra sesión y un reinicio recuperan la meta, el modo de avisos, el ranking opcional, el movimiento, el espaciado y la continuidad.
- Dado un conflicto, error o cambio de aprendiz, el borrador permanece y no se anuncia un guardado exitoso.
- Dado un acceso directo a una evidencia, los filtros se limpian y el acordeón se abre para revelar y enfocar la tarjeta.
- Dados avisos importantes, permanecen visibles en todos los modos; los adicionales quedan consultables por fecha y tema.
- Dado un ancho de 320 a 2560 px o zoom del 200 %, la experiencia conserva texto, controles y ancho de página.

## 03_USER_FLOWS: estados y recuperación

Inicio → siguiente acción → evidencia → envío → confirmación → revisión del instructor. El estado de recepción se deriva de la entrega persistida; el estado aprobado depende de la revisión registrada.

Los ajustes parten del estado guardado. Al cambiar un control o la ubicación se agrupan los cambios durante 600 ms; el estado indica guardado en curso y solo aplica el resultado tras confirmar el servidor. Un error ofrece reintentar; HTTP 409 ofrece recargar antes de escribir. La vista vacía explica qué aparecerá y mantiene una acción de consulta. Los detalles secundarios conservan el inicio breve.

## 04_TRD: contratos y límites

Se mantiene Flask/Jinja/SQLAlchemy. `GET /aprendiz/<ficha_id>/experiencia` devuelve `ok`, `preferences` y `revision`. `POST` recibe únicamente `preferences` y `revision`, con CSRF y `X-Learner-Id`; la identidad sigue siendo la de la sesión. Una revisión obsoleta no sobrescribe preferencias. Las respuestas son privadas y no se almacenan en caché.

Las preferencias son `weeklyGoal` (0 a 20), `notificationMode` (`all`, `important`, `quiet`), `rankingVisible`, `reducedMotion`, `density` y `resume`. Una tarea de continuidad debe ser individual, de la ficha y de la pestaña `evidencias`; otras pestañas usan `taskId: null`.

Los hitos se actualizan con una unión monotónica separada de la revisión de preferencias. Las carreras de creación y actualización se resuelven con restricciones y comparación atómica. Los conteos no usan información enviada por el cliente. La semana y los avisos se presentan en Colombia; el redondeo porcentual coincide entre Python y JavaScript.

La navegación emite `learner:navigate` y la integración revela la tarjeta. Los saltos existentes y la navegación móvil emiten `learner:location` para conservar continuidad. Las alertas críticas no se ocultan al reducir avisos. Ocultar ranking modifica la vista propia; no cambia la visibilidad del aprendiz para otros usuarios.

## 05_SQL: persistencia y migración

`r41experienciaaprendiz`, descendiente de `q40personalizacionaprendiz`, crea `experiencias_aprendiz` con clave foránea al aprendiz, preferencias JSON/JSONB, revisión positiva e hitos JSON/JSONB. La reversión elimina únicamente esa tabla; las pruebas preservan los registros académicos. La eliminación del aprendiz elimina también su experiencia.

Este proyecto conserva su autorización por sesión en Flask; no introduce Supabase ni otro proveedor. El despliegue habitual debe aplicar la migración antes de servir esta versión.

## 06_STITCH: diseño implementado

Se aplica el estilo Bento y los temas de `DESIGN.md` en el código existente. La acción principal y la meta ocupan tarjetas fluidas; competencias, hitos y preferencias secundarias usan detalles desplegables. Los controles se operan con teclado, tienen objetivos táctiles de 44 px y respetan movimiento reducido. El contraste de las acciones se calcula con el primer plano del acento. Se corrigieron además el ancho de las tarjetas del portafolio y la distribución del calendario en celular.

## 07_AISTUDIO: integración y evidencia

La implementación utiliza el runtime vigente sin generar una segunda aplicación. Python, JavaScript y Playwright verifican resultados y efectos de las mismas rutas utilizadas por el aprendiz. Los reportes de esta ejecución se encuentran en `test-results/`, y la CI incluye las pruebas, los reportes de cobertura y las capturas del recorrido.

| Comprobación ejecutada | Resultado y alcance |
| --- | --- |
| Suite completa de Python con cobertura de ramas | 893 pruebas aprobadas; cobertura conjunta de líneas y ramas del 84,92 %, superior al umbral vigente del 75 % |
| Compuerta nativa de funciones Python | 691 de 691 funciones de producción alcanzadas: 100 % |
| Suite completa de JavaScript con cobertura nativa | 87 pruebas aprobadas; 100 % de funciones en los archivos medidos |
| Suite completa de navegador | 22 recorridos aprobados con SQLite aislado y servidor real; incluye personalización, foto, reinicio, sesiones, conflictos y experiencia |
| Revisión final de avisos | 23 pruebas de integración aprobadas y recorrido de navegador repetido tras ajustar iconos SVG y hora colombiana de 12 horas |
| Adaptación visual | Sin desbordamiento de página en 320, 390, 768, 1440, 1920 y 2560 px, y al 200 % de zoom; contraste de acción de avisos de al menos 4,5:1; espaciado perimetral verificado en las vistas cómoda y compacta |
| Migración | Creación, reversión y cadena de revisiones verificadas en pruebas; compuerta estricta aplicada directamente al archivo nuevo |

Los mensajes de carga inicial y guardado confirmado se prueban por separado: una revisión cero no se presenta como un guardado persistido. Tras el último ajuste de espaciado, se repitieron los seis recorridos de experiencia en navegador: todos aprobados. La comprobación final repite únicamente los límites afectados por los últimos ajustes de plantilla y estilo, sin sustituir la suite completa ya ejecutada.

La verificación automatizada cubre persistencia y uso de los controles con datos preparados en una base aislada. No equivale a una observación de aprendices reales ni a un despliegue de producción. La evaluación de facilidad de uso puede medir tiempo para encontrar una actividad, abandono de entregas y consultas sobre guardados, sin agregar registros de comportamiento individual en este cambio.
