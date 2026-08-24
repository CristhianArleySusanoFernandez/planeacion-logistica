"""Compara la asignación zona→carro que propuso la app contra la que se hizo a mano.

Sirve para medir qué tan cerca queda la máquina de Rudy sobre planeaciones ya
cerradas. Es lógica pura: recibe los dos repartos y devuelve el conteo, sin saber
de dónde salió cada uno.

Sobre qué se calcula el porcentaje: la maestra de clientes de la base no cubre
necesariamente a todos los clientes de un día viejo, así que puede haber zonas
que Rudy asignó y que la app no llegó a producir. Mezclarlas con las diferencias
reales confundiría dos problemas distintos —una regla de negocio faltante y un
hueco de cobertura de la maestra—, así que se reportan aparte y el porcentaje
principal se calcula sobre la intersección. ``porcentaje_pesimista`` da la otra
lectura, contando lo no cubierto como no coincidencia.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from planeacion.domain.modelo.balanceo import AsignacionZona
from planeacion.domain.servicios.parseo_zonas import normalizar_nombre_zona


@dataclass(frozen=True)
class DiferenciaAsignacion:
    """Una zona que la app puso en un carro distinto al de la planeación manual."""

    zona: str
    municipio: str
    carro_manual: str
    carro_propuesto: str
    clientes: int
    pesos: Decimal


@dataclass(frozen=True)
class ComparacionAsignaciones:
    """El resultado de cotejar un día: cuánto coincidió y en qué difirió."""

    zonas_manuales: int
    coincidencias: int
    diferencias: tuple[DiferenciaAsignacion, ...]
    sin_propuesta: tuple[str, ...]  # zonas del manual que la app no asignó

    @property
    def comparables(self) -> int:
        """Zonas presentes en ambos repartos: el denominador del porcentaje principal."""
        return self.coincidencias + len(self.diferencias)

    @property
    def porcentaje(self) -> float:
        """Coincidencia sobre las zonas que ambos lados asignaron. Sin comparables, 0."""
        return self.coincidencias / self.comparables if self.comparables else 0.0

    @property
    def porcentaje_pesimista(self) -> float:
        """Coincidencia sobre TODAS las zonas del manual: lo no cubierto cuenta como fallo."""
        return self.coincidencias / self.zonas_manuales if self.zonas_manuales else 0.0


def comparar_asignaciones(
    manual: Mapping[str, str], propuesta: Sequence[AsignacionZona]
) -> ComparacionAsignaciones:
    """Coteja el reparto manual (nombre de zona → número de carro) contra el propuesto.

    Los nombres se normalizan de los dos lados antes de cruzarse: en los Excel el
    mismo nombre de zona aparece con distinta cantidad de espacios.
    """
    manual_normalizado = {normalizar_nombre_zona(zona): carro for zona, carro in manual.items()}
    propuesta_por_zona = {
        normalizar_nombre_zona(asignacion.zona.nombre): asignacion for asignacion in propuesta
    }

    coincidencias = 0
    diferencias: list[DiferenciaAsignacion] = []
    sin_propuesta: list[str] = []
    for zona, carro_manual in sorted(manual_normalizado.items()):
        asignacion = propuesta_por_zona.get(zona)
        if asignacion is None:
            sin_propuesta.append(zona)
        elif asignacion.carro.numero == carro_manual:
            coincidencias += 1
        else:
            diferencias.append(
                DiferenciaAsignacion(
                    zona=zona,
                    municipio=asignacion.zona.municipio.nombre,
                    carro_manual=carro_manual,
                    carro_propuesto=asignacion.carro.numero,
                    clientes=asignacion.clientes,
                    pesos=asignacion.pesos,
                )
            )

    return ComparacionAsignaciones(
        zonas_manuales=len(manual_normalizado),
        coincidencias=coincidencias,
        diferencias=tuple(diferencias),
        sin_propuesta=tuple(sin_propuesta),
    )
