# Importación idempotente de resultados de aprendizaje

## Decisión

Un resultado de aprendizaje se identifica por:

`ficha_id + aprendiz_id + competencia + resultado_aprendizaje`

La huella de esa identidad es estable. El juicio, la fecha, el funcionario y
el archivo fuente son datos variables: una nueva importación los actualiza en
la fila existente y no crea otra.

## Flujo

- `app/services/importacion_ficha.py` resuelve la identidad después de crear o
  localizar al aprendiz y actualiza los campos variables.
- Las filas repetidas dentro del mismo Excel se resuelven en memoria.
- `worker.py`, la ruta y la vista informan por separado juicios nuevos y
  juicios actualizados.
- `j31_normalizar_juicios_idempotentes.py` consolida los duplicados históricos,
  conserva los vínculos con instructores y normaliza sus huellas.

El historial conserva una única fila vigente por resultado; no se usa el
estado anterior como una versión adicional del resultado.

## Despliegue

La migración se ejecuta en tiempo de arranque mediante
`docker-entrypoint.sh`, después de que Coolify inyecta `DATABASE_URL` y antes
de iniciar Gunicorn. El `Dockerfile` solo copia el código y deja
`RUN_MIGRATIONS=true` como valor predeterminado; ejecutar `flask db upgrade`
durante `docker build` sería incorrecto porque el build no debe conectarse a
la base de datos de producción.

En Compose, únicamente `app` ejecuta migraciones. `worker` usa
`RUN_MIGRATIONS=false` y arranca después de que el servicio web haya aplicado
la cadena de Alembic.
