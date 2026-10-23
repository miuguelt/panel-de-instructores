# Diseño de SENA Control

## Contrato de diseño — sistema visual de superficies translúcidas, botones y bordes (23 de octubre de 2026)

- Dirección visual: un mismo sistema de capas para toda la aplicación. Las superficies de vidrio se calibran por tema para que el texto conserve contraste AA sobre el color compuesto, los datos tabulares viven en superficie sólida y los controles comparten una sola escala de radios, alturas y bordes. La identidad SENA (verde, naranja y neutros) se expresa con tokens, no con colores escritos en las plantillas.
- Capas de superficie (de atrás hacia adelante):
  - `--bg-base`: lienzo del tema. Es la referencia para calcular el contraste compuesto.
  - `--surface-glass-subtle`, `--surface-glass` y `--surface-glass-strong`: vidrio de 0.55–0.58, 0.74–0.82 y 0.86–0.91 de alfa. A mayor elevación, más opaca: el contenido crítico nunca queda sobre el vidrio más transparente.
  - `--surface-glass-overlay`: capa opaca del tema para overlays de modal y barras fijas.
  - `--surface-data`: superficie sólida (blanco en temas claros, 0.96 en el tema oscuro) para tablas, filas y celdas donde el dato debe leerse sin ruido del fondo.
  - `--surface-control`: fondo de botones e inputs; `--surface-hover` y `--surface-selected`: realce de interacción; `--surface-header`: cabecera de tabla.
  - Bordes: `--border-divider` (separación interna), `--border-data` (filas), `--border-glass` (tinte del acento sobre vidrio) y `--border-control` (borde de controles, contraste >= 3:1 sobre la superficie compuesta).
- Tokens del sistema (fuente única: `app/static/css/styles.css`):
  - Radios: `--radius-xs` 6 px, `--radius-sm` 10 px, `--radius-md` 12 px, `--radius-lg` 16 px, `--radius-xl` 22 px, `--radius-pill` 999 px; alias `--radius`/`--radius-card` = lg y `--radius-control` = md.
  - Controles: `--control-h-sm` 42 px, `--control-h-md` 44 px y `--control-h-lg` 48 px. Todo botón, input, select y cierre de modal respeta al menos 42 px (44 px en modales y acciones críticas).
  - Foco: `--focus-width` 3 px, `--focus-offset` 2 px y `--focus-ring`; el foco visible es `outline: 3px solid var(--accent-primary)` y debe permanecer en cualquier estado del botón.
  - Vidrio: `--glass-blur` 18 px, `--glass-blur-strong` 22 px, `--blur-glass-sm` 10 px y `--glass-saturate` 140 %; `--glass-highlight` aporta el brillo interior de 1 px.
  - Movimiento: `--dur-fast` 120 ms, `--dur-base` 180 ms, `--dur-slow` 240 ms y `--ease-standard`.
- Reglas de legibilidad:
  - Para cada tema se compone `--surface-glass` sobre `--bg-base` y se exige `--text-strong`, `--text-main` y `--text-muted` >= 4.5:1, y `--border-control` >= 3:1. Los valores se verifican en `tests_js/tokens_accesibilidad_m1.test.cjs`.
  - El cuerpo de las tablas usa `--surface-data`, no vidrio: la lectura de datos no depende del fondo decorativo.
  - Un texto nunca se coloca sobre una capa de vidrio más transparente que la calibrada para su nivel de elevación.
  - La transparencia es decorativa y opcional: cualquier navegador o preferencia de accesibilidad puede desactivarla sin perder legibilidad ni jerarquía.
- Botones (componente `.btn`):
  - Base: `inline-flex`, altura mínima 42 px, radio de control, borde de control, superficie de control, texto `--text-strong` y peso 600. Tamaños `.btn-sm`/`.btn-xs` (42 px mínimo de alto y ancho para objetivos táctiles), `.btn-lg` (48 px), `.btn-full` y `.btn-group`.
  - Variantes: `.btn-primary` (degradado del acento y `--button-on-accent`), `.btn-secondary`, `.btn-outline`, `.btn-ghost`, `.btn-link`, `.btn-danger`, `.btn-success`, `.btn-warning` y `.btn-info` (usando los tokens `--status-*-solid` y `--status-*-solid-on`), más las familias `.btn-outline-*` y `.btn-icon` (42 x 42 px).
  - Estados: `:hover` eleva 2 px y refuerza borde/sombra; `:active` comprime 1 px; `:focus-visible` dibuja el anillo de 3 px con offset de 2 px; `:disabled` y `[aria-disabled="true"]` bajan la opacidad a .55, desactivan el cursor y anulan la elevación; `[aria-busy="true"]` (o `.is-loading`) oculta el texto y muestra un spinner cuyo trazo usa `--button-on-accent` en las variantes rellenas.
