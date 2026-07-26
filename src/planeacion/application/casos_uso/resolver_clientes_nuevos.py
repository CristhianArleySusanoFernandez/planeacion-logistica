"""Caso de uso: asistente de clientes nuevos (la máquina propone, Rudy decide).

Para cada cliente no resuelto del pivote sugiere la zona más probable con el
voto de vecinos de la maestra. Antes de sugerir aplica la corrección de
ubicación (hoja CAMBIOS) si el cliente la tiene: ECOM a veces trae la ciudad o
el barrio mal. Nada se persiste hasta que Rudy confirma con ``confirmar_cliente``.
"""

from collections.abc import Sequence

from planeacion.application.dto.clientes_nuevos import ClientePendiente, SugerenciaDTO
from planeacion.application.dto.pivote import ClienteNoResueltoDTO
from planeacion.application.puertos.salida.repositorios import (
    RepositorioClientes,
    RepositorioCorrecciones,
    RepositorioZonas,
)
from planeacion.domain.errores import ZonaInexistente
from planeacion.domain.modelo import Cliente, MotivoNoResuelto, SugerenciaDeZona
from planeacion.domain.servicios.normalizacion_ubicacion import normalizar_ubicacion
from planeacion.domain.servicios.parseo_zonas import normalizar_nombre_zona
from planeacion.domain.servicios.sugeridor_zona import SugeridorDeZona


class CasoDeUsoResolverClientesNuevos:
    """Implementación del puerto de entrada ``ResolverClientesNuevos``."""

    def __init__(
        self,
        clientes: RepositorioClientes,
        zonas: RepositorioZonas,
        correcciones: RepositorioCorrecciones,
    ) -> None:
        self._clientes = clientes
        self._zonas = zonas
        self._correcciones = correcciones

    def pendientes(self, no_resueltos: Sequence[ClienteNoResueltoDTO]) -> list[ClientePendiente]:
        if not no_resueltos:
            return []
        sugeridor = SugeridorDeZona(self._clientes.listar())
        correcciones = {c.cliente_codigo: c for c in self._correcciones.listar()}

        pendientes: list[ClientePendiente] = []
        for cliente in no_resueltos:
            ciudad, barrio = cliente.ciudad, cliente.barrio
            correccion = correcciones.get(cliente.codigo)
            if correccion is not None:
                ciudad = correccion.ciudad_real or ciudad
                barrio = correccion.barrio_real or barrio
            sugerencia = sugeridor.sugerir(ciudad, barrio)
            pendientes.append(
                ClientePendiente(
                    codigo=cliente.codigo,
                    motivo=cliente.motivo,
                    nombre=cliente.nombre,
                    documento=cliente.documento,
                    direccion=cliente.direccion,
                    ciudad=ciudad,
                    barrio=barrio,
                    sugerencia=_a_sugerencia_dto(sugerencia),
                )
            )
        return pendientes

    def confirmar_cliente(self, pendiente: ClientePendiente, zona_nombre: str) -> None:
        zona = self._zonas.obtener_por_nombre(normalizar_nombre_zona(zona_nombre))
        if zona is None:
            raise ZonaInexistente(f"la zona {zona_nombre!r} no existe en la base")

        if pendiente.motivo == MotivoNoResuelto.EN_MAESTRA_SIN_ZONA.value:
            self._clientes.actualizar_zona(pendiente.codigo, zona.nombre)
            return

        # Cliente nuevo: se agrega completo a la maestra para que no vuelva a salir
        # como #N/D. Ciudad y barrio se guardan normalizados (sin prefijo DANE ni
        # acentos), que es el formato de la maestra y del voto de vecinos.
        self._clientes.guardar_cliente(
            Cliente(
                codigo=pendiente.codigo,
                direccion=pendiente.direccion,
                barrio=normalizar_ubicacion(pendiente.barrio) or None,
                ciudad=normalizar_ubicacion(pendiente.ciudad) or None,
                zona=zona,
                documento=pendiente.documento,
                razon_social=pendiente.nombre,
            )
        )


def _a_sugerencia_dto(sugerencia: SugerenciaDeZona | None) -> SugerenciaDTO | None:
    if sugerencia is None:
        return None
    return SugerenciaDTO(
        zona=sugerencia.zona_sugerida.nombre,
        municipio=sugerencia.zona_sugerida.municipio.nombre,
        vecinos_en_zona=sugerencia.vecinos_en_zona,
        total_vecinos=sugerencia.total_vecinos,
        confianza=sugerencia.confianza.value,
        alternativas=tuple((zona.nombre, votos) for zona, votos in sugerencia.alternativas),
    )
