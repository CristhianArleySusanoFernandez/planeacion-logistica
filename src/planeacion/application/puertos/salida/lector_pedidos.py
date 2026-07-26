"""Puerto de salida: lector del archivo crudo de pedidos (ECOM)."""

from pathlib import Path
from typing import Protocol

from planeacion.domain.modelo import LineaPedido


class LectorDePedidos(Protocol):
    def leer(self, ruta: Path) -> list[LineaPedido]:
        """Lee todas las líneas de producto del archivo crudo (una por fila)."""
        ...
