# Seguimiento del hito del 70 % para Saber TyT

## 01_PLAN
Comparar el tiempo de la etapa lectiva, desde la inducción, con el promedio de resultados aprobados,
mostrar resultados evaluados por separado y publicar avisos internos del hito.
El indicador apoya la preparación; no certifica requisitos de inscripción.

## 02_PRD · Criterios de aceptación
- Dado un calendario válido, cuando transcurren al menos el 70 % de sus días lectivos
  inclusivos, entonces se activa el hito exactamente en el día calculado,
  independientemente del redondeo visual. La fecha se interpreta en Colombia.
- El 100 % corresponde al último día lectivo y permanece en 100 % después.
  La etapa productiva se presenta aparte con sus seis meses y sus fechas,
  sin barra ni porcentaje. No participa en el denominador ni en la alarma TyT.
- Un calendario cuya etapa productiva deja una etapa lectiva vacía se informa
  como inválido; no se inventa un hito ni se genera una notificación.
- Dados los resultados distintos del reporte de una ficha, cuando se calcula
  cada aprendiz activo, entonces la meta es `ceil(total * 0.70)`; un resultado
  ausente cuenta pendiente y un juicio no aprobado cuenta evaluado, no aprobado.
- Dados dos registros del mismo resultado, cuando se recalcula, entonces solo
  se usa el último importado. Un promedio alto no oculta aprendices rezagados.
- Dada una ficha sin resultados o sin fechas válidas, entonces se informa la
  ausencia de datos sin afirmar cumplimiento ni inventar un porcentaje.
- Dado el hito, cuando se revisa repetida o simultáneamente, entonces cada
  instructor vinculado y aprendiz activo recibe un solo aviso por hito y fecha.
- Dado un aprendiz, entonces solo accede a su detalle; un instructor ajeno
  recibe 403 al consultar el grupo y una ficha inexistente devuelve 404.
- Cuando cambian juicios, fechas o matrícula, la siguiente consulta y revisión
  recalculan el progreso desde la base de datos, sin caché entre peticiones.

## 03_USER_FLOWS
Instructor: tarjeta → detalle por aprendiz → juicios evaluativos.
Aprendiz: panel → progreso propio → resultados por competencia existentes.
Estados: datos disponibles, sin datos con orientación, error con reintento;
renderizado del servidor, sin estado artificial de carga ni confirmación de escritura.

## 04_TRD
Una funcionalidad `app/tyt/` separa cálculo puro, lectura de juicios, notificaciones
y entrada web. Las plantillas consumen el mismo contrato. El cronograma y el
worker invocan las notificaciones; el cálculo no depende de estos consumidores.
`app/services/periodo_formacion.py` resuelve las fechas y el porcentaje lectivo
para cronograma y TyT. Su cálculo es puro y no depende de alertas ni persistencia.
El contrato `porcentaje`/`dias_totales`/`dias_transcurridos` del cronograma ahora
corresponde únicamente a la etapa lectiva; las fechas de la productiva y los
días restantes de toda la ficha conservan sus campos separados. Los indicadores
de instructor y aprendiz identifican expresamente su porcentaje como lectivo.
El hito de la ficha 3235642 es el 14/10/2026, con cierre lectivo el 23/04/2027;
la fase adicional productiva va del 24/04/2027 al 24/10/2027 y dura seis meses.
Las claves de notificación usan `lectiva70` para distinguir la nueva base de
cálculo de los avisos históricos calculados sobre la duración total.
El catálogo es la unión de RAP distintos del reporte entre aprendices activos,
no un catálogo oficial supuesto. La interfaz declara esa base. Se excluyen
retirados y trasladados; se incluyen condicionados e inducción conforme al
contrato de estados académicos activos del proyecto.
El registro de rutas se extrae a `app/routes/__init__.py` para conectar el módulo
sin ampliar la función de creación de la aplicación. Las notificaciones se
actualizan antes de cargar las vistas y durante la revisión del cronograma;
las plantillas solo leen. Así se evita invalidar objetos ORM a mitad del
renderizado y provocar consultas por cada aprendiz.
El worker existente revisa el hito cada cinco minutos. Los fallos de esa revisión
se registran y no interrumpen la cola de importaciones. Con el worker detenido,
la revisión también ocurre al entrar al panel y al actualizar los juicios.
Los avisos son internos, con campana y advertencia visible; no reproducen sonido
ni envían correos. Su texto conserva el estado de la revisión que detectó el
hito; la tarjeta y el detalle siempre presentan el progreso actual.

## 05_SQL
Se reutilizan tablas y restricciones existentes. La notificación única por
destinatario y clave se inserta con savepoint para tolerar revisiones concurrentes.
Sin migración. Autorización en servidor con los permisos de ficha existentes.
Los mensajes de aprendices contienen únicamente su propio progreso.

## 06_STITCH · Diseño
Visualización de datos con tarjetas institucionales: barras sobre la misma
escala 0–100, marca fija del 70 %, contadores de brecha y aviso con campana.
Tokens del tema vigente, estados con texto e icono y adaptación desde 320 px.

## 07_AISTUDIO · Contrato de implementación
Mantener cálculos verificables, fechas de Colombia, lectura autoritativa,
privacidad individual y avisos idempotentes. No interpretar un juicio pendiente
como evaluado ni aprobación automática para presentar la prueba.

## Verificación de esta implementación
- Pruebas de cálculo, autorización, privacidad, primera carga del contador,
  revisión periódica e idempotencia en `tests/test_tyt_*.py`.
- Prueba real PostgreSQL: `python scripts/verify_tyt_postgres.py`. Crea un esquema
  dentro de una transacción externa, prueba destinatarios, colisión de clave
  única y refresco de datos; revierte todo y comprueba que el esquema desapareció.
- Regresión de consultas por aprendiz: `tests/test_rendimiento.py`.
- Renderizado con datos persistidos de la ficha 3235642, en transacción de solo
  lectura. Capturas de tarjeta, detalle y vista personal en 320, 390, 768, 1440,
  1920 y 2560 px, temas SENA y oscuro, y ampliación del 200 %.
- Auditoría específica con Playwright y axe: sin desbordamiento, errores de
  JavaScript ni violaciones WCAG en los componentes TyT; búsqueda y filtros
  comprobados. Evidencia local bajo `test-results/tyt-ui/` (ignorada por Git).
- El auditor de página completa conserva problemas de contraste en elementos
  previos, como el contador de notificaciones y las métricas del panel. La
  auditoría de calidad también marca tres posibles secretos en líneas previas
  de pruebas y en un comentario de `app/__init__.py`; no se alteraron esas líneas.
- Sin migraciones de producción ni envío de mensajes durante la verificación.
  La actualización del servidor y su worker activa el comportamiento en uso.
