"""Puerto de entrada: generar el pivote por zona desde el ECOM crudo."""

from datetime import date
from pathlib import Path
from typing import Protocol

from planeacion.application.dto.pivote import PivotePorZonaDTO


class GenerarPivotePorZona(Protocol):
    def ejecutar(
        self, ruta_ecom: Path, fecha: date | None = None, todas_las_fechas: bool = False
    ) -> PivotePorZonaDTO:
        """Pivotea el ECOM por zona. Sin ``fecha`` usa la fecha válida más frecuente del archivo.

        ``todas_las_fechas`` desactiva el filtro por día y toma el archivo entero:
        sirve para orígenes que ya vienen filtrados y que pueden cubrir dos
        jornadas planeadas juntas.
        """
        ...
