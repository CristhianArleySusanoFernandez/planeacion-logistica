"""Modelo del balanceo: cargas por carro y métricas de desbalance por municipio."""

from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from decimal import Decimal

from planeacion.domain.errores import MovimientoInvalido
from planeacion.domain.modelo.carro import Carro
from planeacion.domain.modelo.pivote import ZonaAgregada
from planeacion.domain.modelo.zona import Zona

# Repertorio: número de carro → nombres de zona que ese carro puede atender.
# Vacío = base sin configurar: cualquier carro del municipio puede atender todo.
Repertorio = Mapping[str, Set[str]]


def zona_permitida(repertorio: Repertorio, nombre_zona: str, numero_carro: str) -> bool:
    """Con repertorio vacío todo está permitido (comportamiento clásico)."""
    if not repertorio:
        return True
    return nombre_zona in repertorio.get(numero_carro, frozenset())


@dataclass(frozen=True)
class ReglasBalanceo:
    """Pesos de la función de costo y tope de iteraciones de la heurística."""

    w_clientes: float = 0.5
    w_pesos: float = 0.5
    max_iteraciones: int = 500


REGLAS_POR_DEFECTO = ReglasBalanceo()


@dataclass(frozen=True)
class AsignacionZona:
    """Una fila del detalle de la planeación: qué zona quedó en qué carro."""

    zona: Zona
    carro: Carro
    facturas: int
    clientes: int
    pesos: Decimal
    kilos: Decimal


@dataclass
class CargaCarro:
    """Mutable a propósito: el balanceador y el ajuste manual mueven zonas."""

    carro: Carro
    zonas: list[ZonaAgregada] = field(default_factory=list)

    @property
    def facturas(self) -> int:
        return sum(zona.facturas for zona in self.zonas)

    @property
    def clientes(self) -> int:
        return sum(zona.clientes for zona in self.zonas)

    @property
    def pesos(self) -> Decimal:
        return sum((zona.pesos for zona in self.zonas), Decimal("0"))

    @property
    def kilos(self) -> Decimal:
        return sum((zona.kilos for zona in self.zonas), Decimal("0"))

    def agregar(self, zona: ZonaAgregada) -> None:
        self.zonas.append(zona)

    def quitar(self, nombre_zona: str) -> ZonaAgregada:
        for indice, zona in enumerate(self.zonas):
            if zona.zona.nombre == nombre_zona:
                return self.zonas.pop(indice)
        raise MovimientoInvalido(f"el carro {self.carro.numero} no tiene la zona {nombre_zona!r}")


@dataclass(frozen=True)
class MetricasDesbalance:
    """Qué tan parejos quedaron los carros de un municipio."""

    municipio: str
    rango_clientes: int  # max - min de clientes entre carros
    rango_pesos: Decimal
    cv_clientes: float  # coeficiente de variación (desv. estándar poblacional / media)
    cv_pesos: float

    def es_aceptable(self, umbral_cv: float) -> bool:
        return max(self.cv_clientes, self.cv_pesos) <= umbral_cv


@dataclass
class ResultadoBalanceo:
    """El reparto final más las métricas de antes y después de la mejora.

    Una zona está fijada (no se puede mover) cuando su ``regla_chiquinquira``
    no es None; no se duplica ese estado aquí. ``zonas_sin_carro`` son las que
    ningún carro activo tiene en su repertorio: quedan sin asignar para que
    Rudy las configure. ``repertorio`` viaja en el resultado para que el ajuste
    manual y la UI validen los movimientos sin volver a la base.
    """

    cargas_por_municipio: dict[str, list[CargaCarro]]
    metricas_iniciales: dict[str, MetricasDesbalance]
    metricas_finales: dict[str, MetricasDesbalance]
    desde_historico: bool
    zonas_sin_carro: list[ZonaAgregada] = field(default_factory=list)
    repertorio: dict[str, frozenset[str]] = field(default_factory=dict)

    def carro_permite(self, numero_carro: str, nombre_zona: str) -> bool:
        return zona_permitida(self.repertorio, nombre_zona, numero_carro)
