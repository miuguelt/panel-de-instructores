# Datos documentales y resultados calculados

## Decisión de almacenamiento

PostgreSQL sigue siendo la base principal. Los juicios, aprendices y demás
entidades operativas permanecen como filas relacionales. Por cada versión de
planeación o programa PDF se guarda también la salida estructurada del parser en
`archivos_ficha_versiones.contenido_extraido_json` (JSONB en PostgreSQL); el original permanece en el
volumen `uploads` para descarga y auditoría. Así, la navegación habitual no abre
el Excel o PDF. El campo de versión del parser permite reconstruir la extracción
cuando cambie su contrato.

Los análisis listos para mostrar quedan en `resultados_calculados_ficha`. Cada
snapshot JSONB lleva ficha, tipo de vista, fecha de corte, revisión de datos, versión
del algoritmo y huella de sus archivos de entrada. Cambiar documentos, juicios,
aprendices o fechas invalida la clave. La fecha de corte crea una nueva lectura
diaria porque las métricas de avance cambian con el calendario. PostgreSQL usa
bloqueo asesor por ficha para que varias peticiones simultáneas compartan un
cálculo.

Los documentos de versiones anteriores se migran al primer acceso si el archivo
sigue presente. Para migrarlos todos y precalentar sus resultados después del
despliegue, ejecute desde el servicio `app`:

```powershell
docker compose exec app python scripts/backfill_documentos_persistidos.py
```

El comando no borra ni modifica los originales. Informa archivos ausentes o
ilegibles y termina con código distinto de cero para poder corregirlos y repetir
la operación.

## Navegador

Los recursos estáticos conservan caché pública de un año y su URL cambia con el
SHA-256 del contenido. Las respuestas privadas usan `Cache-Control: private,
no-store`; la aplicación no guarda páginas de aprendices en `localStorage`,
`sessionStorage` ni una caché compartida. También se eliminó la precarga de HTML
al pasar el puntero: esa petición ejecutaba rutas costosas antes del clic. La
fluidez se obtiene reutilizando snapshots desde PostgreSQL y los recursos
estáticos desde el navegador.

## Operación

El worker procesa el reporte asíncrono y precalienta los snapshots tras confirmar
los datos importados. Las cargas de planeación y PDF encolan el mismo recálculo.
Si Redis no está disponible, la carga sigue registrada, el trabajo de resumen
queda con estado de error y la primera visita construye el snapshot. La caché de
resultados se renueva cada día y ante cambios de fuentes; no reemplaza los datos
de origen ni se usa como registro académico oficial.
