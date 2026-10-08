"""Zona: agrupación geográfica de clientes (RUTA en los datos viejos)."""

from dataclasses import dataclass
from enum import Enum

from planeacion.domain.modelo.municipio import Municipio


class ReglaChiquinquira(Enum):
    """De qué lado de Chiquinquirá es una zona (y, en la flota, una ruta).

    La regla dura: una zona del sur solo puede caer en una ruta del sur. Vale
    para el PAR de rutas de cada lado (hoy SUR → {1, 2} y NORTE → {3, 4}), no
    para una ruta concreta; entre las del lado correcto deciden el repertorio y
    el balance.
    """

    SUR = "SUR"
    NORTE = "NORTE"


@dataclass(frozen=True)
class Zona:
    nombre: str
    municipio: Municipio
    regla_chiquinquira: ReglaChiquinquira | None = None
    activa: bool = True