- Bordes y radios:
  - Un borde normal mide 1 px (`--border-hairline`); el borde reforzado mide 2 px (`--border-strong`) y se reserva para foco de contraste reforzado y estados de error.
  - Los radios salen siempre de la escala: control/inner 10–12 px, tarjeta/modal 16 px, píldora 999 px. No se admiten radios ad hoc fuera de la escala.
  - Los iconos usan `.icon-sm` 16 px, `.icon-md` 20 px, `.icon-lg` 24 px o `.icon-inline` 1em; su tamaño no se fija con `style` en línea.
- Estados semánticos: alertas con `--status-*-text`, `--status-*-bg` y `--status-*-border` y acento lateral de 4 px; insignias con fondo sólido y texto de contraste ya emparejado; formularios con borde `--border-control`, foco de 3 px y superficie `--input-bg`; tablas con cabecera `--surface-header` y filas `--surface-data`.
- Fallbacks obligatorios:
  - `@supports not (backdrop-filter: blur(1px))`: las superficies con vidrio pasan a `--surface-1` sólida y `backdrop-filter: none`.
  - `@media (prefers-reduced-transparency: reduce)`: mismo paso a superficie sólida para tarjetas, alertas, modales y controles.
  - `@media (prefers-contrast: more)`: superficie de datos, bordes de control de 2 px y `--text-muted` como color de borde.
  - `@media (forced-colors: active)`: bordes `ButtonText`, foco `Highlight` de 3 px y sin decoraciones que dependan solo del color.
  - `@media (prefers-reduced-motion: reduce)`: desplazamientos y animaciones neutralizados.
- Criterios BDD:
  - Dado un tema cualquiera, cuando se compone su superficie translúcida sobre el fondo base, entonces el texto principal, secundario y atenuado conserva al menos 4.5:1 y el borde de control al menos 3:1.
  - Dado un navegador sin `backdrop-filter` o una preferencia de transparencia reducida, cuando se carga cualquier pantalla, entonces las tarjetas, alertas y modales se pintan con superficie sólida y el contenido sigue siendo legible.
  - Dado un botón primario, outline, deshabilitado u ocupado, cuando se inspecciona su estilo calculado, entonces conserva radio de control, altura mínima de 42 px y el estado se comunica también con opacidad, cursor o spinner.
  - Dado un icono en una plantilla, cuando se revisa el HTML, entonces su tamaño procede de `.icon-*` o de un token, nunca de `width/height` en píxeles dentro de `style`.
  - Dado un ancho de 320, 390, 768, 1440, 1920 o 2560 px, cuando se recorre una página del sistema, entonces no aparece desbordamiento horizontal de página y las acciones siguen alcanzables.
- Verificación:
  - `node tests_js/estilos_estandarizados.test.cjs`: variables definidas o dinámicas, variantes `.btn-*` definidas, cero `<style>` en plantillas (salvo el `noscript` de `base.html`), cero colores literales fuera de tokens, cero iconos con ancho/alto en línea y ratchet de atributos `style=` (720 tras la migración; solo puede bajar).
  - `node tests_js/tokens_accesibilidad_m1.test.cjs`: tokens de superficie en los tres temas, contraste compuesto por alfa, fallbacks y estados canónicos de botón.
  - `node tests_js/responsive_bento_m2.test.cjs`: calibración de `--surface-glass` del tema Sena y contraste de `--text-main` sobre la superficie compuesta.
  - `node tests_js/grupos_layout.test.cjs`: la regla `.bento-sidebar` vive en `app/static/css/grupos.css`.
  - `python -m pytest tests/test_ui_ux_design_and_depth.py -q`: tokens y selectores canónicos presentes en `styles.css`.
  - `node tests_browser/diseno_visual.test.cjs`: estilos calculados de botón, tarjeta, alerta, insignia, input, tabla y modal; foco visible; cambio de tema; cero desbordamiento en 320, 390, 768, 1440, 1920 y 2560 px. Requiere lanzar Chromium real (sesión con `danger-full-access`, porque el sandbox confinado falla con `spawn EPERM`).

