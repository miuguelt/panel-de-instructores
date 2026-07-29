# Estándar de Carga de Archivos — ADSO Control Académico

## Principios

1. **SSOT**: Toda operación de archivos pasa por `app/services/archivos.py`. Ninguna ruta implementa su propia validación, generación de nombre, almacenamiento **ni envío al navegador**.
2. **Validación en cascada**: extensión → MIME header → magic bytes → tamaño.
3. **Nombres únicos y seguros**: `secure_filename()` + UUID prefix. Sin colisiones, sin path traversal.
4. **Escritura atómica**: el contenido va a `<nombre>.part` y solo se renombra al destino si llegó completo y con tamaño > 0. Una subida cortada nunca deja un archivo de 0 bytes referenciado en la BD.
5. **Subdirectorios canónicos**: 4 categorías fijas definidas en `TiposCarpeta`.
6. **Acceso controlado**: materiales y soportes pasan por `aprendiz.descargar_archivo`; una evidencia del instructor pasa por `instructor.descargar_archivo_entrega`, vinculada al `entrega_id`.
7. **Aislamiento de evidencias**: las nuevas entregas se guardan en `ficha/instructor/aprendiz/tarea`; la base permite una sola entrega por pareja tarea-aprendiz.
8. **Descarga reanudable y con nombre legible**: `ArchivoService.enviar()` emite ETag/Last-Modified, atiende `Range` y devuelve el nombre original en vez del nombre técnico.

## Arquitectura

```
Route (request.files['campo'])
    → ArchivoService.guardar(archivo, carpeta, ...)
        → validar_extension()
        → validar_mime()        [opcional]
        → validar_magic_bytes() [opcional]
        → generar_nombre()
        → os.makedirs() + save()
        → return ResultadoGuardar(url, ruta, nombre, tamaño)
    → Guardar url en BD
    → Commit
```

## Uso en rutas

### Guardar archivo

```python
from app.services.archivos import ArchivoService, TiposCarpeta, ErrorArchivo

try:
    resultado = ArchivoService.guardar(
        archivo=request.files['campo'],
        carpeta=TiposCarpeta.ENTREGAS,           # obligatorio
        subcarpeta=f'ficha_{ficha_id}/instructor_{tarea.instructor_id}/aprendiz_{aprendiz.id}/tarea_{tarea.id}',
        prefijo_extra=f'tarea_{tarea.id}',
        check_mime=True,                          # default True
        check_magic=False,                        # default False (rendimiento)
    )
    # resultado.url        → "entregas/ficha_3/instructor_7/aprendiz_42/tarea_9/tarea_9_uuid_documento.pdf"
    # resultado.ruta       → "C:/.../uploads/entregas/abc123_documento.pdf"
    # resultado.nombre_original → "documento.pdf"
    # resultado.tamano     → 102400
    modelo.url_archivo = resultado.url
except ErrorArchivo as exc:
    flash(str(exc), 'error')
```

### Eliminar archivo

```python
ArchivoService.eliminar(modelo.url_archivo)
```

### Consultar tamaño

```python
ArchivoService.obtener_tamano(modelo.url_archivo)
```

### Descargar (en la ruta)

```python
raiz, relativa, candidatos = _resolver_archivo_subido(filename)
# ...verificar permisos...
return ArchivoService.enviar(
    raiz,
    relativa,
    nombre_descarga='Guia_JEE.docx',   # opcional: por defecto se infiere el original
    inline=request.args.get('inline') == '1',
)
```

`enviar()` aporta, en un solo punto:

| Comportamiento | Efecto |
|---|---|
| `conditional=True` | `Range` (descarga reanudable) + `304` en revisitas |
| `download_name` | nombre original, sin el prefijo UUID |
| `mimetype` explícito | docx/xlsx/pptx abren bien aunque la imagen slim no tenga `/etc/mime.types` |
| `inline` restringido | solo `png/jpg/jpeg/pdf`; el resto se fuerza como adjunto |
| `nosniff` + `Cache-Control: private` | nada se interpreta como HTML ni queda en cachés compartidas |

### Descargar / previsualizar

```jinja
{# En templates, NUNCA usar url_for('static', ...) para archivos subidos #}
<a href="{{ url_for('aprendiz.descargar_archivo', filename=m.url_archivo) }}">
    Descargar
</a>

{# Para vista previa de imágenes #}
<img src="{{ url_for('aprendiz.descargar_archivo', filename=m.url_archivo, inline=1) }}">
```

## Subdirectorios canónicos (TiposCarpeta)

| Enum | Carpeta en disco | Contenido |
|------|-----------------|-----------|
| `MATERIALES_TAREA` | `uploads/materiales/` | Material de apoyo adjunto a tareas |
| `MATERIALES_FICHA` | `uploads/materiales_ficha/{ficha_id}/` | Materiales generales de ficha |
| `ENTREGAS` | `uploads/entregas/ficha_{ficha}/instructor_{instructor}/aprendiz_{aprendiz}/tarea_{tarea}/` | Evidencias de tareas de aprendices |
| `JUSTIFICACIONES` | `uploads/justificaciones/` | Soportes de inasistencia |

