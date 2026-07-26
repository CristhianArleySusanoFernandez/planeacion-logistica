"""Auditoría y fusión de nombres de zona duplicados por normalización.

Detecta zonas cuyo nombre colapsa al mismo valor bajo ``normalizar_nombre_zona``
pero están guardadas con texto distinto (espacios, mayúsculas/acentos si los
hubiera), y decide cuál de las variantes es la canónica. Mover las referencias
en la base es trabajo del repositorio; aquí solo se decide qué fusionar con qué.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from planeacion.domain.modelo import Zona
from planeacion.domain.servicios.parseo_zonas import normalizar_nombre_zona


@dataclass(frozen=True)
class VarianteZona:
    """Una de las escrituras reales de un nombre de zona duplicado."""

    nombre: str
    clientes: int


@dataclass(frozen=True)
class GrupoDuplicado:
    """Dos o más zonas reales que normalizan al mismo nombre."""

    clave_normalizada: str
    variantes: tuple[VarianteZona, ...]


def agrupar_duplicados(
    zonas: Sequence[Zona], clientes_por_zona: Mapping[str, int]
) -> list[GrupoDuplicado]:
    """Agrupa las zonas por su nombre normalizado y devuelve solo los grupos con
    más de una variante real, con los que tienen más clientes primero (los que
    más urge fusionar)."""
    nombres_por_clave: dict[str, list[str]] = {}
    for zona in zonas:
        nombres_por_clave.setdefault(normalizar_nombre_zona(zona.nombre), []).append(zona.nombre)

    grupos = [
        GrupoDuplicado(
            clave_normalizada=clave,
            variantes=tuple(
                VarianteZona(nombre, clientes_por_zona.get(nombre, 0)) for nombre in sorted(nombres)
            ),
        )
        for clave, nombres in nombres_por_clave.items()
        if len(nombres) > 1
    ]
    return sorted(grupos, key=lambda g: -sum(v.clientes for v in g.variantes))


@dataclass(frozen=True)
class PlanFusion:
    """Qué zona sobrevive y cuáles se absorben en ella."""

    canonica: str
    variantes: tuple[str, ...]


@dataclass(frozen=True)
class ReferenciasMovidas:
    """Cuántas filas se reapuntaron a la zona canónica, por tabla."""

    clientes: int = 0
    repertorio: int = 0
    overrides: int = 0
    planeaciones: int = 0

    @property
    def total(self) -> int:
        return self.clientes + self.repertorio + self.overrides + self.planeaciones

    def __add__(self, otra: "ReferenciasMovidas") -> "ReferenciasMovidas":
        return ReferenciasMovidas(
            clientes=self.clientes + otra.clientes,
            repertorio=self.repertorio + otra.repertorio,
            overrides=self.overrides + otra.overrides,
            planeaciones=self.planeaciones + otra.planeaciones,
        )


def planear_fusion(grupo: GrupoDuplicado) -> PlanFusion:
    """Elige la zona canónica del grupo: la que más clientes tiene; si empatan,
    la de nombre más corto (la más limpia, sin espacios de sobra); si aún
    empatan, la primera alfabéticamente, para que el plan sea determinista."""
    ordenadas = sorted(grupo.variantes, key=lambda v: (-v.clientes, len(v.nombre), v.nombre))
    canonica = ordenadas[0]
    return PlanFusion(
        canonica=canonica.nombre,
        variantes=tuple(v.nombre for v in ordenadas[1:]),
    )