## Contrato de diseño — cronograma compacto y eventos interactivos (1 de octubre de 2026)

- Dirección visual: visualización de datos integrada al tablero Bento; superficies sólidas y colores del tema vigente.
- Jerarquía: filtros y leyenda breve → escala temporal con meses y años → fases → resumen compacto y línea de tiempo por competencia.
- Densidad: la página usa todo el ancho disponible. El resumen ocupa entre 15 y 19 rem en escritorio y «Ocultar columna» devuelve ese espacio al calendario. En esa vista, el nombre y el avance permanecen sobre cada evento; la fila de nombre breve no supera 120 px en escritorio. Los nombres completos pueden ocupar varias líneas.
- Interacción: toda la línea de tiempo es un botón accesible. Un clic, Enter o la barra espaciadora abre un diálogo con pestañas de resumen, resultados, aprendices y ficha pedagógica. Cada apertura inicia en el resumen; las flechas, Inicio y Fin recorren las pestañas. Escape y «Cerrar» devuelven el foco al evento.
- Lectura: la barra superior representa el periodo planeado; la inferior muestra la proporción aprobada dentro de ese periodo. El porcentaje no representa una fecha de ejecución. El trimestre actual y la etapa productiva tienen etiquetas explícitas.
- Adaptación: en celular la columna inicia oculta; el usuario puede mostrarla y su decisión se conserva al cambiar el ancho durante la consulta. Dos columnas cuando el contenedor dispone de al menos 800 px. Escala y barras comparten anchura y origen. El diálogo usa dos pestañas por fila en celular y cuatro en escritorio, con controles de al menos 44 px. Los filtros anuncian el conteo, ocultan fases sin coincidencias y permiten restablecer una búsqueda vacía.
- Verificación: pruebas de renderizado, interacción y cobertura del 100 % de funciones del módulo; revisión en navegador a 320, 390, 768, 1440, 1920 y 2560 px, nombres largos y ancho disponible al 200 %.

## Contrato de diseño — seguimiento de evaluaciones por tramo (1 de octubre de 2026)

- Dirección visual: tablero Bento con tarjetas operativas, superficies sólidas y tokens institucionales existentes.
- Jerarquía en el detalle del evento: competencia y periodo → pestañas → fechas y horas, RAP con actividad y conteos, seguimiento de aprendices o contenido curricular según la pestaña seleccionada.
- Semántica: evaluado y aprobado se consultan por separado. En un tramo, tener un RAP pendiente impide aparecer como completamente evaluado; la evaluación parcial se identifica expresamente.
- Detalle: diálogo con selección de RAP, búsqueda por nombre o documento, filtro por instructor registrado y estados pendientes, evaluados y todos. El listado usa tarjetas en orden alfabético con juicio, instructor y fecha por RAP.
- Celular: una columna desde 320 px; la vista inicial muestra el nombre sobre el evento y repite los trimestres. El resumen se puede mostrar con el control de columna. Los controles tienen altura mínima de 44 px y el diálogo cabe en el ancho y alto disponibles.
- Accesibilidad y estados: diálogo nativo, Escape, devolución del foco, nombres completos, anuncios de conteo, vacío con instrucciones para ajustar filtros y error de lectura con reintento. La consulta usa datos ya cargados, sin espera remota adicional.
- Contratos y criterios BDD: [Seguimiento de evaluaciones](docs/architecture/seguimiento-evaluaciones-planeacion.md).

## Contrato de diseño — planeación de la ficha (29 de septiembre de 2026)

- Usuario y objetivo: el instructor identifica la ficha, consulta su avance y accede al cronograma o a la actualización de fuentes desde el encabezado.
- Jerarquía: identidad de la ficha y acción principal → navegación de consultas frecuentes → estado de las fuentes → resumen y análisis → historial. Los gráficos complementarios se agrupan en «Más análisis».
- Dirección visual: tablero Bento editorial con superficies sólidas, acento institucional, tipografía jerárquica y espaciado consistente. Se reutilizan los tokens de los temas existentes.
- Interacción: los enlaces abren las secciones contraídas, incluido el enlace directo de la URL. Las preferencias de plegado se conservan por ficha. Los controles tienen nombre accesible, foco visible y altura mínima de 44 px.
- Estados: vacío con acceso a la carga; procesamiento anunciado; errores con reintento; fuentes parciales o completas con sus versiones reales; se conservan validación, progreso y confirmaciones de carga existentes.
- Alcance de datos: presentación y navegación; no se modifican cálculos, permisos, contratos de carga ni tratamiento de datos educativos o personales.
- Verificación: pruebas de renderizado Flask y comportamiento de navegación en JavaScript, integración en CI y revisión a 320, 390, 768, 1440, 1920 y 2560 px y zoom del 200 %.

