"""Errores propios del dominio. El dominio nunca lanza excepciones de librerías."""

from datetime import date


class ErrorDeDominio(Exception):
    """Base de todos los errores del dominio."""


class ZonaInvalida(ErrorDeDominio):
    """El nombre de zona está vacío o no se puede interpretar."""


class SinPedidosParaPivotear(ErrorDeDominio):
    """El archivo no trae pedidos (o ninguno con fecha válida) para pivotear."""


class SinPedidosEnLaFecha(SinPedidosParaPivotear):
    """El archivo trae pedidos, pero ninguno del día que se pidió.

    Es un caso distinto del archivo vacío —el archivo está bien, es de otro día—
    y por eso es su propio tipo: quien lo muestre no tiene que adivinarlo
    leyendo el texto del mensaje.
    """

    def __init__(self, mensaje: str, fecha: date | None = None) -> None:
        super().__init__(mensaje)
        self.fecha = fecha


class ZonaInexistente(ErrorDeDominio):
    """Se intentó asignar una zona que no existe en la base."""


class MovimientoInvalido(ErrorDeDominio):
    """Un movimiento de zona entre carros viola una regla (municipio distinto,
    regla dura de Chiquinquirá, zona o carro inexistentes)."""


class SinCarrosParaMunicipio(ErrorDeDominio):
    """Un municipio tiene zonas con carga pero ningún carro disponible en la flota."""
