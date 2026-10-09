"""Adaptador Supabase del RepositorioClientes. Solo traducción de datos."""

from collections.abc import Mapping, Sequence
from typing import Any

from postgrest.types import CountMethod
from supabase import Client

from planeacion.domain.modelo import Cliente
from planeacion.infraestructura.adaptadores.salida.supabase import repositorio_zonas
from planeacion.infraestructura.adaptadores.salida.supabase._filas import como_filas

TABLA = "clientes"
_TAMANO_LOTE = 500
# El techo real lo pone el servidor (`max-rows` de Supabase) y no se puede subir
# desde el cliente: pedir 5.000 devuelve 1.000. Se deja en 1.000, que es lo que
# contesta de todas formas, y la maestra de 9.200 clientes sale en 10 viajes.
_TAMANO_PAGINA = 1000
_COLUMNAS = (
    "codigo, documento, razon_social, direccion, barrio, ciudad, dia_visita, activo, "
    "zonas(id, nombre, regla_chiquinquira, activa, municipios(nombre))"
)


def a_fila(cliente: Cliente, ids_zonas: Mapping[str, int]) -> dict[str, Any]:
    zona_id = ids_zonas.get(cliente.zona.nombre) if cliente.zona else None
    return {
        "codigo": cliente.codigo,
        "documento": cliente.documento,
        "razon_social": cliente.razon_social,
        "direccion": cliente.direccion,
        "barrio": cliente.barrio,
        "ciudad": cliente.ciudad,
        "zona_id": zona_id,
        "dia_visita": cliente.dia_visita,
        "activo": cliente.activo,
    }


def desde_fila(fila: dict[str, Any]) -> Cliente:
    anidado = fila.get("zonas")
    return Cliente(
        codigo=fila["codigo"],
        direccion=fila.get("direccion"),
        barrio=fila.get("barrio"),
        ciudad=fila.get("ciudad"),
        zona=repositorio_zonas.desde_fila(anidado) if anidado else None,
        documento=fila.get("documento"),
        razon_social=fila.get("razon_social"),
        dia_visita=fila.get("dia_visita"),
        activo=fila["activo"],
    )


class RepositorioClientesSupabase:
    def __init__(self, cliente: Client) -> None:
        self._cliente = cliente

    def guardar_lote(self, clientes: Sequence[Cliente], ids_zonas: Mapping[str, int]) -> int:
        filas = [a_fila(c, ids_zonas) for c in clientes]
        for inicio in range(0, len(filas), _TAMANO_LOTE):
            lote = filas[inicio : inicio + _TAMANO_LOTE]
            self._cliente.table(TABLA).upsert(lote, on_conflict="codigo").execute()
        return len(filas)

    def guardar_cliente(self, cliente: Cliente) -> None:
        ids_zona: dict[str, int] = {}
        if cliente.zona is not None:
            ids_zona[cliente.zona.nombre] = self._id_de_zona(cliente.zona.nombre)
        self._cliente.table(TABLA).upsert(a_fila(cliente, ids_zona), on_conflict="codigo").execute()

    def actualizar_zona(self, codigo: str, zona_nombre: str) -> None:
        zona_id = self._id_de_zona(zona_nombre)
        self._cliente.table(TABLA).update({"zona_id": zona_id}).eq("codigo", codigo).execute()

    def _id_de_zona(self, zona_nombre: str) -> int:
        respuesta = (
            self._cliente.table(repositorio_zonas.TABLA).select("id").eq("nombre", zona_nombre).execute()
        )
        filas = como_filas(respuesta.data)
        if not filas:
            raise LookupError(f"no existe la zona {zona_nombre!r} en la tabla zonas")
        return int(filas[0]["id"])

    def listar(self) -> list[Cliente]:
        """La maestra entera, paginada.

        El corte y el avance van por lo que DEVUELVE el servidor, no por el
        tamaño pedido: Supabase tiene un techo propio (`max-rows`, 1.000) y
        responde 1.000 filas aunque se le pidan 5.000. Medido: `range(0, 4999)`
        devuelve 1.000. Con la condición escrita contra el tamaño pedido, subir
        la página a 5.000 cortaba el bucle en la primera vuelta y **perdía 8.200
        clientes en silencio**. Así, cualquier tamaño de página es correcto.
        """
        clientes: list[Cliente] = []
        inicio = 0
        while True:
            respuesta = (
                self._cliente.table(TABLA)
                .select(_COLUMNAS)
                .order("codigo")
                .range(inicio, inicio + _TAMANO_PAGINA - 1)
                .execute()
            )
            pagina = como_filas(respuesta.data)
            clientes.extend(desde_fila(fila) for fila in pagina)
            if not pagina:
                return clientes
            inicio += len(pagina)

    def contar(self) -> int:
        respuesta = self._cliente.table(TABLA).select("codigo", count=CountMethod.exact, head=True).execute()
        return respuesta.count or 0
