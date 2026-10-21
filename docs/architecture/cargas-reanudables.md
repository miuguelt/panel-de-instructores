# Cargas reanudables

El panel puede recibir archivos de hasta 2 GiB (2.147.483.648 bytes) mediante bloques de 4 MiB. El límite del envío tradicional se conserva por separado. Los formatos permitidos dependen del formulario; ampliar el tamaño no habilita otros formatos.

## Recepción y confirmación

`POST /cargas` crea la sesión con destino, campo, nombre, tipo y tamaño. `Idempotency-Key` identifica un mismo intento por archivo y propietario: repetirlo después de perder una respuesta recupera la misma sesión. `GET /cargas/<id>` devuelve el avance confirmado, las huellas de los bloques y su vencimiento. `PATCH` recibe un bloque binario con `Upload-Offset` y `X-Chunk-SHA256`. `DELETE` cancela una transferencia que todavía no se ha registrado.

El servidor verifica identidad, permisos, tamaño y SHA-256. Después escribe el bloque, ejecuta `fsync` y confirma su posición en la base de datos. Si el proceso se interrumpe entre disco y base de datos, el siguiente envío descarta únicamente la escritura que no alcanzó a confirmarse. El cliente consulta el avance antes de retransmitir. El tamaño de bloque queda registrado en cada sesión y se conserva al reiniciar o actualizar la aplicación.

La confirmación del formulario lleva `_cargas` —referencias por nombre del campo— y `_carga_envio`, sin repetir los bytes. El registro principal y su confirmación de idempotencia se guardan en la misma transacción. Un reintento con otros campos no reutiliza esa confirmación. Las validaciones existentes de tareas, grupos, planes, fichas y tipos de archivo siguen aplicándose.

Los archivos se guardan inicialmente en `UPLOAD_FOLDER/.cargas`, que no admite descargas públicas. Su publicación usa enlaces dentro del mismo almacenamiento, con un diario de recuperación. Cuando el sistema de archivos no admite enlaces, se usa una copia acotada con verificación de espacio. El original temporal permite recuperarse de un fallo de persistencia. La limpieza conserva los archivos referenciados por registros definitivos.

## Procesamiento y recuperación

Los Excel y PDF recibidos mediante el flujo reanudable se registran en `cargas_envios` antes de procesarlos. Redis avisa al worker, pero la base de datos conserva los trabajos cuando la cola falla. El worker también revisa los pendientes y las ejecuciones cuyo plazo de reserva terminó. Un bloqueo por trabajo impide que dos procesos importen el mismo envío. Si el proceso termina después de confirmar los datos académicos, la recuperación completa su resultado sin repetir la importación.

La interfaz distingue transferencia, verificación, recepción, procesamiento y resultado. Un 100 % transferido no significa que los datos académicos estén incorporados. La consulta puede continuar después de recargar la página. Para retomar una transferencia incompleta puede ser necesario seleccionar otra vez el mismo archivo; se comparan sus bloques recibidos antes de continuar. El navegador guarda referencias y metadatos, sin almacenar el contenido del archivo.

El avance vence 24 horas después del último bloque confirmado. Se admiten tres transferencias pendientes por identidad. La reserva de espacio incluye los bytes declarados que faltan por recibir y deja libre el mayor valor entre 2 GiB y el 10 % del disco. La limpieza omite los trabajos pendientes o activos. Los errores de procesamiento permiten reintentar con `POST /cargas/<id>/reintentar`, dentro del plazo de conservación y sin repetir la transferencia.

Los lectores XLSX usan streams y lectura de solo lectura; los registros intermedios se conservan temporalmente en disco y se importan por lotes de 1.000, sin confirmaciones parciales. XLS usa ruta y apertura bajo demanda. PDF se abre desde un stream. Las bibliotecas pueden consumir memoria proporcional a las cadenas compartidas de XLSX, a una hoja XLS o al contenido de un PDF: el límite de recepción no garantiza que cualquier documento de ese tamaño sea procesable con los recursos disponibles. Un fallo de procesamiento conserva el original durante el plazo de recuperación y produce un mensaje independiente del resultado de la transferencia.

## Habilitación del despliegue

1. Mantenga `CARGAS_REANUDABLES_ENABLED=false` mientras actualiza el esquema con `flask db upgrade` mediante el ciclo de despliegue autorizado. La revisión es `u44cargasreanudables` y no modifica los archivos históricos.
2. Actualice aplicación y worker con el mismo almacenamiento persistente y `MAX_RESUMABLE_UPLOAD_BYTES=2147483648`. Conserve `MAX_CONTENT_LENGTH` para el flujo tradicional; no es necesario permitir solicitudes HTTP de 2 GiB.
3. En el entorno de validación, habilite el flujo y compruebe a través del proxy público un archivo de más de 4 MiB. El proxy debe aceptar `PATCH`, `DELETE`, CSRF, `Idempotency-Key`, `Upload-Offset` y `X-Chunk-SHA256`, permitir cuerpos de al menos 4 MiB y no almacenar las respuestas privadas en caché. El cliente limita cada solicitud a 120 segundos y conserva el avance si se agota ese plazo.
4. Compruebe el avance después de cortar la conexión, la continuación desde el bloque confirmado, una descarga con contenido idéntico y el procesamiento desde el worker. Revise el espacio disponible y la limpieza de temporales.
5. Después de esas verificaciones, configure `CARGAS_REANUDABLES_ENABLED=true` tanto en aplicación como en worker y aplique el ciclo controlado de despliegue. Para deshabilitar el flujo nuevo, vuelva a `false`; conserve las tablas y el almacenamiento para recuperar los trabajos y archivos.

Esta entrega verifica el recorrido con un servidor Flask hermético y un navegador real. La configuración y los límites del proxy de producción deben comprobarse en ese entorno antes de habilitarlo; las pruebas locales no acreditan esa configuración externa.

## Verificación reproducible

- Servidor: `python -m pytest tests/ --cov=app --cov=config --cov=worker --cov=wsgi --cov=seed_admin --cov-branch --cov-report=xml:coverage.xml --cov-fail-under=75 --function-calls-json=test-results/function-calls.json`.
- Compuerta de funciones: `python scripts/check_function_coverage.py --source app --coverage-xml coverage.xml --calls-json test-results/function-calls.json --runtime-files config.py worker.py wsgi.py seed_admin.py`.
- Interfaz: `npm test` y `npm run test:browser`. La CI exige el 100 % de funciones de ambos controladores de carga.
- `test_transfiere_dos_gib_reales_con_memoria_acotada_y_descarga_identica` recibe 512 bloques y compara las huellas del archivo guardado y de la descarga, con memoria acotada. Los resultados de tiempo son mediciones locales, no una velocidad garantizada para otra conexión.
- `tests_browser/uploads_servidor.test.cjs` verifica Chromium, CSRF, Flask, SQLite, disco y procesamiento real, incluyendo pérdida de respuestas y confirmación sin duplicados. El servidor de prueba usa puerto aleatorio y almacenamiento temporal.
