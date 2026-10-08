"""Adaptador Supabase del RepositorioCarroZonas (el repertorio de zonas por carro).

El repertorio tiene tres dimensiones desde la migración 003: carro, zona y día
de la semana. Una zona-día con un solo carro habilitado queda fijada; con varios,
el balanceador elige entre ellos.
"""

from collections.abc import Sequence
from typing import Any

from postgrest.exceptions import APIError
from postgrest.types import CountMethod
from supabase import Client

from planeacion.application.puertos.salida.repositorios import ParRepertorio
from planeacion.infraestructura.adaptadores.salida.supabase._filas import como_filas

TABLA = "carro_zonas"
_COLUMNAS = "dia_semana, frecuencia, carros(numero), zonas(nombre)"
# PostgREST corta toda respuesta en `max-rows` (1000 en Supabase) sin avisar y sin
# importar el `.limit()` que se le pida: pedir 100.000 filas devuelve 1000 y se
# pierden las demás en silencio. Por eso se pagina con `.range()`, igual que el
# repositorio de clientes. Con seis días × ~180 zonas × varios carros la tabla
# pasa las 1000 filas fácil, y un repertorio truncado deja zonas sin carro elegible
# que el balanceador reporta como huérfanas sin que lo sean.
_TAMANO_PAGINA = 1000
_TAMANO_LOTE = 500  # filas por upsert, como en el repositorio de clientes
# La tabla puede no existir aún: 42P01 es el undefined_table de Postgres y
# PGRST205 el "not in the schema cache" con que PostgREST reporta lo mismo.
_TABLA_INEXISTENTE = ("42P01", "PGRST205")
# 42703 es undefined_column: la migración 003 todavía sin aplicar sobre la 002.
_COLUMNA_INEXISTENTE = "42703"


class RepositorioCarroZonasSupabase:
    def __init__(self, cliente: Client) -> None:
        self._cliente = cliente

    def obtener_por_dia(self, dia_semana: str) -> dict[str, set[str]]:
        repertorio: dict[str, set[str]] = {}
        for fila in self._filas(dia_semana):
            repertorio.setdefault(fila["carros"]["numero"], set()).add(fila["zonas"]["nombre"])
        return repertorio

    def obtener_matriz(self) -> dict[str, dict[str, set[str]]]:
        matriz: dict[str, dict[str, set[str]]] = {}
        for fila in self._filas():
            por_carro = matriz.setdefault(fila["dia_semana"], {})
            por_carro.setdefault(fila["carros"]["numero"], set()).add(fila["zonas"]["nombre"])
        return matriz

    def frecuencias(self) -> dict[ParRepertorio, int]:
        return {
            ParRepertorio(fila["carros"]["numero"], fila["zonas"]["nombre"], str(fila["dia_semana"])): int(
                fila["frecuencia"] or 0
            )
            for fila in self._filas()
        }

    def _filas(self, dia_semana: str | None = None) -> list[dict[str, Any]]:
        """Las filas del repertorio, opcionalmente de un solo día.

        Pagina hasta agotar la tabla (ver ``_TAMANO_PAGINA``): una lectura corta
        no da error, devuelve menos repertorio del que hay.

        Con la migración sin aplicar devuelve vacío en vez de reventar: equivale a
        un repertorio sin configurar, y así el balanceo diario no depende del orden
        del despliegue (es la misma tolerancia que ya tenía la 002).
        """
        filas: list[dict[str, Any]] = []
        inicio = 0
        while True:
            consulta = self._cliente.table(TABLA).select(_COLUMNAS).order("id")
            if dia_semana is not None:
                consulta = consulta.eq("dia_semana", dia_semana)
            try:
                respuesta = consulta.range(inicio, inicio + _TAMANO_PAGINA - 1).execute()
            except APIError as error:
                if error.code in _TABLA_INEXISTENTE or error.code == _COLUMNA_INEXISTENTE:
                    return []
                raise
            pagina = como_filas(respuesta.data)
            filas.extend(pagina)
            if len(pagina) < _TAMANO_PAGINA:
                return filas
            inicio += _TAMANO_PAGINA

    def asignar(self, numero_carro: str, nombre_zona: str, dia_semana: str) -> None:
        self.asignar_lote([ParRepertorio(numero_carro, nombre_zona, dia_semana)])

    def asignar_lote(self, pares: Sequence[ParRepertorio]) -> int:
        if not pares:
            return 0
        ids_carros = self._ids_por_clave("carros", "numero")
        ids_zonas = self._ids_por_clave("zonas", "nombre")
        filas: list[dict[str, Any]] = []
        for par in pares:
            if par.numero_carro not in ids_carros:
                raise LookupError(f"el carro {par.numero_carro!r} no existe en la base")
            if par.nombre_zona not in ids_zonas:
                raise LookupError(f"la zona {par.nombre_zona!r} no existe en la base")
            filas.append(
                {
                    "carro_id": ids_carros[par.numero_carro],
                    "zona_id": ids_zonas[par.nombre_zona],
                    "dia_semana": par.dia_semana,
                    "frecuencia": par.frecuencia,
                }
            )
        # Sin ignore_duplicates: re-sembrar tiene que poder ACTUALIZAR la frecuencia
        # de un par que ya estaba, no dejarla como la dejó la corrida anterior.
        # En lotes porque la siembra manda miles de filas de una: son ~80 pares por
        # archivo × seis días × decenas de archivos.
        for inicio in range(0, len(filas), _TAMANO_LOTE):
            self._cliente.table(TABLA).upsert(
                filas[inicio : inicio + _TAMANO_LOTE], on_conflict="carro_id,zona_id,dia_semana"
            ).execute()
        return len(filas)

    def vaciar(self) -> int:
        """Borra el repertorio completo (ver el puerto) y devuelve cuántos borró.

        El filtro `id >= 0` está porque PostgREST no acepta un delete sin `where`:
        es su red de seguridad contra un borrado accidental de toda la tabla, y acá
        el borrado de toda la tabla es justo lo que se quiere.
        """
        respuesta = self._cliente.table(TABLA).select("id", count=CountMethod.exact, head=True).execute()
        borrados = respuesta.count or 0
        if borrados:
            self._cliente.table(TABLA).delete().gte("id", 0).execute()
        return borrados

    def quitar_sin_observaciones(self) -> int:
        """Borra los pares con frecuencia 0 (ver el puerto) y devuelve cuántos borró.

        Se cuenta antes de borrar porque el delete de PostgREST no devuelve las
        filas afectadas salvo que se le pidan, y pedirlas traería miles de vuelta.
        """
        respuesta = (
            self._cliente.table(TABLA)
            .select("id", count=CountMethod.exact, head=True)
            .eq("frecuencia", 0)
            .execute()
        )
        borrados = respuesta.count or 0
        if borrados:
            self._cliente.table(TABLA).delete().eq("frecuencia", 0).execute()
        return borrados

    def quitar(self, numero_carro: str, nombre_zona: str, dia_semana: str) -> None:
        carro_id = self._id_de("carros", "numero", numero_carro)
        zona_id = self._id_de("zonas", "nombre", nombre_zona)
        (
            self._cliente.table(TABLA)
            .delete()
            .eq("carro_id", carro_id)
            .eq("zona_id", zona_id)
            .eq("dia_semana", dia_semana)
            .execute()
        )

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
