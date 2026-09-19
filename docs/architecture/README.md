# Arquitectura de panel de instructores

## Fuerzas del problema

Documenta dominio, ritmo de cambio, integraciones, persistencia, concurrencia y restricciones reales antes de elegir un patrón.

## Patrón y límites

- Patrón inicial: vertical slice por funcionalidad.
- Cada archivo de implementación tiene una capacidad pública principal.
- Dependencias hacia contratos estables; no hay ciclos ni imports de detalles privados entre funcionalidades.
- Routes/controllers son delgados; dominio y casos de uso no dependen de infraestructura.

## Presupuesto modular

- Objetivo: 250 líneas por archivo y 40 por función; revisión obligatoria en 400/80.
- Los límites disparan una revisión de cohesión, complejidad, dependencias y ritmo de cambio; se divide por responsabilidades distintas, no para crear archivos triviales.
- Gate: Test-DevBrainModularity.ps1 -Path . -ChangedOnly -FailOnViolations.

Registra decisiones transversales en esta carpeta y excepciones temporales en xceptions.md.