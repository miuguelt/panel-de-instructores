# DevBrain — reglas del workspace

Este archivo es un **puntero generado**. No lo edites: se regenera y perderás el cambio.

La fuente única del estándar es `.antigravityrules` en la raíz del workspace
(`C:\Users\Miguel\Documents\Aplicaciones\.antigravityrules`), publicada en el
catálogo como el asset `policy.antigravity`.

Hasta 2026-08-20 este archivo era una copia íntegra de 20 KB de esa fuente, y
había 228 copias como esta repartidas por 38 proyectos: seis nombres distintos,
el mismo contenido, ninguno capaz de discrepar sin que nadie lo notara. Ahora el
estándar se sirve por tarea desde el catálogo, y aquí queda solo lo que no admite
matices.

## Reglas duras (aplican siempre, sin consultar nada más)

- **Runtime**: Windows nativo. PostgreSQL `127.0.0.1:5434`, Redis/Memurai
  `127.0.0.1:6380`, gateway MCP `127.0.0.1:8010`, dashboard `127.0.0.1:8051`.
- **Prohibido en desarrollo**: WSL, Docker, Ollama, Qdrant, SearXNG, Redis 6379,
  PostgreSQL 5433, dashboard 8050, gateway 7777/8011, bridges 7800/7801.
- **Credenciales**: solo desde Windows Credential Manager o un `.env` local
  protegido. Nunca en código, JSON, reglas, prompts ni logs. El hook de edición
  bloquea la escritura si detecta un secreto en claro.
- **Procesos**: nunca matar por nombre. `mcp-lightning-proxy.exe` corre a la vez
  como maestro DevBrain y como relay stdio de cada IDE; resolver siempre un PID
  concreto por pidfile, puerto o línea de comandos.
- **Obsoleto**: `_archive/`, `backups/`, `vault/`, `legacy/`, `_graveyard/` no se
  leen para decidir ni se ejecutan. Para retirar algo, cuarentena con motivo y
  caducidad; nunca renombrar a `_OLD` en su sitio ni dejar `.bak` junto al vivo.
- **Idioma**: interfaz y textos en español de Colombia (`es-CO`); código y
  comentarios técnicos en inglés donde el repositorio ya lo use.

## El resto del estándar

Arquitectura modular, calidad de código, UI/UX, higiene de repositorio,
verificación y guías educativas se sirven según la tarea:

```
mcp-core__devbrain_task_context   → qué agente, workflow y reglas aplican
mcp-core__devbrain_asset_get      → el cuerpo completo de un asset concreto
```

Para el estándar entero: `devbrain_asset_get` con `asset_key = policy.antigravity`.