## Contrato de diseño — cronograma planificado y avance real (29 de septiembre de 2026)

- Tarea principal: el instructor compara el periodo previsto y el avance aprobado de cada competencia, y abre su ficha pedagógica desde la misma tarjeta.
- Jerarquía: filtros → fases y trimestres → nombre y estado de la competencia → horas, RAP y porcentaje aprobado → acción para ver la ficha.
- Presentación: cada competencia conserva su nombre y metadatos en una tarjeta; el cronograma ocupa el carril temporal. En pantallas estrechas, el nombre de la competencia permanece visible mientras el instructor desplaza los trimestres.
- Lectura: el porcentaje aprobado se presenta completo junto con la barra visual; las barras dejan de alojar texto que se recortaba según su longitud. El nombre del cronograma, los botones y el detalle de cada barra tienen etiquetas accesibles.
- Interacción vigente: la línea de tiempo abre el detalle del tramo; el botón «Ver ficha», dentro del detalle, abre la ficha pedagógica.
- Responsive: tarjetas legibles desde 320 px; filtros y acción con altura mínima de 42 px; las columnas temporales usan desplazamiento horizontal interno sin ampliar la página.
- Alcance: no se cambian los cálculos de porcentaje, periodo, retraso o prioridad ni el filtro existente.

### Criterios BDD

- Dada una competencia con nombre largo, cuando el instructor recorre el cronograma, entonces puede leer el nombre completo y abrir la ficha con un botón claramente identificado.
- Dado un porcentaje de avance, cuando la barra es más corta que su etiqueta, entonces el porcentaje sigue visible completo en los metadatos de la tarjeta.
- Dado un teléfono o un control por teclado, cuando el instructor recorre los trimestres, entonces el nombre de la competencia permanece a la vista y el foco del teclado identifica el área desplazable.

## Dirección visual

La interfaz usa un tablero operativo de inspiración Bento: superficies agrupadas, jerarquía por estados y acciones contextuales. La identidad SENA se conserva en el verde institucional, mientras que los colores de estado ayudan a detectar atención, avance y riesgo sin depender únicamente del color.

## Principios de experiencia

- Mobile First: una columna legible, controles táctiles de al menos 42 px y desplazamiento horizontal solo cuando el contenido lo necesita.
- Prioridad por frecuencia: asistencia, tareas, aprendices y alertas aparecen primero; consultas menos frecuentes se revelan bajo demanda.
- Una fuente de contexto: la ficha activa y su programa se muestran en la cabecera; las tarjetas evitan repetir todos los módulos en cada nivel de navegación.
- Lectura progresiva: el resumen muestra estado y próximos pasos; el detalle adicional vive en elementos expandibles.
- Accesibilidad: foco visible, enlaces activos identificables, mensajes de búsqueda en vivo y estados vacíos accionables.

## Contrato de diseño — tarjeta de ficha (12 de septiembre de 2026)

- Usuario y tarea primaria: el instructor debe identificar en pocos segundos el estado de una ficha, la brecha académica y la siguiente acción operativa.
- Jerarquía: identidad y estado → tiempo y fases → indicadores académicos → alertas y pendientes operativos → acciones frecuentes → detalle bajo demanda.
- Dirección de arte: tablero operativo editorial con acentos semánticos SENA (verde para avance, azul para información, naranja para atención y rojo solo para riesgo), superficies sólidas y bordes visibles en cada control de progreso.
- Datos: reutilizar los datos reales ya calculados por el dashboard (`tareas_totales`, `entregas_totales`, `pendientes`, `planes_pendientes`, RAPs, asistencia y estados del grupo); no agregar valores de muestra ni ocultar textos esenciales por truncamiento.
- Componentes: hero comparativo con una barra de tiempo y otra de avance promedio grupal, comparador de fases, KPI complementarios, franja de indicadores operativos y acciones frecuentes. Los hitos de certificación y formación integral permanecen en el detalle expandible.
- Estados y accesibilidad: conservar vacío, carga, error con reintento y confirmación de éxito del dashboard; añadir nombres accesibles a las barras de progreso, foco visible y objetivos táctiles de mínimo 42 px.
- Responsive: 320, 390, 768, 1440, 1920 y 2560 px; una columna legible en móvil, dos columnas solo con holgura, sin desbordamiento horizontal ni elipsis en nombres de competencias o etiquetas esenciales.
- Presupuestos: tarjetas internas con separación de 12–16 px, bordes de 1–2 px y barras de 10–12 px con contraste suficiente; la información secundaria debe poder leerse sin depender del color.

