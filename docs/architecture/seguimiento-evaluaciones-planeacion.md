# Seguimiento de evaluaciones en el cronograma

## Alcance y contratos

El cronograma conserva el orden pedagógico, las fases y el periodo de cada tramo. El seguimiento identifica cada tramo con una clave propia; una competencia que aparece en dos fases conserva los RAP de cada fase. El detalle curricular existente sigue disponible en «Ver ficha».

`construir_analisis` consulta aprendices y juicios de la ficha autorizada. `evaluar_resultado` usa los mismos estados académicos incluidos en Planeación y los juicios emparejados con cada RAP. No consulta otras fichas ni atribuye una evaluación al instructor previsto o al usuario que importó el archivo.

`construir_seguimiento` compone el detalle por tramo después de ubicar los RAP en la línea de tiempo. La ruta autenticada incorpora este catálogo al HTML mediante `tojson`; el cliente crea los textos con `textContent`, sin interpretar nombres o documentos como HTML. No se agregan tablas, escrituras, cachés ni permisos. Cada consulta vuelve a leer los juicios persistidos.

## Reglas de conteo

- Solo Aprobado (A) y No aprobado (NA), incluidas sus denominaciones completas, representan un juicio emitido. «Por evaluar», registros administrativos y ausencia de fila quedan pendientes.
- Cada persona cuenta una vez por RAP. Entre varios juicios emitidos se usa el de fecha más reciente; el identificador resuelve empates. Una fila administrativa no borra un juicio emitido.
- En el tramo, «Evaluados» significa que la persona tiene juicio en todos sus RAP. «Pendientes» incluye personas sin juicios y con evaluación parcial. Total = evaluados + pendientes.
- El resumen conserva por separado personas con evaluación parcial, personas sin evaluar, personas aprobadas en todos los RAP y cantidad de evaluaciones faltantes.
- El instructor mostrado es `funcionario_registro` del juicio seleccionado. Un dato faltante se presenta como «No registrado»; la fecha faltante se informa sin inventarla.
- Los porcentajes de aprobación y el umbral temporal de cierre existentes conservan su contrato. La cobertura de evaluación es una consulta distinta.

## Criterios Given–When–Then

1. Dado un aprendiz con «No aprobado», cuando se consulta su RAP, entonces aparece evaluado con su juicio, instructor y fecha.
2. Dado un aprendiz sin fila o con «Por evaluar», cuando se consulta el RAP, entonces se cuenta como pendiente sin instructor evaluador atribuido.
3. Dados juicios duplicados, cuando se calcula el seguimiento, entonces se cuenta una persona y se muestra el juicio emitido más reciente.
4. Dado un tramo con varios RAP, cuando un aprendiz tiene solo algunos evaluados, entonces queda pendiente con el estado «Evaluación parcial» y el detalle de cada RAP.
5. Dada una competencia repetida en dos fases, cuando se abre un tramo, entonces solo aparecen los RAP del tramo seleccionado.
6. Dado un instructor sin acceso a la ficha, cuando solicita la página, entonces la protección existente impide recibir el catálogo de aprendices.
7. Dado un teléfono de 320 px, cuando se consulta el cronograma y se abre el seguimiento, entonces los controles y las tarjetas caben en la pantalla.
8. Dado un juicio nuevo confirmado, cuando se vuelve a consultar la página, entonces los conteos reflejan el nuevo estado persistido.

## Interfaz y verificación

La página de planeación utiliza todo el ancho de pantalla. «Ocultar columna» amplía el calendario y deja el nombre y el avance sobre cada evento. En celular la columna inicia oculta; se puede mostrar y la decisión del usuario se conserva al cambiar el ancho durante la consulta. Los carriles repiten las etiquetas de trimestre en pantallas estrechas.

