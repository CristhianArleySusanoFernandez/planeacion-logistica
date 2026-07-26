"""Adaptador Supabase del RepositorioMunicipios. Solo traducción de datos."""

from collections.abc import Sequence
from typing import Any

from supabase import Client

from planeacion.domain.modelo import Municipio
from planeacion.infraestructura.adaptadores.salida.supabase._filas import como_filas

TABLA = "municipios"


def a_fila(municipio: Municipio) -> dict[str, Any]:
    return {"nombre": municipio.nombre}


def desde_fila(fila: dict[str, Any]) -> Municipio:
    return Municipio(nombre=fila["nombre"])


class RepositorioMunicipiosSupabase:
    def __init__(self, cliente: Client) -> None:
        self._cliente = cliente

    def guardar_lote(self, municipios: Sequence[Municipio]) -> dict[str, int]:
        filas = [a_fila(m) for m in municipios]
        if filas:
            self._cliente.table(TABLA).upsert(filas, on_conflict="nombre").execute()
        respuesta = self._cliente.table(TABLA).select("id, nombre").execute()
        return {fila["nombre"]: fila["id"] for fila in como_filas(respuesta.data)}

    def listar(self) -> list[Municipio]:
        respuesta = self._cliente.table(TABLA).select("*").order("nombre").execute()
        return [desde_fila(fila) for fila in como_filas(respuesta.data)]
