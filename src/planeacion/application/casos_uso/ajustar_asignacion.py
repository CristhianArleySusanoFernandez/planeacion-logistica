"""Caso de uso: el override manual de Rudy (mover una zona a otro carro)."""

from planeacion.domain.modelo import ResultadoBalanceo
from planeacion.domain.servicios.balanceador import AjustadorDeAsignacion


class CasoDeUsoAjustarAsignacion:
    """Implementación del puerto de entrada ``AjustarAsignacion``."""

    def __init__(self) -> None:
        self._ajustador = AjustadorDeAsignacion()

    def ejecutar(
        self, resultado: ResultadoBalanceo, nombre_zona: str, numero_carro: str
    ) -> ResultadoBalanceo:
        return self._ajustador.mover(resultado, nombre_zona, numero_carro)
