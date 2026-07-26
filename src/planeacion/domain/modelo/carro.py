"""Carro: vehículo fijo de reparto, con conductor, placa y auxiliar."""

from dataclasses import dataclass
from decimal import Decimal

from planeacion.domain.modelo.municipio import Municipio


@dataclass(frozen=True)
class Carro:
    numero: str
    conductor: str | None = None
    placa: str | None = None
    auxiliar: str | None = None
    municipio: Municipio | None = None
    es_externo: bool = False
    costo_diario: Decimal = Decimal("0")
    activo: bool = True
