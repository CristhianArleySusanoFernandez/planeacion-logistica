"""Puerto de entrada: generar el pivote por zona desde el ECOM crudo."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from planeacion.application.dto.pivote import PivotePorZonaDTO
from planeacion.domain.servicios.guarda_kilos import KILOS_MAX_POR_UNIDAD


class GenerarPivotePorZona(Protocol):
    def ejecutar(
        self,
        ruta_ecom: Path,
        fecha: date | None = None,
        todas_las_fechas: bool = False,
        kilos_max_por_unidad: Decimal = KILOS_MAX_POR_UNIDAD,
    ) -> PivotePorZonaDTO:
        """Pivotea el ECOM por zona. Sin ``fecha`` usa la fecha válida más frecuente del archivo.

        ``todas_las_fechas`` desactiva el filtro por día y toma el archivo entero:
        sirve para orígenes que ya vienen filtrados y que pueden cubrir dos
        jornadas planeadas juntas. ``kilos_max_por_unidad`` es el techo de la
        guarda de kilos (ver ``domain/servicios/guarda_kilos.py``).
        """
        ...
