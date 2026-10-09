"""Puerto de salida: exportar la planeación al Excel que consume facturación."""

from pathlib import Path
from typing import Protocol

from planeacion.application.dto.planeacion import PlaneacionCompleta
from planeacion.domain.modelo import Parametros


class ExportadorPlaneacion(Protocol):
    def exportar(
        self,
        planeacion: PlaneacionCompleta,
        ruta_salida: Path,
        parametros: Parametros | None = None,
    ) -> Path:
        """Escribe el .xlsx con las hojas ECOM, PLANEACION, BASE y PEDIDOS.
        Devuelve la ruta del archivo generado.

        ``parametros`` son los umbrales vigentes de las alertas; sin ellos se usan
        los defaults del dominio, que es lo correcto en una base sin migrar."""
        ...
