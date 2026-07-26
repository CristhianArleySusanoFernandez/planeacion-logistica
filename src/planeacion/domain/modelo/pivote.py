"""Resultados del pivote por zona: agregados y clientes sin zona resuelta."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from planeacion.domain.modelo.zona import Zona


class MotivoNoResuelto(Enum):
    """Por qué un cliente quedó sin zona en el pivote."""

    NO_ESTA_EN_MAESTRA = "NO_ESTA_EN_MAESTRA"  # el #N/D clásico: cliente nuevo
    EN_MAESTRA_SIN_ZONA = "EN_MAESTRA_SIN_ZONA"  # el "(en blanco)" del pivote viejo


@dataclass(frozen=True)
class ZonaAgregada:
    zona: Zona
    facturas: int  # pedidos distintos, no líneas
    clientes: int  # códigos de cliente distintos
    pesos: Decimal
    kilos: Decimal


@dataclass(frozen=True)
class FacturaAgrupada:
    """Una factura (pedido único) con sus líneas ya sumadas y la zona resuelta."""

    pedido: str
    codigo_cliente: str
    zona: Zona | None  # None = cliente sin zona (#N/D o en la maestra sin RUTA)
    total: Decimal  # suma de las líneas (col AE); reproduce el total de la factura
    kilos: Decimal
    fecha: date | None = None
    nombre_cliente: str | None = None
    ciudad: str | None = None
    barrio: str | None = None
    direccion: str | None = None
    asesor: str | None = None


@dataclass(frozen=True)
class ClienteNoResuelto:
    codigo: str
    motivo: MotivoNoResuelto
    nombre: str | None = None
    documento: str | None = None
    direccion: str | None = None
    ciudad: str | None = None
    barrio: str | None = None
