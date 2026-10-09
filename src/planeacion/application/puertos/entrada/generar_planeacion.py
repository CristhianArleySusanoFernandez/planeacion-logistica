"""Puerto de entrada: generar (y opcionalmente guardar) la planeación del día."""

from datetime import date
from pathlib import Path
from typing import Protocol

from planeacion.application.dto.planeacion import PlaneacionCompleta
from planeacion.domain.modelo import ReglasBalanceo


class GenerarPlaneacion(Protocol):
    def ejecutar(
        self,
        ruta_ecom: Path,
        fecha: date | None = None,
        reglas: ReglasBalanceo | None = None,
        usar_historico: bool = True,
        todas_las_fechas: bool = False,
    ) -> PlaneacionCompleta:
        """Pivote + carros por municipio + warm-start + balanceo. NO persiste.

        Sin ``reglas`` se usan los pesos de la tabla de parámetros (y, si no hay,
        los defaults del dominio); pasarlas explícitamente es para medir.
        Con ``usar_historico=False`` no consulta la planeación previa y reparte
        desde cero; ``todas_las_fechas`` se pasa tal cual al pivote.
        """
        ...

    def guardar(self, planeacion: PlaneacionCompleta) -> int:
        """Persiste la planeación cuando Rudy la confirma. Devuelve el id."""
        ...
