# Aprendizajes de diseño web

## 22 de noviembre de 2026 — auditoría de arquitectura y consistencia

- Error de datos corregido: la regla `'APROBADO' in juicio and 'AUN NO' not in juicio`, repetida en 23 lugares, contaba «NO APROBADO» y «AÚN NO APROBADO» como aprobados.
  - Con cinco juicios y uno aprobado, varias vistas mostraban 60 % en lugar de 20 %.
  - Ahora todo usa `es_aprobado()`, que normaliza tildes, o su versión SQL `condicion_aprobado_sql()`.
  - Una prueba impide que la regla por subcadena vuelva a aparecer en `app/`.
- Arquitectura:
  - `panel()` del aprendiz pasó de 604 a 343 líneas, y la lógica quedó en tres servicios con pruebas: `juicios_aprendiz`, `evidencias_aprendiz` y `asistencia`.
  - El reporte PDF reutiliza esos servicios y deja de diferir del panel: ahora deduplica juicios, respeta prórrogas y excluye trabajos grupales.
- Patrón de interacción:
  - Al cargar, una página no debe mover la vista.
  - Casos de seguimiento aplicaba sus filtros con `FiltroVista.aplicar`, que desplazaba la página hasta la barra de filtros y escondía el título y el resumen.
  - Ahora el filtrado inicial es directo y solo los cambios del usuario conservan la posición de lectura.
- Consistencia:
  - Un solo `<h1>` por página; casos de seguimiento tenía dos cabeceras completas.
  - Íconos Lucide en lugar de emojis en los títulos.
  - Mayúscula solo en la primera palabra y en los nombres propios, también en los títulos de pestaña.
  - `tests/test_titulos_paginas.py` lo vigila.
- Decisión aplicada: la asistencia descuenta solo las faltas sin justificar en todas las vistas. Antes, para un aprendiz con una falta sin justificar, una justificada y una excusa médica en cuatro sesiones, seis vistas del instructor mostraban 25 % y su panel 75 %.
- Deuda declarada: `juicios.html` conserva 85 estilos en línea, casi todos únicos. Migrarlos no cambia lo que ve el usuario, por eso no se priorizó.

## 21 de noviembre de 2026 — primero lo importante y biblioteca de visualización

- Alcance observado:
  - En «Mis fichas», cada tarjeta mostraba seis bloques de fechas antes de los pendientes; la cuenta regresiva aparecía tres veces y las fechas, cuatro o más.
  - En la Visión general, la atención inmediata quedaba en el tercer bloque y una rejilla de 12 módulos repetía la barra de la ficha.
  - En el panel del aprendiz, la asistencia aparecía en cinco sitios y el % de juicios en siete, con fórmulas y umbrales distintos.
- Patrón aplicado:
  - Pirámide invertida: acción de hoy, luego estado y después el detalle plegado.
  - Una cifra por pantalla y un umbral por concepto (`viz_estado`).
  - Macros SVG/CSS accesibles en lugar de gráficos hechos a mano en cada plantilla.
- Decisión de datos: los servicios devuelven `None` cuando no hay sesiones, tareas o juicios, y la interfaz dice «Sin datos». Antes, una ficha sin asistencia registrada aparecía con un 100 % en verde.
- Hallazgos corregidos de paso:
  - `main` no arrancaba: el commit 80ecb74 borró tres módulos de rutas sin retirar su import. Se recuperaron del punto de control Entire 1a89457 y se dividieron en módulos de menos de 400 líneas.
  - La ruta de juicios había perdido las variables del avance del curso.
  - El semáforo de riesgo estaba duplicado y contaba tareas distintas en Alertas y en la Visión general.
  - El selector de las pestañas de Juicios del aprendiz reescribía la clase de las pestañas principales.
  - La vista continua forzaba `display: block` y rompía las rejillas.
  - Una regla genérica de inputs tapaba la primera letra del buscador de fichas.
- Patrón candidato: «Hoy en tus fichas» con indicadores agregados y fichas ordenadas por urgencia. Estado: `candidate` hasta observar su uso con instructores reales.
- Evidencia obtenida:
  - Revisión en el navegador integrado con datos de práctica en SQLite (sin tocar la base real).
  - Cero desbordamiento horizontal en ocho páginas del instructor a 320, 390, 768, 1440, 1920 y 2560 px.
  - Capturas a 390 y 1440 px de «Mis fichas», Visión general, Juicios, Tareas, Alertas, Estadísticas, Asistencia, Aprendices y el panel del aprendiz.
  - `npm test`: 189/189.
  - `tests_browser/auditoria_funciones.test.cjs`: 11/11.
