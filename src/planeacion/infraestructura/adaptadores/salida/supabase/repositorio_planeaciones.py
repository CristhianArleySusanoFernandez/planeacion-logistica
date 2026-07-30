"""Adaptador Supabase del RepositorioPlaneaciones. Solo traducción de datos."""

from collections.abc import Sequence
from datetime import date
from typing import Any

from supabase import Client

from planeacion.application.dto.planeacion import AsignacionPrevia
from planeacion.domain.modelo import AsignacionZona
from planeacion.infraestructura.adaptadores.salida.supabase import (
    repositorio_carros,
    repositorio_zonas,
)
from planeacion.infraestructura.adaptadores.salida.supabase._filas import como_filas

TABLA = "planeaciones"
TABLA_ASIGNACIONES = "planeacion_asignaciones"


def a_fila_asignacion(
    asignacion: AsignacionZona,
    planeacion_id: int,
    ids_zonas: dict[str, int],
    ids_carros: dict[str, int],
) -> dict[str, Any]:
    return {
        "planeacion_id": planeacion_id,
        "zona_id": ids_zonas[asignacion.zona.nombre],
        "carro_id": ids_carros.get(asignacion.carro.numero),
        "num_facturas": asignacion.facturas,
        "clientes_unicos": asignacion.clientes,
        # str porque Decimal no es serializable a JSON; Postgres lo castea a numeric.
        "total_pesos": str(asignacion.pesos),
        "total_kilos": str(asignacion.kilos),
    }


class RepositorioPlaneacionesSupabase:
    def __init__(self, cliente: Client) -> None:
        self._cliente = cliente

    def guardar_planeacion(self, fecha: date, dia_semana: str, asignaciones: Sequence[AsignacionZona]) -> int:
        cabecera = (
            self._cliente.table(TABLA)
            .insert({"fecha": fecha.isoformat(), "dia_semana": dia_semana})
            .execute()
        )
        planeacion_id = int(como_filas(cabecera.data)[0]["id"])

        ids_zonas = self._ids(repositorio_zonas.TABLA, "nombre")
        ids_carros = self._ids(repositorio_carros.TABLA, "numero")
        filas = [a_fila_asignacion(a, planeacion_id, ids_zonas, ids_carros) for a in asignaciones]
        if filas:
            self._cliente.table(TABLA_ASIGNACIONES).insert(filas).execute()
        return planeacion_id

    def obtener_asignacion_previa(self, dia_semana: str) -> AsignacionPrevia | None:
        cabeceras = (
            self._cliente.table(TABLA)
            .select("id, fecha")
            .eq("dia_semana", dia_semana)
            .order("fecha", desc=True)
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        filas_cabecera = como_filas(cabeceras.data)
        if not filas_cabecera:
            return None

        detalle = (
            self._cliente.table(TABLA_ASIGNACIONES)
            .select("zonas(nombre), carros(numero)")
            .eq("planeacion_id", filas_cabecera[0]["id"])
            .execute()
        )
        mapeo: dict[str, str] = {}
        for fila in como_filas(detalle.data):
            zona, carro = fila.get("zonas"), fila.get("carros")
            if zona and carro:  # carro_id es nullable: una zona sin asignar no aporta warm-start
                mapeo[zona["nombre"]] = carro["numero"]
        if not mapeo:
            return None
        return AsignacionPrevia(fecha=date.fromisoformat(filas_cabecera[0]["fecha"]), zona_a_carro=mapeo)

    def _ids(self, tabla: str, clave: str) -> dict[str, int]:
        respuesta = self._cliente.table(tabla).select(f"id, {clave}").limit(10000).execute()
        return {fila[clave]: int(fila["id"]) for fila in como_filas(respuesta.data)}
