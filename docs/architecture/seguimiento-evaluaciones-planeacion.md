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

Las tarjetas muestran primero la competencia, el periodo, los conteos de personas y las acciones. Los RAP se despliegan bajo demanda con actividad, código, denominación, conteos e instructores previstos. En celular, el carril temporal se apila bajo la información y repite las etiquetas de trimestre.

El diálogo nativo conserva el foco y el cierre con Escape. Inicia en pendientes, permite seleccionar un RAP, filtrar por evaluador y buscar por nombre o documento sin depender de tildes. Las listas mantienen orden alfabético y el contador anuncia el resultado de los filtros. La ausencia de coincidencias y los errores de lectura tienen mensajes accionables.

Las pruebas de servicio cubren estados, duplicados y agrupación. Las pruebas Flask comprueban la carga real del Excel, datos persistidos, renderizado, actualización y permisos. La suite JavaScript verifica filtros, apertura, cambio de RAP, cierre, datos corruptos y texto seguro; CI exige el 100 % de funciones del módulo y mantiene la compuerta global de Python.