- Limpieza posterior (21 de noviembre de 2026):
  - Se retiraron 426 reglas CSS huérfanas (unas 2 900 líneas; `styles.css` pasó de 14 503 a 12 403).
  - Criterio conservador: solo clases que estaban en las plantillas antes del rediseño y que hoy no aparecen como texto en ningún archivo de la app ni de las pruebas.
  - Se excluyeron los modificadores genéricos (`is-*`, `text-*`, `tag-*`) porque pueden armarse dinámicamente.
  - El JS del panel del aprendiz pasó a `app/static/js/aprendiz_panel.js`, sin dependencia de Jinja: el calendario lee sus datos de un `<script type="application/json">`.
  - La prueba nueva `tests_js/aprendiz_panel.test.cjs` cubre el 100 % de las funciones y se ejecuta en CI.
  - La auditoría de inyección ahora carga el archivo real con datos escapados como lo hace `tojson`, incluido un intento de cerrar la etiqueta `</script>`.
  - Hallazgo: con los nombres nuevos, la barra inferior del aprendiz desbordaba 25 px a 320 px. Se corrigió con el rótulo corto «Logros» (que conserva «Rendimiento y logros» como nombre accesible) y celdas que pueden encogerse.
  - Verificación: sin desbordamiento horizontal en 10 páginas del instructor y en el panel del aprendiz, a 320, 390, 768, 1440 y 2560 px.
- Deuda previa resuelta: `tests_browser/diseno_visual.test.cjs` fallaba en 3 aserciones porque el Chromium de este equipo expone `prefers-reduced-transparency: reduce` (Windows con los efectos de transparencia desactivados), y el fallback accesible quitaba el vidrio como corresponde.
  - El CSS era correcto; la prueba no fijaba la preferencia.
  - Ahora la fija con `Emulation.setEmulatedMedia` y suma un caso que verifica el fallback sólido con transparencia reducida.
  - El CI ejecuta esta prueba, así que antes habría fallado en cualquier máquina con esa preferencia.

## 23 de octubre de 2026 — sistema visual de superficies translúcidas, botones y bordes

- Alcance observado: la interfaz acumulaba superficies de vidrio con alfas distintas, botones con radios y alturas propios en cada módulo, iconos dimensionados con `style` en línea y colores literales repetidos en plantillas. El resultado era un sistema que se veía coherente de lejos y se rompía de cerca: contraste irregular, objetivos táctiles menores de 42 px y CSS incrustado imposible de auditar.
- Patrón aplicado: capas de superficie con nombre y propósito (`--surface-glass-subtle` → `--surface-glass` → `--surface-glass-strong` → `--surface-data`), una sola escala de radios y alturas, y `.btn` como único punto de entrada de acciones. El dato tabular se aparta del vidrio con `--surface-data`; el vidrio queda para jerarquía y decoración.
- Decisión de legibilidad: el contraste se calcula sobre el color compuesto (`--surface-glass` con alfa sobre `--bg-base`), no sobre el color ideal del token. Esa diferencia explica por qué un gris que parecía correcto sobre blanco dejaba de cumplir AA sobre el fondo tintado del tema.
- Patrón candidato: los fallbacks de accesibilidad (`@supports not`, `prefers-reduced-transparency`, `prefers-contrast: more`, `forced-colors: active`) como parte del contrato y no como parche. Estado: `candidate` hasta revisarlo en una segunda familia de pantallas (aprendiz y grupos).
- Riesgo evitado: fijar los nuevos tokens como colores planos habría vuelto a acoplar los tres temas; se mantuvieron como capas por tema con alias de compatibilidad para no romper CSS de página ya existente.
- Evidencia obtenida (estática, cierre del 23 de octubre de 2026):
  - `node tests_js/estilos_estandarizados.test.cjs`: 7/7. Atributos `style=` en plantillas: 706 (partían de 952); 0 bloques `<style>` fuera del `noscript` de `base.html`; 0 colores literales fuera de tokens; 0 iconos `<i>`/`<svg>` con ancho y alto en línea; ratchet en 720.
  - `node tests_js/tokens_accesibilidad_m1.test.cjs`: 9/9, incluido el contraste compuesto por alfa de `--surface-glass` sobre `--bg-base` en los tres temas y los cuatro fallbacks de accesibilidad.
  - `node tests_js/responsive_bento_m2.test.cjs`: 4/4, con `--surface-glass` del tema Sena (alfa 0.82) y `--text-main` >= 4.5 sobre el compuesto.
  - `node tests_js/grupos_layout.test.cjs`: 3/3, con `.bento-sidebar` leído desde `app/static/css/grupos.css`.
  - `node tests_js/test_auditoria_frontend.test.cjs` 8/8, `node tests_js/uploads.test.cjs` 13/13 y `node tests_js/uploads_reanudables.test.cjs` 24/24 tras migrar sus paneles a clases del sistema.
  - `python -m pytest tests/test_ui_ux_design_and_depth.py -q`: 11 passed.
