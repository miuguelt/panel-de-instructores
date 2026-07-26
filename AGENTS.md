# SENA Control Academico - ADSO

## Descripcion
Aplicacion web para control de llamado a lista, tareas y evidencias de aprendices SENA.
Regional Santander - Centro de Gestion Agroempresarial de Velez.

## Stack
- Backend: Flask + SQLAlchemy + Flask-Migrate
- Frontend: Jinja2 + HTMX (server-rendered, mobile-first)
- BD: PostgreSQL 18 (puerto 5434, base `adso_control`)
- Redis: Memurai (puerto 6380, DB 1 para rate-limiting)
- Puerto backend: 8009

## Inicio rapido
```powershell
.\start-windows.ps1
```
O manualmente:
```powershell
.\venv\Scripts\Activate.ps1
python wsgi.py
```

## Credenciales admin
- Correo: admin@sena.edu.co
- Contrasena: admin123
(Cambiar en produccion)

## Estructura
```
app/
  models/       # SQLAlchemy models
  routes/       # Blueprints (auth, instructor, aprendiz, api)
  templates/    # Jinja2 templates
  static/css/   # Estilos mobile-first
migrations/     # Flask-Migrate (Alembic)
uploads/        # Archivos de aprendices y materiales
wsgi.py         # Punto de entrada
start-windows.ps1  # Script de arranque
```

## Modulos
1. **Auth** - Login/registro instructores (correo @sena.edu.co)
2. **Fichas** - Crear fichas, cargar aprendices via Excel
3. **Asistencia** - Llamado a lista rapido, causal justificada
4. **Tareas** - Crear tareas, ver entregas, calificar
5. **Alertas** - Umbrales configurables (amarillo/rojo)
6. **Vista aprendiz** - Sin cuenta, acceso por documento

## Vista aprendiz (publica)
URL: `/aprendiz/{ficha_id}`
El aprendiz ingresa su numero de documento y ve:
- Asistencia y porcentaje
- Tareas pendientes/entregadas
- Subir evidencias
- Alertas de rendimiento

## BD
- Base: `adso_control`
- Usuario: `adso`
- Password: `adso_pass`
- Host: 127.0.0.1:5434

## Reglas
- Aprendices NO tienen cuenta de usuario
- Umbrales de alerta son configurables por ficha
- Textos en espanol colombiano natural
- Colores SENA: verde #39A900, blanco, acentos naranja
- Legibilidad N°1: PROHIBIDO hardcodear colores de texto o fondos (ej. #111827, #ffffff, rgba). Todo componente UI DEBE consumir variables CSS de tema (`var(--bg-card)`, `var(--bg-surface)`, `var(--text-strong)`, `var(--text-main)`, `var(--text-muted)`). Badges deben ser sólidos de alto contraste.