Toda la línea de tiempo abre el detalle del tramo con cuatro pestañas: resumen (fechas, horas, estado e instructores previstos), resultados (actividad, código, denominación, avance y conteos), aprendices (resumen de evaluaciones y acceso al listado filtrable) y ficha pedagógica (norma, código, saberes, criterios y perfil del instructor). Esta última consume la correspondencia exacta del catálogo ya construido; la ausencia de información oficial se explica sin atribuir contenido de otra competencia. El acceso a la ficha completa conserva sus herramientas de consulta, copia e impresión.

`planeacion_gantt.js` controla el diálogo de eventos, las pestañas, la columna y los filtros del cronograma. `_planeacion_gantt_detalle.html` conserva cada tramo en un panel oculto con clave única por fase y posición; sus pestañas y paneles mantienen relaciones ARIA únicas. `_planeacion_gantt_pedagogia.html` presenta los datos oficiales con escape de texto. No se clonan controles ni se modifica el catálogo de seguimiento. `planeacion_gantt.css` aplica la distribución según el ancho del contenedor. El detalle de aprendices se abre sobre el evento y regresa a su acción al cerrarse. Abrir la ficha pedagógica completa cierra primero el evento para usar el modal compartido de la aplicación.

El paso a la ficha pedagógica completa detiene la apertura inmediata, espera el evento de cierre nativo y dos cuadros de renderizado, y luego delega la apertura al controlador compartido. Así la capa anterior deja de bloquear el foco antes de mostrar la ficha; al cerrarla, el foco vuelve al evento. Las pruebas de navegador verifican varias aperturas y cierres consecutivos, y la suite unitaria controla estos cuadros de forma determinista.

El diálogo nativo conserva el foco y el cierre con Escape. Inicia en pendientes, permite seleccionar un RAP, filtrar por evaluador y buscar por nombre o documento sin depender de tildes. Las listas mantienen orden alfabético y el contador anuncia el resultado de los filtros. La ausencia de coincidencias y los errores de lectura tienen mensajes accionables.

Las pruebas de servicio cubren estados, duplicados y agrupación. Las pruebas Flask comprueban la carga real del Excel, datos persistidos, renderizado, actualización y permisos. La suite JavaScript verifica filtros, apertura, cambio de RAP, cierre, datos corruptos y texto seguro; CI exige el 100 % de funciones del módulo y mantiene la compuerta global de Python.

### Criterios del cronograma compacto

1. Dado un tramo, cuando se hace clic en cualquier punto de su línea de tiempo o se activa por teclado, entonces se abre solo su detalle y se conservan sus RAP y evaluaciones.
2. Dado el detalle abierto, cuando se cierra con Escape, el botón o el fondo, entonces el foco regresa a la línea de tiempo que lo abrió.
3. Dada una categoría sin coincidencias, cuando se filtra, entonces desaparecen las fases vacías y «Mostrar todas» restablece el cronograma.
4. Dado un contenedor ancho, cuando se renderiza el cronograma, entonces la línea de tiempo ocupa al menos el doble de ancho que el resumen, se alinea con la escala y la tarjeta de nombre breve no supera 150 px de altura.
5. Dado un nombre largo, un celular o el ancho disponible al 200 %, cuando se consulta el cronograma, entonces el contenido se ajusta sin desbordar la página.
6. Dada la columna oculta, cuando se consulta un evento, entonces su nombre permanece visible y el carril usa todo el ancho de la fila; mostrar la columna restablece el resumen.
7. Dado el detalle abierto, cuando se selecciona una pestaña por clic o teclado, entonces solo aparece su contenido y los estados ARIA y el foco coinciden con la selección.
8. Dado un evento que ya se consultó, cuando se vuelve a abrir o se cambia de tramo, entonces inicia en el resumen y conserva únicamente los datos de ese tramo.
9. Dada una competencia con contenido curricular oficial, cuando se abre la ficha pedagógica, entonces aparecen sus datos y el texto se escapa. Si no hay contenido asociado, se informa cómo completar la fuente.