- Evidencia pendiente por limitación del entorno: `tests_browser/diseno_visual.test.cjs` (Playwright) comprueba estilos calculados y desbordamiento en 320, 390, 768, 1440, 1920 y 2560 px, pero no puede ejecutarse en el sandbox de trabajo: Chromium falla al lanzarse con `spawn EPERM`. La prueba ya lanza un mensaje explícito y requiere una sesión con `danger-full-access`; al ejecutarla, anotar aquí las capturas y cualquier ajuste de alfa o altura táctil que surja.

## 12 de septiembre de 2026 — herramientas del directorio de aprendices

- Alcance observado: la versión anterior agrupaba correctamente las herramientas, pero al desplegarse perdía jerarquía, dejaba demasiado espacio alrededor del QR y mezclaba controles nativos con botones tematizados.
- Patrón conservado: divulgación progresiva mediante `details` y `summary`; evita competir con la búsqueda y el directorio durante el recorrido principal.
- Patrón aplicado: panel SaaS B2B sobrio con formularios agrupados, ayuda persistente y prioridad visual para una acción principal por módulo.
- Patrón candidato: pasos compactos `01` y `02` para acelerar el reconocimiento de las dos tareas. Estado: `candidate`; no se promueve al catálogo global sin evidencia en otro contexto.
- Riesgo evitado: no se alteraron rutas, permisos, datos, carga de archivos ni generación del enlace.
- Evidencia obtenida: revisión autenticada del panel abierto en 320, 390, 768, 1440, 1920 y 2560 px, sin desbordamiento horizontal; controles principales de 46 px; copia real confirmada con estado `¡Enlace copiado!`; consola sin errores ni advertencias.
- Auditoría automatizada complementaria: 0 violaciones de Axe y 0 desbordamientos en capturas claras y oscuras. La herramienta redirige a inicio de sesión al no compartir la sesión autenticada, por lo que la evidencia del componente proviene de la revisión autenticada en navegador.
- Seguimiento: el auditor global conserva dos errores anteriores y ajenos a este alcance en `_tarea_card.html` y `planeacion.html`; no se amplió el cambio para corregirlos.

## 12 de septiembre de 2026 — ranking de participación

- Alcance observado: la versión anterior obligaba a recorrer tarjetas demasiado altas, truncaba nombres relevantes y desplazaba el título de la clasificación debajo de toda la lista móvil.
- Patrón aplicado: jerarquía de tablero de datos con resumen compacto, podio deslizable y tarjetas de comparación que mantienen visibles nombre, puntaje y tres métricas.
- Patrón candidato: carril horizontal con `scroll-snap` para comparar los tres puestos destacados en pantallas angostas. Estado: `candidate`; requiere validación en una segunda vista antes de promoverse.
- Decisión responsive: una columna en 320 px, dos tarjetas desde 360 px cuando hay espacio real, podio de tres columnas desde 680 px y tabla con columnas estables en escritorio.
- Evidencia obtenida: 0 desbordamiento horizontal en 320, 390, 768, 1440, 1920 y 2560 px; 69 controles visibles de al menos 42 px en móvil; nombres completos; foco visible; cambio de período funcional; consola sin errores ni advertencias.
- Auditoría complementaria: los validadores específicos de las dos plantillas no reportan errores. El auditor automatizado de navegador fue redirigido al inicio de sesión al no compartir la sesión autenticada, por lo que no se usa como evidencia Axe de esta pantalla.
