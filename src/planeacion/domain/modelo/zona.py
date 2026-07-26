"""Zona: agrupación geográfica de clientes (RUTA en los datos viejos)."""

from dataclasses import dataclass
from enum import Enum

from planeacion.domain.modelo.municipio import Municipio


class ReglaChiquinquira(Enum):
    """Regla dura de Chiquinquirá: SUR → carro 1, NORTE → carro 2."""

    SUR = "SUR"
    NORTE = "NORTE"


@dataclass(frozen=True)
class Zona:
    nombre: str
    municipio: Municipio
    regla_chiquinquira: ReglaChiquinquira | None = None
    activa: bool = True
