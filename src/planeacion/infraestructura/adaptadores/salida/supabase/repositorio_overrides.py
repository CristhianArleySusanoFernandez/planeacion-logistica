"""Adaptador Supabase del RepositorioOverrides. Solo traducción de datos."""

from collections.abc import Mapping, Sequence
from typing import Any

from supabase import Client

from planeacion.domain.modelo import OverrideZona
from planeacion.infraestructura.adaptadores.salida.supabase._filas import como_filas

TABLA = "overrides_zona"
_COLUMNAS = "cliente_codigo, zonas(nombre)"


def a_fila(override: OverrideZona, ids_zonas: Mapping[str, int]) -> dict[str, Any]:
    return {
        "cliente_codigo": override.cliente_codigo,
        "zona_id": ids_zonas[override.zona_nombre],
    }


def desde_fila(fila: dict[str, Any]) -> OverrideZona:
    return OverrideZona(
        cliente_codigo=fila["cliente_codigo"],
        zona_nombre=fila["zonas"]["nombre"],
    )


class RepositorioOverridesSupabase:
    def __init__(self, cliente: Client) -> None:
        self._cliente = cliente

    def guardar_lote(self, overrides: Sequence[OverrideZona], ids_zonas: Mapping[str, int]) -> int:
        filas = [a_fila(o, ids_zonas) for o in overrides]
        if filas:
            self._cliente.table(TABLA).upsert(filas, on_conflict="cliente_codigo").execute()
        return len(filas)

    def listar(self) -> list[OverrideZona]:
        respuesta = self._cliente.table(TABLA).select(_COLUMNAS).order("cliente_codigo").execute()
        return [desde_fila(fila) for fila in como_filas(respuesta.data)]

    def guardar_override(self, override: OverrideZona) -> None:
        respuesta = self._cliente.table("zonas").select("id").eq("nombre", override.zona_nombre).execute()
        filas = como_filas(respuesta.data)
        if not filas:
            raise LookupError(f"la zona {override.zona_nombre!r} no existe en la base")
        fila = a_fila(override, {override.zona_nombre: int(filas[0]["id"])})
        self._cliente.table(TABLA).upsert(fila, on_conflict="cliente_codigo").execute()

    def eliminar(self, cliente_codigo: str) -> None:
        self._cliente.table(TABLA).delete().eq("cliente_codigo", cliente_codigo).execute()
