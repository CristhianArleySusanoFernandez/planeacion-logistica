"""Resuelve la zona de un cliente: override ("martha ojo") → maestra → no resuelto."""

from collections.abc import Mapping

from planeacion.domain.modelo import Zona
from planeacion.domain.modelo.pivote import MotivoNoResuelto


class ResolutorDeZona:
    """Servicio puro: se construye con los mapas que el caso de uso ya cargó.

    ``zonas_maestra`` mapea código → zona según la maestra (``None`` cuando el
    cliente está en la maestra pero sin RUTA). ``zonas_override`` fuerza la zona
    de clientes puntuales por encima de la maestra.
    """

    def __init__(
        self,
        zonas_maestra: Mapping[str, Zona | None],
        zonas_override: Mapping[str, Zona],
    ) -> None:
        self._maestra = zonas_maestra
        self._override = zonas_override

    def resolver(self, codigo: str) -> Zona | None:
        zona = self._override.get(codigo)
        if zona is not None:
            return zona
        return self._maestra.get(codigo)

    def motivo_no_resuelto(self, codigo: str) -> MotivoNoResuelto:
        if codigo in self._maestra:
            return MotivoNoResuelto.EN_MAESTRA_SIN_ZONA
        return MotivoNoResuelto.NO_ESTA_EN_MAESTRA
