# CLAUDE.md

Contexto para asistentes de IA que trabajen en este repositorio.

- **Dominio y arquitectura**: [`docs/dominio.md`](docs/dominio.md) — el negocio, el glosario, las
  reglas, la estructura hexagonal, el formato de los archivos de ECOM y las convenciones de código.
  Leerlo completo antes de tocar nada.
- **Instalación, comandos y despliegue**: [`README.md`](README.md).
- **Cruce vehículos ↔ rutas de reparto**: [`docs/mapeo-vehiculos-rutas.md`](docs/mapeo-vehiculos-rutas.md).

Reglas rápidas: todo en español (código, comentarios, commits); `domain` y `application` no importan
nada de `infraestructura`; `Decimal` para dinero, nunca `float`; cada servicio de dominio y cada caso
de uso llevan pruebas. Antes de dar por terminado un cambio: `uv run ruff check`, `uv run mypy src` y
`uv run pytest`.
