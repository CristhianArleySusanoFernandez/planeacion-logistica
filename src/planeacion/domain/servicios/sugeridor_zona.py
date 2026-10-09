"""Sugiere la zona de un cliente nuevo por voto mayoritario de sus vecinos.

Replica lo que la operación hace a mano: filtrar la maestra por la ciudad y el
barrio del cliente nuevo y asignarle la zona que tienen los vecinos. El servicio
es puro: recibe la lista de clientes existentes por parámetro y la indexa una
vez; ``sugerir`` es solo consulta.

Devuelve las **tres mejores zonas con su respaldo** y no solo la ganadora,
porque el margen es parte de la decisión, y **vecinos de ejemplo con su
dirección**, porque quien decide reconoce la calle aunque no reconozca la zona.
"""

from collections.abc import Sequence

from planeacion.domain.modelo import Cliente, Zona
from planeacion.domain.modelo.sugerencia import (
    MAX_VECINOS_DE_EJEMPLO,
    ConfianzaSugerencia,
    OpcionDeZona,
    SugerenciaDeZona,
    VecinoDeEjemplo,
)
from planeacion.domain.servicios.normalizacion_ubicacion import normalizar_ubicacion

# Cuántas zonas candidatas se muestran. Tres es lo que cabe sin que la pantalla
# se vuelva una lista para leer en vez de una decisión para tomar.
MAX_OPCIONES = 3


class SugeridorDeZona:
    def __init__(self, clientes_existentes: Sequence[Cliente]) -> None:
        # Se guardan los vecinos y no solo el conteo: de ellos salen los
        # ejemplos con dirección. Son ~9.200 clientes, cabe de sobra.
        self._por_ciudad_barrio: dict[tuple[str, str], dict[str, list[Cliente]]] = {}
        self._por_ciudad: dict[str, dict[str, list[Cliente]]] = {}
        self._zonas: dict[str, Zona] = {}
        for cliente in clientes_existentes:
            if cliente.zona is None:
                continue
            ciudad = normalizar_ubicacion(cliente.ciudad)
            barrio = normalizar_ubicacion(cliente.barrio)
            if not ciudad:
                continue
            self._zonas.setdefault(cliente.zona.nombre, cliente.zona)
            self._por_ciudad.setdefault(ciudad, {}).setdefault(cliente.zona.nombre, []).append(cliente)
            if barrio:
                vecinos = self._por_ciudad_barrio.setdefault((ciudad, barrio), {})
                vecinos.setdefault(cliente.zona.nombre, []).append(cliente)

    def sugerir(
        self, ciudad: str | None, barrio: str | None, max_opciones: int = MAX_OPCIONES
    ) -> SugerenciaDeZona | None:
        """Escalera de respaldo: (ciudad, barrio) → solo ciudad → sin sugerencia.

        Los dos escalones comparan sobre el texto **normalizado** (mayúsculas,
        sin tildes, espacios colapsados y sin el prefijo DANE "15001 - "), así
        que no hace falta un escalón aparte para eso: "Chivatá" y "CHIVATA  "
        caen en el mismo grupo desde el primer intento.
        """
        ciudad_normalizada = normalizar_ubicacion(ciudad)
        barrio_normalizado = normalizar_ubicacion(barrio)

        vecinos = (
            self._por_ciudad_barrio.get((ciudad_normalizada, barrio_normalizado))
            if barrio_normalizado
            else None
        )
        confianza = ConfianzaSugerencia.BARRIO
        if not vecinos:
            vecinos = self._por_ciudad.get(ciudad_normalizada)
            confianza = ConfianzaSugerencia.CIUDAD
        if not vecinos:
            return None

        total = sum(len(clientes) for clientes in vecinos.values())
        # Más vecinos primero; el empate se rompe por nombre de zona para que la
        # pantalla no cambie de orden entre dos cargas iguales.
        ordenadas = sorted(vecinos.items(), key=lambda par: (-len(par[1]), par[0]))
        opciones = tuple(
            OpcionDeZona(
                zona=self._zonas[nombre],
                vecinos=len(clientes),
                total_vecinos=total,
                ejemplos=_ejemplos(clientes),
            )
            for nombre, clientes in ordenadas[:max_opciones]
        )
        return SugerenciaDeZona(opciones=opciones, total_vecinos=total, confianza=confianza)


def _ejemplos(clientes: Sequence[Cliente]) -> tuple[VecinoDeEjemplo, ...]:
    """Hasta tres vecinos, los que tengan dirección primero.

    Un vecino sin dirección no sirve para reconocer la calle, que es justamente
    para lo que están. El orden por código después deja la pantalla estable.
    """
    elegidos = sorted(clientes, key=lambda cliente: (not cliente.direccion, cliente.codigo))
    return tuple(
        VecinoDeEjemplo(
            codigo=cliente.codigo,
            nombre=cliente.razon_social,
            direccion=cliente.direccion,
        )
        for cliente in elegidos[:MAX_VECINOS_DE_EJEMPLO]
    )
