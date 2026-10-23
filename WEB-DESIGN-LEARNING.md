# Aprendizajes de diseño web

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