## Componentes clave

- `dashboard-hero`: entrada de la página y acción principal.
- `dashboard-toolbar`: búsqueda, contador y elección persistente de vista.
- `card-ficha`: resumen de avance, métricas prioritarias y acciones de la ficha.
- `ficha-secondary-metrics` / `ficha-more-actions`: contenido secundario bajo demanda.
- `ficha-nav`: navegación contextual de la ficha, desplazable en pantallas pequeñas.

## Contrato de diseño — herramientas del directorio de aprendices (12 de septiembre de 2026)

- Usuario y tarea primaria: el instructor debe actualizar la información del grupo o compartir el acceso sin confundir acciones, permisos ni formatos admitidos.
- Jerarquía: resumen contraído → actualización del grupo → asignación operativa → acciones complementarias → acceso mediante QR o enlace.
- Dirección de arte: panel SaaS B2B sobrio con apoyo minimalista. Se conservan los tokens y temas del producto; la estructura usa superficies sólidas, pasos numerados y un único acento por acción principal.
- Patrones aplicados: divulgación progresiva del panel existente; agrupación de formulario y ayuda persistente; confirmación contextual de copia mediante una región `aria-live`.
- Hipótesis local: la numeración `01` y `02` puede acelerar el recorrido visual. Se mantiene como candidata hasta contar con observación de uso en otra vista.
- Responsive: una columna desde 320 px; carga y botón comparten fila solo cuando el contenedor supera 560 px; QR y enlace comparten fila desde 460 px; las dos herramientas aparecen en paralelo desde 900 px.
- Estados: esqueleto mientras se genera el QR, alternativa textual si la biblioteca no carga, validación nativa de archivo obligatorio, resultado de copia exitoso o ruta manual con `Ctrl+C`.
- Accesibilidad: controles de mínimo 42 px, foco visible, ayudas asociadas con `aria-describedby`, título completo del selector y movimiento reducido.

### Criterios BDD

- Dado un instructor autenticado, cuando despliega “Herramientas de Gestión y Carga de Archivos”, entonces distingue las áreas “Actualizar información del grupo” y “Compartir acceso con aprendices”, cada una con su acción principal.
- Dado que no se ha seleccionado un archivo, cuando intenta enviar el formulario, entonces la validación nativa bloquea el envío y conserva el contexto.
- Dado que el navegador permite el portapapeles, cuando copia el enlace, entonces recibe una confirmación accesible; si el permiso falla, el enlace queda seleccionado y se indica `Ctrl+C`.
- Dado un ancho de 320 px o un zoom de 200 %, cuando el panel está abierto, entonces los controles se apilan sin desbordamiento horizontal ni pérdida de texto esencial.
- Dado un usuario sin autorización para gestionar la ficha, cuando intenta acceder a la ruta, entonces la protección del servidor vigente sigue gobernando la respuesta; este cambio no altera permisos ni contratos de datos.

## Contrato de diseño — ranking de participación (12 de septiembre de 2026)

