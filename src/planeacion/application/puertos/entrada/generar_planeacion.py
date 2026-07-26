"""Puerto de entrada: generar (y opcionalmente guardar) la planeación del día."""

from datetime import date
from pathlib import Path
from typing import Protocol

from planeacion.application.dto.planeacion import PlaneacionCompleta
from planeacion.domain.modelo import ReglasBalanceo
from planeacion.domain.modelo.balanceo import REGLAS_POR_DEFECTO


class GenerarPlaneacion(Protocol):
    def ejecutar(
        self,
        ruta_ecom: Path,
        fecha: date | None = None,
        reglas: ReglasBalanceo = REGLAS_POR_DEFECTO,
    ) -> PlaneacionCompleta:
        """Pivote + carros por municipio + warm-start + balanceo. NO persiste."""
        ...

    def guardar(self, planeacion: PlaneacionCompleta) -> int:
        """Persiste la planeación cuando Rudy la confirma. Devuelve el id."""
        ...
