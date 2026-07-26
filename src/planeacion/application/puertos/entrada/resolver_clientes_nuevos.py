"""Puerto de entrada: asistente de clientes nuevos (resolución de #N/D)."""

from collections.abc import Sequence
from typing import Protocol

from planeacion.application.dto.clientes_nuevos import ClientePendiente
from planeacion.application.dto.pivote import ClienteNoResueltoDTO


class ResolverClientesNuevos(Protocol):
    def pendientes(self, no_resueltos: Sequence[ClienteNoResueltoDTO]) -> list[ClientePendiente]:
        """Sugiere zona a cada no resuelto del pivote (voto de vecinos de la maestra)."""
        ...

    def confirmar_cliente(self, pendiente: ClientePendiente, zona_nombre: str) -> None:
        """Persiste la decisión de Rudy: agrega el cliente nuevo o le actualiza la zona."""
        ...
