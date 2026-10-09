"""Agrupa las cargas de las rutas que lleva un mismo conductor.

Por qué existe: el balanceador reparte por RUTA, que es la unidad real de
reparto, pero quien maneja ve su día completo. Un conductor con dos rutas
(``FABIAN 1`` y ``FABIAN 2``) puede tener las dos parejas entre sí y aun así
cargar el doble que el resto; eso no se ve en la tabla por ruta.

Función pura y sin estado: solo suma. No decide nada y no toca el reparto —
alimenta el resumen del Paso 3.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from planeacion.domain.modelo import CargaCarro
from planeacion.domain.modelo.carro import clave_conductor, clave_orden_carro


@dataclass(frozen=True)
class CargaConductor:
    """Lo que lleva un conductor en el día, sumando todas sus rutas."""

    conductor: str
    rutas: tuple[str, ...]
    facturas: int
    clientes: int
    pesos: Decimal
    kilos: Decimal
    # Los municipios de sus rutas: hoy un conductor reparte en uno solo, pero las
    # alertas se aplican por municipio y el dato no se puede perder en la suma.
    municipios: tuple[str, ...] = ()


_SIN_CONDUCTOR = "sin conductor"


def agrupar_por_conductor(cargas: Sequence[CargaCarro]) -> list[CargaConductor]:
    """Las cargas sumadas por conductor, ordenadas por su primera ruta.

    La clave es ``carro.conductor_clave`` y, si está vacía, se deriva del nombre
    completo: así la agrupación funciona igual sobre una base recién migrada que
    todavía no tiene la columna poblada. Las rutas sin conductor se agrupan
    aparte en vez de desaparecer del resumen.
    """
    por_conductor: dict[str, list[CargaCarro]] = {}
    for carga in cargas:
        clave = carga.carro.conductor_clave or clave_conductor(carga.carro.conductor) or _SIN_CONDUCTOR
        por_conductor.setdefault(clave, []).append(carga)

    agrupadas = [
        CargaConductor(
            conductor=clave,
            rutas=tuple(sorted((c.carro.numero for c in grupo), key=clave_orden_carro)),
            facturas=sum(c.facturas for c in grupo),
            clientes=sum(c.clientes for c in grupo),
            pesos=sum((c.pesos for c in grupo), Decimal("0")),
            kilos=sum((c.kilos for c in grupo), Decimal("0")),
            municipios=tuple(
                sorted({c.carro.municipio.nombre for c in grupo if c.carro.municipio is not None})
            ),
        )
        for clave, grupo in por_conductor.items()
    ]
    return sorted(agrupadas, key=lambda c: clave_orden_carro(c.rutas[0]) if c.rutas else (1, 0, c.conductor))
