# Aprendizajes de diseño web

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
