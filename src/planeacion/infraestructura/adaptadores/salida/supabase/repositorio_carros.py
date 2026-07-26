"""Adaptador Supabase del RepositorioCarros. Solo traducción de datos."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from postgrest.types import CountMethod
from supabase import Client

from planeacion.domain.modelo import Carro, Municipio
from planeacion.infraestructura.adaptadores.salida.supabase._filas import como_filas

TABLA = "carros"
_COLUMNAS = "numero, conductor, placa, auxiliar, es_externo, costo_diario, activo, municipios(nombre)"


def a_fila(carro: Carro, ids_municipios: Mapping[str, int]) -> dict[str, Any]:
    municipio_id = ids_municipios.get(carro.municipio.nombre) if carro.municipio else None
    return {
        "numero": carro.numero,
        "conductor": carro.conductor,
        "placa": carro.placa,
        "auxiliar": carro.auxiliar,
        "municipio_id": municipio_id,
        "es_externo": carro.es_externo,
        # str porque Decimal no es serializable a JSON; Postgres lo castea a numeric.
        "costo_diario": str(carro.costo_diario),
        "activo": carro.activo,
    }


def desde_fila(fila: dict[str, Any]) -> Carro:
    anidado = fila.get("municipios")
    return Carro(
        numero=fila["numero"],
        conductor=fila.get("conductor"),
        placa=fila.get("placa"),
        auxiliar=fila.get("auxiliar"),
        municipio=Municipio(nombre=anidado["nombre"]) if anidado else None,
        es_externo=fila["es_externo"],
        costo_diario=Decimal(str(fila["costo_diario"])),
        activo=fila["activo"],
    )


class RepositorioCarrosSupabase:
    def __init__(self, cliente: Client) -> None:
        self._cliente = cliente

    def guardar_lote(self, carros: Sequence[Carro], ids_municipios: Mapping[str, int]) -> int:
        filas = [a_fila(c, ids_municipios) for c in carros]
        if filas:
            self._cliente.table(TABLA).upsert(filas, on_conflict="numero").execute()
        return len(filas)

    def obtener_por_numero(self, numero: str) -> Carro | None:
        respuesta = self._cliente.table(TABLA).select(_COLUMNAS).eq("numero", numero).execute()
        datos = como_filas(respuesta.data)
        return desde_fila(datos[0]) if datos else None

    def listar(self) -> list[Carro]:
        respuesta = self._cliente.table(TABLA).select(_COLUMNAS).order("numero").execute()
        return [desde_fila(fila) for fila in como_filas(respuesta.data)]

    def actualizar_carro(self, carro: Carro) -> None:
        ids_municipios = self._ids_municipios()
        if carro.municipio and carro.municipio.nombre not in ids_municipios:
            raise LookupError(f"el municipio {carro.municipio.nombre!r} no existe en la base")
        fila = a_fila(carro, ids_municipios)
        self._cliente.table(TABLA).upsert(fila, on_conflict="numero").execute()

    def eliminar_carro(self, numero: str) -> None:
        respuesta = self._cliente.table(TABLA).select("id").eq("numero", numero).execute()
        datos = como_filas(respuesta.data)
        if not datos:
            raise LookupError(f"el carro {numero!r} no existe en la base")
        carro_id = int(datos[0]["id"])
        asignaciones = (
            self._cliente.table("planeacion_asignaciones")
            .select("carro_id", count=CountMethod.exact)
            .eq("carro_id", carro_id)
            .limit(1)
            .execute()
        )
        if asignaciones.count:
            raise ValueError(
                f"no se puede borrar el carro {numero!r}: lo referencian "
                f"{asignaciones.count} asignación(es) de planeaciones guardadas. "
                "Desactívalo (activo = false) en su lugar."
            )
        # El repertorio (carro_zonas) se borra en cascada: es configuración dependiente.
        self._cliente.table(TABLA).delete().eq("id", carro_id).execute()

    def _ids_municipios(self) -> dict[str, int]:
        respuesta = self._cliente.table("municipios").select("id, nombre").execute()
        return {fila["nombre"]: int(fila["id"]) for fila in como_filas(respuesta.data)}
