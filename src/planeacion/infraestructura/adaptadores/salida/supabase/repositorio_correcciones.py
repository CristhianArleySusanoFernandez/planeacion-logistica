"""Adaptador Supabase del RepositorioCorrecciones. Solo traducción de datos."""

from collections.abc import Sequence
from typing import Any

from supabase import Client

from planeacion.domain.modelo import CorreccionUbicacion
from planeacion.infraestructura.adaptadores.salida.supabase._filas import como_filas

TABLA = "correcciones_ubicacion"


def a_fila(correccion: CorreccionUbicacion) -> dict[str, Any]:
    return {
        "cliente_codigo": correccion.cliente_codigo,
        "ciudad_real": correccion.ciudad_real,
        "barrio_real": correccion.barrio_real,
    }


def desde_fila(fila: dict[str, Any]) -> CorreccionUbicacion:
    return CorreccionUbicacion(
        cliente_codigo=fila["cliente_codigo"],
        ciudad_real=fila.get("ciudad_real"),
        barrio_real=fila.get("barrio_real"),
    )


class RepositorioCorreccionesSupabase:
    def __init__(self, cliente: Client) -> None:
        self._cliente = cliente

    def guardar_lote(self, correcciones: Sequence[CorreccionUbicacion]) -> int:
        filas = [a_fila(c) for c in correcciones]
        if filas:
            self._cliente.table(TABLA).upsert(filas, on_conflict="cliente_codigo").execute()
        return len(filas)

    def listar(self) -> list[CorreccionUbicacion]:
        respuesta = self._cliente.table(TABLA).select("*").order("cliente_codigo").execute()
        return [desde_fila(fila) for fila in como_filas(respuesta.data)]

    def guardar_correccion(self, correccion: CorreccionUbicacion) -> None:
        self._cliente.table(TABLA).upsert(a_fila(correccion), on_conflict="cliente_codigo").execute()

    def eliminar(self, cliente_codigo: str) -> None:
        self._cliente.table(TABLA).delete().eq("cliente_codigo", cliente_codigo).execute()
