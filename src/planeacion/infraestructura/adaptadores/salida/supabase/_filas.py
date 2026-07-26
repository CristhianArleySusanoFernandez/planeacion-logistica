"""Ayuda de tipado: PostgREST tipa response.data como JSON genérico; aquí se
estrecha a la forma real (lista de filas) en un solo punto."""

from typing import Any, cast


def como_filas(datos: Any) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], datos)
