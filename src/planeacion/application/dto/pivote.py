"""DTOs del pivote por zona: lo que consumen el CLI y la UI, sin objetos de dominio."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ZonaAgregadaDTO:
    municipio: str
    zona: str
    facturas: int
    clientes: int
    pesos: Decimal
    kilos: Decimal


@dataclass(frozen=True)
class FacturaDTO:
    """Una factura (pedido único) con sus líneas sumadas; alimenta la hoja PEDIDOS."""

    pedido: str
    codigo_cliente: str
    zona: str | None  # None = cliente sin zona resuelta
    total: Decimal
    kilos: Decimal
    fecha: date | None
    nombre_cliente: str | None
    ciudad: str | None
    barrio: str | None
    direccion: str | None
    asesor: str | None


@dataclass(frozen=True)
class ClienteNoResueltoDTO:
    codigo: str
    motivo: str  # valor de MotivoNoResuelto
    nombre: str | None
    documento: str | None
    direccion: str | None
    ciudad: str | None
    barrio: str | None


@dataclass(frozen=True)
class PivotePorZonaDTO:
    fecha: date  # la fecha pivoteada (la del día que se planea)
    zonas: tuple[ZonaAgregadaDTO, ...]  # ordenadas por municipio y zona
    total_facturas: int
    total_clientes: int
    total_pesos: Decimal
    total_kilos: Decimal
    no_resueltos: tuple[ClienteNoResueltoDTO, ...]
    facturas_no_resueltas: int
    pesos_no_resueltos: Decimal
    kilos_no_resueltos: Decimal
    pedidos_excluidos_por_fecha: int  # pedidos del archivo que no son de la fecha pivoteada
    fechas_excluidas: tuple[str, ...]  # qué fechas traían ("ilegible" si venía dañada)
    facturas: tuple[FacturaDTO, ...] = ()  # detalle por factura, por zona y cliente
