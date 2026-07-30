"""Adaptador Supabase del RepositorioCarroZonas (el repertorio de zonas por carro)."""

from collections.abc import Sequence

from postgrest.exceptions import APIError
from supabase import Client

from planeacion.infraestructura.adaptadores.salida.supabase._filas import como_filas

TABLA = "carro_zonas"
# La tabla puede no existir aún: 42P01 es el undefined_table de Postgres y
# PGRST205 el "not in the schema cache" con que PostgREST reporta lo mismo.
_TABLA_INEXISTENTE = ("42P01", "PGRST205")


class RepositorioCarroZonasSupabase:
    def __init__(self, cliente: Client) -> None:
        self._cliente = cliente

    def obtener_todos(self) -> dict[str, set[str]]:
        try:
            respuesta = (
                self._cliente.table(TABLA).select("carros(numero), zonas(nombre)").limit(10000).execute()
            )
        except APIError as error:
            if error.code in _TABLA_INEXISTENTE:
                # Migración 002 sin aplicar: equivale a repertorio sin configurar,
                # así el balanceo diario no se cae por el orden del despliegue.
                return {}
            raise
        repertorio: dict[str, set[str]] = {}
        for fila in como_filas(respuesta.data):
            repertorio.setdefault(fila["carros"]["numero"], set()).add(fila["zonas"]["nombre"])
        return repertorio

    def asignar(self, numero_carro: str, nombre_zona: str) -> None:
        self.asignar_lote([(numero_carro, nombre_zona)])

    def asignar_lote(self, pares: Sequence[tuple[str, str]]) -> int:
        if not pares:
            return 0
        ids_carros = self._ids_por_clave("carros", "numero")
        ids_zonas = self._ids_por_clave("zonas", "nombre")
        filas = []
        for numero_carro, nombre_zona in pares:
            if numero_carro not in ids_carros:
                raise LookupError(f"el carro {numero_carro!r} no existe en la base")
            if nombre_zona not in ids_zonas:
                raise LookupError(f"la zona {nombre_zona!r} no existe en la base")
            filas.append({"carro_id": ids_carros[numero_carro], "zona_id": ids_zonas[nombre_zona]})
        self._cliente.table(TABLA).upsert(
            filas, on_conflict="carro_id,zona_id", ignore_duplicates=True
        ).execute()
        return len(filas)

    def quitar(self, numero_carro: str, nombre_zona: str) -> None:
        carro_id = self._id_de("carros", "numero", numero_carro)
        zona_id = self._id_de("zonas", "nombre", nombre_zona)
        self._cliente.table(TABLA).delete().eq("carro_id", carro_id).eq("zona_id", zona_id).execute()

    def _ids_por_clave(self, tabla: str, clave: str) -> dict[str, int]:
        respuesta = self._cliente.table(tabla).select(f"id, {clave}").limit(10000).execute()
        return {fila[clave]: int(fila["id"]) for fila in como_filas(respuesta.data)}

    def _id_de(self, tabla: str, clave: str, valor: str) -> int:
        respuesta = self._cliente.table(tabla).select("id").eq(clave, valor).execute()
        datos = como_filas(respuesta.data)
        if not datos:
            articulo = "el carro" if tabla == "carros" else "la zona"
            raise LookupError(f"{articulo} {valor!r} no existe en la base")
        return int(datos[0]["id"])
