"""Puerto de entrada: generar el pivote por zona desde el ECOM crudo."""

from datetime import date
from pathlib import Path
from typing import Protocol

from planeacion.application.dto.pivote import PivotePorZonaDTO


class GenerarPivotePorZona(Protocol):
    def ejecutar(self, ruta_ecom: Path, fecha: date | None = None) -> PivotePorZonaDTO:
        """Pivotea el ECOM por zona. Sin ``fecha`` usa la fecha válida más frecuente del archivo."""
        ...
