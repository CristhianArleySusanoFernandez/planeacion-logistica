"""DTO de la planeación completa de un día.

``resultado`` es el objeto de dominio vivo (no una copia plana): el modo
interactivo del CLI y la UI necesitan mover zonas y recalcular métricas sobre
él antes de decidir si se guarda.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from planeacion.application.dto.pivote import (
    ClienteNoResueltoDTO,
    FacturaDTO,
    LineaKilosExcluidosDTO,
)
from planeacion.domain.modelo import AsignacionZona, ResultadoBalanceo


@dataclass(frozen=True)
class AsignacionPrevia:
    """Lo que devuelve el histórico para el warm-start: de qué fecha viene y el reparto."""

    fecha: date
    zona_a_carro: dict[str, str]  # nombre de zona → numero de carro


@dataclass(frozen=True)
class PlaneacionCompleta:
    fecha: date
    dia_semana: str  # "lunes"..."domingo" (minúsculas, sin tildes)
    resultado: ResultadoBalanceo
    total_facturas: int
    total_clientes: int
    total_pesos: Decimal
    total_kilos: Decimal
    no_resueltos: tuple[ClienteNoResueltoDTO, ...]
    pedidos_excluidos_por_fecha: int
    facturas: tuple[FacturaDTO, ...] = ()  # detalle por factura (hojas ECOM y PEDIDOS)
    fecha_previa: date | None = None  # de qué fecha vino el warm-start (None = round-robin)
    # Agregados de los clientes sin zona, tal como los calculó el dominio; son la
    # fila "#N/D" que cierra el pivote exportado. Los clientes distintos no van
    # aquí: son len(no_resueltos).
    facturas_no_resueltas: int = 0
    pesos_no_resueltos: Decimal = Decimal("0")
    kilos_no_resueltos: Decimal = Decimal("0")
    # Kilos que ECOM traia mal cargados y no entraron al reparto (ver guarda_kilos).
    kilos_excluidos: Decimal = Decimal("0")
    lineas_kilos_excluidos: tuple[LineaKilosExcluidosDTO, ...] = ()

    def asignaciones(self) -> list[AsignacionZona]:
        """El reparto aplanado a filas zona→carro, como lo esperan la persistencia
        y la comparación contra planeaciones manuales."""
        return [
            AsignacionZona(
                zona=zona.zona,
                carro=carga.carro,
                facturas=zona.facturas,
                clientes=zona.clientes,
                pesos=zona.pesos,
                kilos=zona.kilos,
            )
            for cargas in self.resultado.cargas_por_municipio.values()
            for carga in cargas
            for zona in carga.zonas
        ]
