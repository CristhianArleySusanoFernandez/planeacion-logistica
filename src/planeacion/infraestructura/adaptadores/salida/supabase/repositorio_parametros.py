"""Adaptador Supabase del RepositorioParametros. Solo traducción de datos.

La tabla guarda únicamente los valores cambiados: el catálogo (qué parámetros
existen y cuánto valen por defecto) vive en el dominio. Si la tabla todavía no
existe —migración 005 sin aplicar— se devuelve {} y la app sigue andando con los
defaults, que es exactamente lo que tiene que pasar.
"""

from decimal import Decimal
from typing import Any

from postgrest.exceptions import APIError
from supabase import Client

from planeacion.domain.modelo import CATALOGO, DEFECTOS
from planeacion.infraestructura.adaptadores.salida.supabase._filas import como_filas

TABLA = "parametros"
_COLUMNAS = "clave, valor"
# 42P01 es el undefined_table de Postgres; PGRST205 es el "not in the schema
# cache" con que PostgREST reporta lo mismo.
_TABLA_INEXISTENTE = ("42P01", "PGRST205")


def desde_fila(fila: dict[str, Any]) -> tuple[str, Decimal]:
    return str(fila["clave"]), Decimal(str(fila["valor"]))


class RepositorioParametrosSupabase:
    def __init__(self, cliente: Client) -> None:
        self._cliente = cliente

    def obtener(self) -> dict[str, Decimal]:
        """Los valores guardados; {} si la tabla no existe todavía.

        Las claves que no estén en el catálogo se ignoran: una fila escrita a mano
        en Supabase con un nombre inventado no tiene que llegar al dominio.
        """
        try:
            respuesta = self._cliente.table(TABLA).select(_COLUMNAS).execute()
        except APIError as error:
            if error.code in _TABLA_INEXISTENTE:
                return {}
            raise
        valores = dict(desde_fila(fila) for fila in como_filas(respuesta.data))
        return {clave: valor for clave, valor in valores.items() if clave in DEFECTOS}

    def guardar(self, clave: str, valor: Decimal) -> None:
        if clave not in DEFECTOS:
            raise LookupError(f"el parámetro {clave!r} no existe en el catálogo")
        self._cliente.table(TABLA).upsert(
            # str porque Decimal no es serializable a JSON; Postgres lo castea.
            {"clave": clave, "valor": str(valor), "descripcion": _descripcion(clave)},
            on_conflict="clave",
        ).execute()

    def restaurar_por_defecto(self) -> int:
        """Borra todas las filas: sin valores guardados manda el catálogo."""
        respuesta = self._cliente.table(TABLA).select("clave").execute()
        borrados = len(como_filas(respuesta.data))
        if borrados:
            self._cliente.table(TABLA).delete().neq("clave", "").execute()
        return borrados


def _descripcion(clave: str) -> str:
    """La descripción del catálogo, para que la tabla se entienda en Supabase."""
    return next(d.descripcion for d in CATALOGO if d.clave == clave)
