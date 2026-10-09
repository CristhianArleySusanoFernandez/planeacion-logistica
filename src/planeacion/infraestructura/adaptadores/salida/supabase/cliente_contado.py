"""Envoltorio del cliente de Supabase que cuenta los viajes a la base.

Para poder decir "esta etapa hace 10 consultas" y no estimarlo. Cuenta las
llamadas a ``table(...)``, que es donde arranca cada petición de PostgREST: un
``listar()`` paginado llama una vez por página, así que el número es el de viajes
reales y no el de métodos del repositorio.

Solo se usa al medir (``planeacion-medir``); la app crea su cliente normal.
"""

from collections import Counter
from typing import Any

from supabase import Client


class ClienteContado:
    """Pasa todo al cliente real y lleva la cuenta por tabla.

    No hereda de ``Client`` a propósito: delega por ``__getattr__`` para no
    quedar atado a su superficie, que es grande y cambia entre versiones.
    """

    def __init__(self, cliente: Client) -> None:
        self._cliente = cliente
        self.consultas: Counter[str] = Counter()

    def table(self, nombre: str) -> Any:
        self.consultas[nombre] += 1
        return self._cliente.table(nombre)

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._cliente, nombre)

    @property
    def total(self) -> int:
        return sum(self.consultas.values())

    def desde(self, marca: Counter[str]) -> Counter[str]:
        """Las consultas hechas desde una foto anterior del contador."""
        return Counter({tabla: veces - marca.get(tabla, 0) for tabla, veces in self.consultas.items()})

    def foto(self) -> Counter[str]:
        return Counter(self.consultas)
