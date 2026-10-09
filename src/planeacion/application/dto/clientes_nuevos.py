"""DTOs del asistente de clientes nuevos (lo que consumen el CLI y la UI)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class VecinoDTO:
    """Un vecino de ejemplo: sirve para reconocer la calle, no para decidir solo."""

    etiqueta: str  # "NOMBRE — DIRECCIÓN", ya armada por el dominio


@dataclass(frozen=True)
class OpcionDTO:
    """Una zona candidata con su respaldo, lista para mostrar."""

    zona: str
    municipio: str
    vecinos: int
    porcentaje: float  # sobre el total de vecinos del escalón
    ejemplos: tuple[VecinoDTO, ...]


@dataclass(frozen=True)
class SugerenciaDTO:
    """Las mejores zonas (hasta 3), ordenadas: la primera es la sugerida.

    Se muestran todas porque el margen es parte de la decisión: 78 % contra 17 %
    y 40 % contra 35 % se resuelven distinto.
    """

    opciones: tuple[OpcionDTO, ...]
    total_vecinos: int
    confianza: str  # valor de ConfianzaSugerencia: "barrio" | "ciudad"
    nivel: str  # el escalón en palabras, para la pantalla

    @property
    def zona(self) -> str:
        return self.opciones[0].zona

    @property
    def municipio(self) -> str:
        return self.opciones[0].municipio

    @property
    def vecinos_en_zona(self) -> int:
        return self.opciones[0].vecinos


@dataclass(frozen=True)
class ClientePendiente:
    codigo: str
    motivo: str  # valor de MotivoNoResuelto
    nombre: str | None
    documento: str | None
    direccion: str | None
    ciudad: str | None  # ya con la corrección de ubicación aplicada, si existía
    barrio: str | None
    sugerencia: SugerenciaDTO | None  # None = Rudy asigna a mano sin ayuda
