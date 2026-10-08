"""Carro: una RUTA de reparto, con conductor, placa y auxiliar.

La unidad de reparto es la ruta, no el vehículo ni la persona: un mismo conductor
puede llevar dos rutas con el mismo camión y el mismo auxiliar (``FABIAN 1`` y
``FABIAN 2``). Por eso ``numero`` es la identidad y ``conductor_clave`` —el
nombre sin el sufijo— es lo que permite volver a juntar las dos rutas de alguien.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from planeacion.domain.modelo.municipio import Municipio
from planeacion.domain.modelo.zona import ReglaChiquinquira

_SUFIJO_DE_RUTA = re.compile(r"\s+\d+\s*$")


def clave_conductor(conductor: str | None) -> str | None:
    """``'FABIAN 2'`` → ``'FABIAN'``. Un nombre sin sufijo se devuelve igual.

    Solo se quita un número al final separado por espacio: así ``'CARLOS 1'`` se
    agrupa con ``'CARLOS 2'`` pero ``'JOSE JIMENEZ'`` queda intacto.
    """
    if conductor is None:
        return None
    return _SUFIJO_DE_RUTA.sub("", conductor.strip()) or None


def clave_orden_carro(numero: str) -> tuple[int, int, str]:
    """Orden natural de números de ruta: 1, 2, 3, 10, 11 (y no 1, 10, 11, 2, 3).

    ``numero`` es texto en la base, así que ordenar por él es ordenar
    alfabéticamente. Los que no son números van al final y entre ellos por texto,
    para que una fila escrita a mano no haga fallar el orden de toda la tabla.
    """
    try:
        return (0, int(numero), "")
    except ValueError:
        return (1, 0, numero)


@dataclass(frozen=True)
class Carro:
    numero: str
    conductor: str | None = None
    placa: str | None = None
    auxiliar: str | None = None
    municipio: Municipio | None = None
    es_externo: bool = False
    costo_diario: Decimal = Decimal("0")
    activo: bool = True
    # El nombre del conductor sin el sufijo de ruta: la clave para agrupar sus rutas.
    conductor_clave: str | None = None
    # Informativo: el destino real de las rutas viajeras (MUZO, FLORIAN, GARAGOA,
    # MIRAFLORES, VILLA DELEYVA), que en `municipio` caen todas en OTROS porque
    # ese es el pool con el que se balancean.
    municipio_real: str | None = None
    # Solo para las rutas de Chiquinquirá: de qué lado reparten. Es un dato de la
    # ruta y no una posición en el pool, porque el municipio tiene cuatro rutas
    # (1 y 2 al sur, 3 y 4 al norte) y la regla dura aplica al par, no a una.
    lado_chiquinquira: ReglaChiquinquira | None = None
