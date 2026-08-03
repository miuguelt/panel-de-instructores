# DevBrain — estándar canónico de desarrollo multi-IDE

**Versión:** 7.0 · **Fecha:** 2026-08-01

## 1. Autoridad y contexto

1. Para estado operativo mandan, en orden: `AI-SESSION-BRIEF.md`, `AI-CURRENT-CONFIG.md`, `_core/DEVBRAIN_RUNTIME_POLICY.md`, el `AGENTS.md` del proyecto y este estándar.
2. Al iniciar sesión se consulta `devbrain_brief`. Para cada tarea se consulta `devbrain_task_context` con la intención concreta y, si aplica, el proyecto.
3. Para arquitectura, impacto, dependencias, depuración o refactor se consulta Codebase Memory antes de verificar los archivos exactos. Tras cambios estructurales se refresca el índice.
4. Las referencias históricas nunca reemplazan la configuración vigente.

## 2. Runtime Windows nativo

- PostgreSQL 18: `127.0.0.1:5434`, servicio `postgresql-x64-18`.
- Memurai: `127.0.0.1:6380`, servicio `Memurai`.
- Gateway MCP único: `127.0.0.1:8010`. Dashboard: `127.0.0.1:8051`.
- No usar WSL, Docker, Qdrant, SearXNG, Redis 6379 ni inferencia LLM local.
- `devbrain start` inicia únicamente el núcleo compartido. Los proyectos se inician explícitamente con `devbrain start <proyecto>` o su script autorizado.
- Los MCP stdio no son servicios HTTP y no se levantan manualmente con puertos.

## 3. Credenciales y seguridad

- Windows Credential Manager es la fuente preferida. Un `.env` local, ignorado y protegido solo se permite cuando el runtime lo requiere.
- Nunca guardar secretos en JSON/JSONC, Markdown, código, prompts, logs, snapshots, argumentos de comandos ni configuraciones de IDE.
- No leer, mostrar ni copiar el contenido de `.env` o credenciales salvo que la tarea lo requiera expresamente y exista un flujo seguro.
- Todo secreto expuesto se elimina de la superficie activa y se rota de forma coordinada.
- Antes de commit se ejecutan el detector de secretos y `validate-rules.ps1`.

## 4. Autonomía objetiva

- Investigar, leer, comparar, probar y diagnosticar proactivamente dentro del alcance solicitado.
- Modificar únicamente lo autorizado por la tarea. No reparar otros proyectos “en caliente”, no arrancar aplicaciones implícitamente y no hacer cambios destructivos por intuición.
- Si una decisión cambia arquitectura, datos, credenciales o alcance, presentar evidencia y detenerse cuando falte autoridad material.
- Informar resultado, alcance, verificación, riesgos y bloqueos; no afirmar éxito sin evidencia.

## 5. Código y calidad

- Código, identificadores y comentarios técnicos en inglés donde el repositorio ya lo use; comunicación al operador en español.
- No dejar código comentado, mocks que suplanten datos persistentes ni binarios en directorios de código.
- Go mínimo 1.25, módulos `github.com/devbrain/`, sin `panic()` en handlers y sin IP/puertos hardcodeados.
- Los errores para el operador deben ser claros, accionables y en español.
- Aplicar el estilo, pruebas, linters y `AGENTS.md` específicos del proyecto.

## 6. UI, legibilidad y Colombia

- Interfaz en español de Colombia (`es-CO`), con fechas y números que declaren el locale.
- Nunca truncar contenido con `text-overflow: ellipsis`; permitir salto con `overflow-wrap: break-word`. Solo se admite truncado en chrome compacto como badges o botones.
- Mobile-first desde 320 px y soporte hasta 2560 px. Usar `clamp()`, Grid con `minmax()` y breakpoints ascendentes.
- Tablas y bloques de código: scroll horizontal seguro; bloques de código con `white-space: pre-wrap` y `word-break: break-word`.
- Contraste suficiente, fondos sólidos para texto y estados legibles sin depender solo del color.
- En HTML, escapar `<` y `>` dentro de ejemplos de código y cerrar siempre `<textarea></textarea>`.

## 7. Verificación y sincronización

1. Después de editar este archivo: `./sync-rules.ps1 -Apply`.
2. Antes de commit: `./validate-rules.ps1` y el hook anti-secretos.
3. Tras cambios DevBrain: sincronizar conocimiento en modo estricto, validar configuración canónica, sincronizar IDEs y ejecutar las pruebas MCP.
4. Verificar el gateway en `/health`, los puertos canónicos y el contexto de tareas representativas.
5. Un fallo de validación bloquea el commit; un hook posterior solo actualiza índices y nunca sustituye la validación previa.

Este archivo es el estándar de desarrollo distribuido a los proyectos. No reemplaza las fuentes de autoridad operativa indicadas en la sección 1.