- Usuario y tarea primaria: el instructor debe reconocer los primeros puestos, comparar las tres fuentes del puntaje y abrir el historial de un aprendiz sin perderse en una lista extensa.
- Jerarquía: título y acciones → corte activo → aclaración institucional → resumen → periodo → podio → clasificación completa → histórico y configuración.
- Dirección de arte: fusión `SaaS Dashboard + Data Visualization`, integrada al tablero Bento existente. Las superficies permanecen sólidas; las medallas y acentos semánticos señalan posición sin convertir el ranking en una evaluación oficial.
- Patrones aplicados: divulgación progresiva para la configuración, tabla de comparación en escritorio y tarjetas compactas en móvil. El carril horizontal con ajuste por tarjeta para el podio queda como patrón candidato y no se promueve hasta verificarlo en otra vista comparable.
- Responsive: desde 320 px la cabecera y los formularios usan una columna, el resumen combina tarjetas de ancho completo y medio, el podio permite desplazamiento interno seguro y la lista conserva nombres completos. Desde 800 px se activa la tabla con desplazamiento horizontal interno; desde 1200 px el histórico ocupa una barra lateral estable.
- Accesibilidad: controles táctiles de mínimo 42 px, nombres sin elipsis, foco visible, podio navegable por teclado, indicador de carga y alerta recuperable para la actualización automática.
- Estados: clasificación vacía con siguiente acción; esqueleto durante la actualización; alerta con reintento cuando HTMX falla; confirmaciones globales vigentes para formularios exitosos; confirmación explícita antes de iniciar un corte nuevo.
- Presupuestos: cero desbordamiento de página en 320, 390, 768, 1440, 1920 y 2560 px; ancho mínimo interno de tabla de 920 px; sin cambios en rutas, cálculos, permisos ni persistencia.

### Criterios BDD

- Dado un ancho de 320 px, cuando se muestra el ranking con nombres largos, entonces ningún contenido amplía la página y los nombres se leen completos sin partir palabras.
- Dado un ranking con participantes, cuando el instructor recorre la página en móvil, entonces encuentra “Clasificación completa” antes de la primera tarjeta y puede abrir el historial mediante un enlace con foco visible.
- Dado un ancho de al menos 800 px, cuando se muestra la clasificación, entonces la tabla conserva una columna de aprendiz legible y cualquier exceso se desplaza dentro de su contenedor.
- Dado que la actualización parcial está en curso, cuando HTMX solicita la lista, entonces se anuncia el estado de carga sin desplazar la geometría principal.
- Dado que la actualización parcial falla, cuando HTMX informa el error, entonces aparece una alerta descriptiva con botón de reintento y la lista anterior permanece disponible.
- Dado que no hay aprendices, cuando se abre el ranking, entonces aparece un estado vacío con acceso al directorio de aprendices.
- Dado un parámetro de periodo inválido, un usuario sin autorización o una creación de corte duplicada, cuando el servidor responde con validación, prohibición o conflicto, entonces esta mejora conserva las respuestas y protecciones existentes sin simular éxito en la interfaz.

# Contrato de diseño — espacio del aprendiz (7 de octubre de 2026)

- Dirección visual: dashboard Bento existente, tarjetas con superficies sólidas y acentos del catálogo institucional.
- Personalización: foto o avatar, saludo, lema, ocho colores, tres fondos, orden de tarjetas y vista por pestañas o continua.
- Confirmación: la interfaz aplica únicamente el estado confirmado por el servidor; el borrador se conserva cuando falla el guardado. Los conflictos permiten recargar preferencias.
- Accesibilidad: controles de 44 px, navegación por teclado, ordenación con Subir/Bajar, estado anunciado y aviso compartido de éxito. La selección de color usa texto e indicador adicional, con primer plano calculado por contraste.
- Jerarquía: cabecera y alertas operativas conservan su posición; solo se ordenan las tarjetas disponibles. Las distinciones de oro, plata y bronce proceden del ranking real.
- Verificación: persistencia después de recarga y reinicio, aislamiento de sesión, recuperación de preferencias antiguas y pruebas a 320, 390, 768, 1440, 1920 y 2560 px, con zoom del 200 %.

## Contrato de diseño — recorrido del aprendiz (7 de octubre de 2026)

- Jerarquía: siguiente acción y meta semanal → confirmación de ajustes → estado de evidencias → competencias, equipo e hitos bajo demanda. El inicio conserva las alertas operativas.
- Motivación: metas ajustables y pausables, progreso propio y reconocimientos permanentes por evidencias registradas. El avance grupal aprovecha los trabajos asignados; ninguna preferencia altera los juicios oficiales.
- Personalización de lectura: espaciado cómodo o compacto, movimiento reducido, ranking opcional y avisos agrupados. Los modos de avisos conservan la información importante y permiten consultar la adicional.
- Continuidad: los accesos revelan la evidencia, limpian filtros y abren acordeones; el punto guardado se recupera desde el servidor.
- Estados: datos iniciales del servidor, confirmación después del commit, error con reintento, conflicto con recarga y orientación cuando faltan tareas o resultados.
- Accesibilidad: controles de 44 px, foco visible y acentos con primer plano contrastado. El portafolio y el calendario se reestructuran en celular sin ampliar la página.
