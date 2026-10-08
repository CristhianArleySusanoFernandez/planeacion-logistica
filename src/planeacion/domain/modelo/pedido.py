"""Línea de pedido: una fila del archivo ECOM crudo (un producto de una factura)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class LineaPedido:
    pedido: str
    codigo_cliente: str
    fecha: date | None  # None si el archivo la trae dañada (texto tipo '46190')
    total_linea: Decimal  # columna AE del ECOM
    kilos: Decimal  # columna AI del ECOM (viene en gramos; aquí ya convertida a kilos)
    nombre_cliente: str | None = None
    documento: str | None = None
    direccion: str | None = None
    ciudad: str | None = None
    barrio: str | None = None
    producto: str | None = None
    cod_producto: str | None = None  # columna Cod.Prod: la identidad del producto
    cantidad: Decimal | None = None
    asesor: str | None = None  # columna P, ej. "10947-MATILDA"