## Validaciones

### 1. Extensión (siempre activa)
Contra `ALLOWED_EXTENSIONS` en `config.py`. Actualmente:
`pdf, png, jpg, jpeg, zip, rar, xlsx, xls, doc, docx, pptx`

### 2. MIME header (activado por defecto)
`check_mime=True` verifica `archivo.content_type` contra `MIME_POR_EXTENSION`.
El cliente puede falsear este header, por eso es informativo + preventivo.

### 3. Magic bytes `check_magic=True` (activado por defecto)
Lee 1 KB del archivo y lo compara con firmas conocidas. Se lee 1 KB y no 32 B
porque hay PDF válidos con bytes previos a `%PDF`. Cubre PDF, PNG, JPEG, ZIP
(incluidos los contenedores vacíos `PK\x05\x06`), RAR y OLE (doc/xls/ppt).

### 4. Tamaño
- Global, a nivel Flask: `MAX_CONTENT_LENGTH = 50MB` en `config.py`. El error 413 tiene template propio en `app/__init__.py`.
- Por archivo, tras escribirlo: 0 bytes → `ErrorArchivoVacio`; por encima del límite → `ErrorTamano`. En ambos casos el `.part` se borra y nada llega a la BD.

## Frontend

`app/static/js/uploads.js` (cargado desde `base.html`) intercepta todo
formulario `multipart/form-data`:

- valida tamaño y extensión **antes** de enviar (evita esperar 50 MB para un 413);
- muestra porcentaje real de subida y bloquea el doble envío;
- traduce 413 / 429 / error de red a un mensaje en español;
- al terminar navega a `xhr.responseURL`, así los mensajes flash del patrón
  POST-Redirect-GET se ven igual que sin JavaScript.

Para excluir un formulario concreto: `data-sin-progreso`. Si el navegador no
soporta `FormData`/progreso, no se intercepta nada.

## Persistencia en Coolify

| Qué | Dónde |
|---|---|
| Evidencias, materiales, soportes | volumen `adso_uploads` → `/app/uploads` |
| Excel en cola de importación | `/app/uploads/importaciones/` (mismo volumen; el worker corre en otro contenedor y solo comparte esto) |
| Estado de los trabajos, rutas de archivos | PostgreSQL (servicio aparte de Coolify) |
| Testigo de salud del worker | `/tmp` — efímero a propósito |

El volumen es **nombrado**, no un bind al repositorio ni uno anónimo: un
`docker compose up -d --build`, un redeploy o un cambio de imagen **no** lo
tocan. Lo que sí lo borra es `docker compose down -v` o el "delete volumes" de
Coolify. `tests/test_persistencia_despliegue.py` verifica estas condiciones sin
necesidad de Docker.

### Respaldo y restauración del volumen

```bash
docker run --rm -v adso_uploads:/datos -v "$PWD":/respaldo alpine \
  tar czf /respaldo/adso_uploads_$(date +%F).tar.gz -C /datos .
```

```bash
docker run --rm -v adso_uploads:/datos -v "$PWD":/respaldo alpine \
  tar xzf /respaldo/adso_uploads_2026-07-29.tar.gz -C /datos
```

El respaldo de archivos solo sirve junto con el de PostgreSQL: las rutas y los
permisos de cada archivo viven en la base.

## Operación

- El volumen `uploads` está montado en `app` y `worker` (`docker-compose.yml`).
- En el arranque se comprueba que la carpeta exista y sea escribible; si no lo
  es, queda en el log y `/health` responde `status: degraded`.
- `GET /health?uploads=1` devuelve inventario: nº de archivos, bytes totales,
  archivos de **0 bytes** (subidas cortadas antes de este estándar) y `.part`
  residuales.

## Seguridad

- **Path traversal**: `_resolver_archivo_subido()` usa `Path.relative_to()` para garantizar que la ruta resuelta esté dentro de `UPLOAD_FOLDER`.
- **Control de acceso**: `_puede_descargar_archivo()` verifica autenticación y pertenencia del archivo a la ficha/aprendiz.
- **Rate limiting**: Subidas de aprendiz: 10/min. Descargas: 30/min.
- **CSRF**: Todos los formularios incluyen `{{ csrf_token() }}`.

## Lo que NO debe hacerse

```python
# MAL: validación inline, sin servicio centralizado
ext = archivo.filename.rsplit('.', 1)[-1].lower()
if ext not in current_app.config['ALLOWED_EXTENSIONS']:
    ...

# MAL: generar nombre sin secure_filename + UUID
filename = archivo.filename

# MAL: hardcodear fallback de extensiones
current_app.config.get('ALLOWED_EXTENSIONS', {'pdf', 'doc', ...})

# MAL: usar url_for('static', ...) para archivos subidos
url_for('static', filename='uploads/' ~ m.url_archivo)
```

## Excepciones del estándar

Las rutas de importación Excel (`importar_reporte_ficha`, `cargar_excel`) procesan el archivo en memoria y no lo persisten en disco. Estas usan validación inline con `endswith(('.xlsx', '.xls'))` porque el servicio `importar_archivo` necesita el stream completo. Son casos deliberadamente fuera del estándar.
