"""Sugerencia de zona para un cliente nuevo (voto mayoritario de vecinos)."""

from dataclasses import dataclass
from enum import Enum

from planeacion.domain.modelo.zona import Zona

# Cuántos vecinos de ejemplo se muestran por zona. Tres alcanzan para reconocer
# la calle; más es ruido en una pantalla donde hay que decidir rápido.
MAX_VECINOS_DE_EJEMPLO = 3


class ConfianzaSugerencia(Enum):
    """En qué escalón de respaldo se encontró a los vecinos.

    El nombre del nivel va en pantalla: no es lo mismo "14 de 18 vecinos del
    mismo barrio" que "14 de 180 de la misma ciudad", y quien decide tiene que
    poder distinguirlo de un vistazo.
    """

    BARRIO = "barrio"  # vecinos con la misma (ciudad, barrio)
    CIUDAD = "ciudad"  # solo coincidió la ciudad (confianza menor)

    @property
    def descripcion(self) -> str:
        if self is ConfianzaSugerencia.BARRIO:
            return "vecinos del mismo barrio"
        return "vecinos de la misma ciudad (el barrio no coincidió con ninguno)"


@dataclass(frozen=True)
class VecinoDeEjemplo:
    """Un cliente vecino, para reconocer la calle. Solo lectura."""

    codigo: str
    nombre: str | None
    direccion: str | None

    @property
    def etiqueta(self) -> str:
        return f"{self.nombre or self.codigo} — {self.direccion or 'sin dirección'}"


@dataclass(frozen=True)
class OpcionDeZona:
    """Una zona candidata con su respaldo: cuántos vecinos y quiénes."""

    zona: Zona
    vecinos: int
    total_vecinos: int  # el total del escalón, para poder calcular el porcentaje
    ejemplos: tuple[VecinoDeEjemplo, ...] = ()

    @property
    def porcentaje(self) -> float:
        """Qué parte de los vecinos encontrados está en esta zona."""
        if self.total_vecinos <= 0:
            return 0.0
        return self.vecinos / self.total_vecinos


@dataclass(frozen=True)
class SugerenciaDeZona:
    """Las mejores zonas para un cliente nuevo, con su respaldo.

    ``opciones`` viene ordenada de mejor a peor y la primera es la sugerida; se
    muestran todas (hasta tres) y no solo la ganadora porque el **margen** es
    parte de la decisión: "78 % contra 17 %" y "40 % contra 35 %" se resuelven
    distinto, y eso lo decide una persona, no el programa.
    """

    opciones: tuple[OpcionDeZona, ...]
    total_vecinos: int
    confianza: ConfianzaSugerencia

    @property
    def zona_sugerida(self) -> Zona:
        return self.opciones[0].zona

    @property
    def vecinos_en_zona(self) -> int:
        return self.opciones[0].vecinos
