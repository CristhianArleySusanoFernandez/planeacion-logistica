"""Adaptador Supabase del RepositorioZonas. Solo traducción de datos."""

from collections.abc import Mapping, Sequence
from typing import Any

from postgrest.types import CountMethod
from supabase import Client

from planeacion.domain.modelo import MUNICIPIO_OTROS, Municipio, ReglaChiquinquira, Zona
from planeacion.domain.servicios.auditoria_zonas import ReferenciasMovidas
from planeacion.infraestructura.adaptadores.salida.supabase._filas import como_filas

TABLA = "zonas"
_COLUMNAS = "id, nombre, regla_chiquinquira, activa, municipios(nombre)"


def a_fila(zona: Zona, ids_municipios: Mapping[str, int]) -> dict[str, Any]:
    return {
        "nombre": zona.nombre,
        "municipio_id": ids_municipios[zona.municipio.nombre],
        "regla_chiquinquira": zona.regla_chiquinquira.value if zona.regla_chiquinquira else None,
        "activa": zona.activa,
    }


def desde_fila(fila: dict[str, Any]) -> Zona:
    anidado = fila.get("municipios")
    municipio = Municipio(nombre=anidado["nombre"]) if anidado else Municipio(nombre=MUNICIPIO_OTROS)
    regla_cruda = fila.get("regla_chiquinquira")
    return Zona(
        nombre=fila["nombre"],
        municipio=municipio,
        regla_chiquinquira=ReglaChiquinquira(regla_cruda) if regla_cruda else None,
        activa=fila["activa"],
    )


class RepositorioZonasSupabase:
    def __init__(self, cliente: Client) -> None:
        self._cliente = cliente

    def guardar_lote(self, zonas: Sequence[Zona], ids_municipios: Mapping[str, int]) -> dict[str, int]:
        filas = [a_fila(z, ids_municipios) for z in zonas]
        if filas:
            self._cliente.table(TABLA).upsert(filas, on_conflict="nombre").execute()
        respuesta = self._cliente.table(TABLA).select("id, nombre").limit(10000).execute()
        return {fila["nombre"]: fila["id"] for fila in como_filas(respuesta.data)}

    def obtener_por_nombre(self, nombre: str) -> Zona | None:
        respuesta = self._cliente.table(TABLA).select(_COLUMNAS).eq("nombre", nombre).execute()
        datos = como_filas(respuesta.data)
        return desde_fila(datos[0]) if datos else None

    def listar(self) -> list[Zona]:
        respuesta = self._cliente.table(TABLA).select(_COLUMNAS).order("nombre").limit(10000).execute()
        return [desde_fila(fila) for fila in como_filas(respuesta.data)]

    def actualizar_zona(self, zona: Zona) -> None:
        respuesta = self._cliente.table("municipios").select("id, nombre").execute()
        ids_municipios = {fila["nombre"]: int(fila["id"]) for fila in como_filas(respuesta.data)}
        if zona.municipio.nombre not in ids_municipios:
            raise LookupError(f"el municipio {zona.municipio.nombre!r} no existe en la base")
        self._cliente.table(TABLA).upsert(a_fila(zona, ids_municipios), on_conflict="nombre").execute()

    def eliminar_zona(self, nombre: str) -> None:
        zona_id = self._id_de_zona(nombre)
        referencias = {
            "cliente(s)": self._contar("clientes", "zona_id", zona_id),
            "override(s)": self._contar("overrides_zona", "zona_id", zona_id),
            "asignación(es) de planeación": self._contar("planeacion_asignaciones", "zona_id", zona_id),
        }
        detalle = ", ".join(f"{n} {etiqueta}" for etiqueta, n in referencias.items() if n)
        if detalle:
            raise ValueError(
                f"no se puede borrar la zona {nombre!r}: la referencian {detalle}. "
                "Reasigna esas referencias o desactívala (activa = false) en su lugar."
            )
        # El repertorio (carro_zonas) se borra en cascada: es configuración dependiente.
        self._cliente.table(TABLA).delete().eq("id", zona_id).execute()

    def fusionar_zona(self, nombre_variante: str, nombre_canonica: str) -> ReferenciasMovidas:
        id_variante = self._id_de_zona(nombre_variante)
        id_canonica = self._id_de_zona(nombre_canonica)
        if id_variante == id_canonica:
            raise ValueError(f"la zona {nombre_variante!r} no se puede fusionar consigo misma")

        # clientes y overrides_zona no tienen unique sobre zona_id (overrides es
        # único por cliente_codigo), así que reapuntar la FK basta.
        clientes = self._reapuntar("clientes", id_variante, id_canonica)
        overrides = self._reapuntar("overrides_zona", id_variante, id_canonica)
        # planeacion_asignaciones tampoco: es histórico, una fila por zona y corrida.
        planeaciones = self._reapuntar("planeacion_asignaciones", id_variante, id_canonica)
        repertorio = self._fusionar_repertorio(id_variante, id_canonica)

        self._cliente.table(TABLA).delete().eq("id", id_variante).execute()
        return ReferenciasMovidas(
            clientes=clientes,
            repertorio=repertorio,
            overrides=overrides,
            planeaciones=planeaciones,
        )

    def _id_de_zona(self, nombre: str) -> int:
        respuesta = self._cliente.table(TABLA).select("id").eq("nombre", nombre).execute()
        datos = como_filas(respuesta.data)
        if not datos:
            raise LookupError(f"la zona {nombre!r} no existe en la base")
        return int(datos[0]["id"])

    def _reapuntar(self, tabla: str, id_variante: int, id_canonica: int) -> int:
        movidas = self._contar(tabla, "zona_id", id_variante)
        if movidas:
            self._cliente.table(tabla).update({"zona_id": id_canonica}).eq("zona_id", id_variante).execute()
        return movidas

    def _fusionar_repertorio(self, id_variante: int, id_canonica: int) -> int:
        """carro_zonas tiene unique (carro_id, zona_id): los carros que ya tenían
        la canónica solo pierden su fila de la variante, no se duplican."""
        respuesta = (
            self._cliente.table("carro_zonas")
            .select("carro_id, zona_id")
            .in_("zona_id", [id_variante, id_canonica])
            .limit(10000)
            .execute()
        )
        filas = como_filas(respuesta.data)
        con_variante = {int(f["carro_id"]) for f in filas if int(f["zona_id"]) == id_variante}
        con_canonica = {int(f["carro_id"]) for f in filas if int(f["zona_id"]) == id_canonica}

        self._cliente.table("carro_zonas").delete().eq("zona_id", id_variante).execute()
        por_agregar = sorted(con_variante - con_canonica)
        if por_agregar:
            self._cliente.table("carro_zonas").insert(
                [{"carro_id": carro_id, "zona_id": id_canonica} for carro_id in por_agregar]
            ).execute()
        return len(con_variante)

    def _contar(self, tabla: str, columna: str, valor: int) -> int:
        # Se cuenta sobre la propia columna FK: "clientes" no tiene columna id.
        respuesta = (
            self._cliente.table(tabla)
            .select(columna, count=CountMethod.exact)
            .eq(columna, valor)
            .limit(1)
            .execute()
        )
        return int(respuesta.count or 0)
