"""Sugerencia de zona para un cliente nuevo (voto mayoritario de vecinos)."""

from dataclasses import dataclass
from enum import Enum

from planeacion.domain.modelo.zona import Zona


class ConfianzaSugerencia(Enum):
    """Qué tan fino fue el match de vecinos que respalda la sugerencia."""

    BARRIO = "barrio"  # vecinos con la misma (ciudad, barrio)
    CIUDAD = "ciudad"  # solo coincidió la ciudad (confianza menor)


@dataclass(frozen=True)
class SugerenciaDeZona:
    zona_sugerida: Zona
    vecinos_en_zona: int  # cuántos vecinos respaldan la zona sugerida
    total_vecinos: int  # cuántos vecinos se encontraron en total
    confianza: ConfianzaSugerencia
    alternativas: tuple[tuple[Zona, int], ...]  # siguientes opciones con su conteo
