"""Puerto de salida: exportar la planeación al Excel que consume facturación."""

from pathlib import Path
from typing import Protocol

from planeacion.application.dto.planeacion import PlaneacionCompleta


class ExportadorPlaneacion(Protocol):
    def exportar(self, planeacion: PlaneacionCompleta, ruta_salida: Path) -> Path:
        """Escribe el .xlsx con las hojas ECOM, PLANEACION, BASE y PEDIDOS.
        Devuelve la ruta del archivo generado."""
        ...
