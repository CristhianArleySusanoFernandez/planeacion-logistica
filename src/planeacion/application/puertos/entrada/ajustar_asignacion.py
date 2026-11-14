"""Puerto de entrada: el override manual de Rudy sobre un balanceo ya calculado."""

from typing import Protocol

from planeacion.domain.modelo import ResultadoBalanceo
from planeacion.domain.modelo.balanceo import OBSERVACIONES_PARA_FIJAR


class AjustarAsignacion(Protocol):
    def ejecutar(
        self,
        resultado: ResultadoBalanceo,
        nombre_zona: str,
        numero_carro: str,
        observaciones_para_fijar: int = OBSERVACIONES_PARA_FIJAR,
    ) -> ResultadoBalanceo:
        """Mueve la zona al carro destino (mismo municipio, sin violar reglas duras)
        y devuelve el resultado con las métricas recalculadas. ``observaciones_para_fijar``
        es el parámetro del candado: por debajo, una ruta única no prohíbe las demás."""
        ...
