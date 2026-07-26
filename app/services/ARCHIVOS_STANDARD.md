# Estándar de Carga de Archivos — ADSO Control Académico

## Principios

1. **SSOT**: Toda operación de archivos pasa por `app/services/archivos.py`. Ninguna ruta implementa su propia validación, generación de nombre o almacenamiento.
2. **Validación en cascada**: extensión → MIME header → magic bytes → tamaño.
3. **Nombres únicos y seguros**: `secure_filename()` + UUID prefix. Sin colisiones, sin path traversal.
4. **Subdirectorios canónicos**: 4 categorías fijas definidas en `TiposCarpeta`.
5. **Acceso controlado**: materiales y soportes pasan por `aprendiz.descargar_archivo`; una evidencia del instructor pasa por `instructor.descargar_archivo_entrega`, vinculada al `entrega_id`.
6. **Aislamiento de evidencias**: las nuevas entregas se guardan en `ficha/instructor/aprendiz/tarea`; la base permite una sola entrega por pareja tarea-aprendiz.

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

### 3. Magic bytes `check_magic=False` (desactivado por defecto)
Lee los primeros 32 bytes del archivo y los compara con firmas conocidas.
Se recomienda activar (`check_magic=True`) en subidas de aprendices (menos confiables).

### 4. Tamaño (a nivel Flask, global)
`MAX_CONTENT_LENGTH = 50MB` en `config.py`. El error 413 tiene template propio en `app/__init__.py`.

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
