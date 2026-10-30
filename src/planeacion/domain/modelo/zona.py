"""Zona: agrupación geográfica de clientes (RUTA en los datos viejos)."""

from dataclasses import dataclass
from enum import Enum

from planeacion.domain.modelo.municipio import Municipio


class ReglaChiquinquira(Enum):
    """De qué lado de Chiquinquirá es una zona (y, en la flota, una ruta).

    La regla dura: una zona del sur solo puede caer en una ruta del sur. Vale
    para el PAR de rutas de cada lado (hoy SUR → {1, 2} y NORTE → {3, 4}), no
    para una ruta concreta; entre las del lado correcto deciden el repertorio y
    el balance.
    """

    SUR = "SUR"
    NORTE = "NORTE"


# Los clientes grandes que piden de vez en cuando y en cantidad: cada uno es su
# propia zona de un solo cliente y se despacha aparte, con el vehículo que
# convenga ese día. Van por nombre SIN prefijo de municipio porque la maestra los
# escribe de las dos maneras —`(TUNJA): ESTADIO REMONTA` y `COMFABOY`— y el
# prefijo no es parte de la identidad del cliente.
NOMBRES_ESPECIALES: tuple[str, ...] = (
    "COMULTRASAN LLEVA SEB",
    "GAITAN LLEVA SEB",
    "BARBOSA SALIDA PUENTE LLEVA SEB",
    "VIA CITE R5",
    "VIA CITE R7",
    "PEÑA BLANCA",
    "MEDELLIN",
    "IMPACTA",
    "PIZZA NOSTRA",
    "DISTRIROSAS",
    "DISTRIBUCIONES LEON - CONCEPCION",
    "ESTADIO REMONTA",
    "COMFABOY",
)


def nombre_sin_prefijo(nombre: str) -> str:
    """El nombre de la zona sin el `(MUNICIPIO):` de adelante.

    La maestra escribe el prefijo pegado o con espacio —`(TUNJA):PIZZA NOSTRA` y
    `(TUNJA): ESTADIO REMONTA`— así que no se puede comparar por igualdad.
    """
    _, separador, resto = nombre.partition("):")
    return (resto if separador else nombre).strip()


@dataclass(frozen=True)
class Zona:
    nombre: str
    municipio: Municipio
    regla_chiquinquira: ReglaChiquinquira | None = None
    activa: bool = True
    # Cliente que pide esporádicamente y en grande: no pasa por el repertorio y
    # se despacha con el vehículo que convenga ese día (ver NOMBRES_ESPECIALES).
    especial: bool = False
