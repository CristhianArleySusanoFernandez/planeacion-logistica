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

**Dos coincidencias, no una.** Cinco conductores llevan dos planillas del mismo
camión (Fabián 1 y 2, Angélica 1 y 2, Raúl, Javier Reyes, Carlos) y la operación
intercambia carga entre las dos según el día, justamente para que lleguen parejas
a bodega. Si la app pone una zona en la planilla 1 y la hoja la tiene en la 2, la
carga va en el **mismo camión**: cuál de las dos hojas la lleve lo decide bodega.
Por eso se cuentan las dos cosas —por planilla, que es lo estricto contra la hoja,
y por camión, que es lo que mide si la carga llega al vehículo correcto— y nunca
se reporta una sin la otra.
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
    # Las dos rutas son planillas del mismo camión: la carga va en el vehículo
    # correcto y solo cambia en cuál de sus dos hojas aparece.
    mismo_conductor: bool = False


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
    def mismo_camion(self) -> int:
        """Diferencias que son solo un cambio de planilla dentro del mismo camión."""
        return sum(1 for diferencia in self.diferencias if diferencia.mismo_conductor)

    @property
    def coincidencias_por_camion(self) -> int:
        """Zonas cuya carga termina en el vehículo correcto.

        Siempre mayor o igual que ``coincidencias``: un acierto por planilla lo es
        también por camión.
        """
        return self.coincidencias + self.mismo_camion

    @property
    def porcentaje_por_camion(self) -> float:
        return self.coincidencias_por_camion / self.comparables if self.comparables else 0.0

    @property
    def porcentaje_pesimista(self) -> float:
        """Coincidencia sobre TODAS las zonas del manual: lo no cubierto cuenta como fallo."""
        return self.coincidencias / self.zonas_manuales if self.zonas_manuales else 0.0


def comparar_asignaciones(
    manual: Mapping[str, str],
    propuesta: Sequence[AsignacionZona],
    claves_por_carro: Mapping[str, str] | None = None,
) -> ComparacionAsignaciones:
    """Coteja el reparto manual (nombre de zona → número de carro) contra el propuesto.

    Los nombres se normalizan de los dos lados antes de cruzarse: en los Excel el
    mismo nombre de zona aparece con distinta cantidad de espacios.

    ``claves_por_carro`` es número de ruta → ``conductor_clave``, y es lo que
    permite ver si dos rutas distintas son dos planillas del mismo camión. Sin él
    la comparación por camión coincide con la de planilla: no se inventa igualdad
    donde no se sabe.
    """
    claves = claves_por_carro or {}
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
            clave_manual = claves.get(carro_manual)
            diferencias.append(
                DiferenciaAsignacion(
                    zona=zona,
                    municipio=asignacion.zona.municipio.nombre,
                    carro_manual=carro_manual,
                    carro_propuesto=asignacion.carro.numero,
                    clientes=asignacion.clientes,
                    pesos=asignacion.pesos,
                    # Sin la clave del carro manual no se puede afirmar que sea el
                    # mismo camión, así que se cuenta como diferencia plena.
                    mismo_conductor=clave_manual is not None
                    and clave_manual == asignacion.carro.conductor_clave,
                )
            )

    return ComparacionAsignaciones(
        zonas_manuales=len(manual_normalizado),
        coincidencias=coincidencias,
        diferencias=tuple(diferencias),
        sin_propuesta=tuple(sin_propuesta),
    )
