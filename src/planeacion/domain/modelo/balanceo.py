"""Modelo del balanceo: cargas por carro y métricas de desbalance por municipio."""

from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

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


# Frecuencias: (número de carro, nombre de zona) → cuántas veces se observó ese
# par en el histórico DEL DÍA que se está planeando. El día ya viene resuelto de
# afuera, igual que el repertorio: acá adentro es un mapa plano.
Frecuencias = Mapping[tuple[str, str], int]


def penalizaciones_por_frecuencia(
    repertorio: Repertorio, frecuencias: Frecuencias
) -> dict[tuple[str, str], float]:
    """Cuánto "cuesta" la costumbre: 0 para el carro dominante de cada zona y hasta
    casi 1 para el más minoritario, según ``1 - f / F``.

    ``F`` es la frecuencia máxima entre los carros ELEGIBLES de esa zona, así que
    la penalización es relativa a la zona y no a la escala global. Dos casos se
    tratan como neutros (penalización 0), a propósito:

    - ``f == 0``: par configurado a mano, sin evidencia histórica. No es un mal
      par, es uno del que no se sabe nada; penalizarlo sería peor que tratar a un
      par visto una sola vez.
    - ``F == 0``: ninguna de las opciones de esa zona se observó nunca. Sin
      evidencia no hay preferencia y manda el balance, como antes.
    """
    if not repertorio or not frecuencias:
        return {}
    carros_por_zona: dict[str, list[str]] = {}
    for numero_carro, zonas in repertorio.items():
        for nombre_zona in zonas:
            carros_por_zona.setdefault(nombre_zona, []).append(numero_carro)

    penalizaciones: dict[tuple[str, str], float] = {}
    for nombre_zona, carros in carros_por_zona.items():
        dominante = max(frecuencias.get((numero, nombre_zona), 0) for numero in carros)
        if dominante == 0:
            continue
        for numero in carros:
            observado = frecuencias.get((numero, nombre_zona), 0)
            if observado == 0:
                continue
            penalizaciones[(numero, nombre_zona)] = 1.0 - observado / dominante
    return penalizaciones


@dataclass(frozen=True)
class ReglasBalanceo:
    """Pesos de la función de costo y tope de iteraciones de la heurística."""

    w_clientes: float = 0.5
    w_pesos: float = 0.5
    # Peso de la costumbre: cuánto pesa, frente al balance, que una zona caiga en
    # el carro que históricamente la atiende. Deliberadamente bajo — rompe empates
    # y sesga decisiones marginales, no debe sobrecargar un carro por costumbre.
    # Con 0 el balanceo se comporta exactamente como antes de existir este término.
    # 0,30 salió de medir julio 2026 contra el reparto manual: 93,4 % → 95,2 % de
    # coincidencia sin mover los CV de ningún municipio (ver docs/dominio.md § 10).
    w_frecuencia: float = 0.30
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


class NivelDesbalance(Enum):
    """Qué tan bien quedó repartido un municipio, según el peor de sus dos CV."""

    ACEPTABLE = "aceptable"
    ATENCION = "atencion"
    CRITICO = "critico"


# Criterio de negocio: hasta 10 % de coeficiente de variación el reparto se
# considera parejo, entre 10 % y 20 % conviene revisarlo y por encima de 20 %
# hay carros claramente desiguales. Vive acá, y no en cada adaptador, para que
# la CLI y la UI no puedan juzgar distinto la misma planeación.
UMBRAL_CV_ACEPTABLE = 0.10
UMBRAL_CV_ATENCION = 0.20


def clasificar_cv(cv: float) -> NivelDesbalance:
    """CV → nivel. Los bordes: 0,10 exacto ya es ATENCION y 0,20 exacto todavía lo es."""
    if cv < UMBRAL_CV_ACEPTABLE:
        return NivelDesbalance.ACEPTABLE
    if cv <= UMBRAL_CV_ATENCION:
        return NivelDesbalance.ATENCION
    return NivelDesbalance.CRITICO


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

    @property
    def nivel(self) -> NivelDesbalance:
        """El nivel del municipio lo marca su peor dimensión, clientes o pesos."""
        return clasificar_cv(max(self.cv_clientes, self.cv_pesos))


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
