"""Puerto de entrada: el override manual de Rudy sobre un balanceo ya calculado."""

from typing import Protocol

from planeacion.domain.modelo import ResultadoBalanceo


class AjustarAsignacion(Protocol):
    def ejecutar(
        self, resultado: ResultadoBalanceo, nombre_zona: str, numero_carro: str
    ) -> ResultadoBalanceo:
        """Mueve la zona al carro destino (mismo municipio, sin violar reglas duras)
        y devuelve el resultado con las métricas recalculadas."""
        ...
