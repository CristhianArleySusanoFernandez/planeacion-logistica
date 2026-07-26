"""Sugiere la zona de un cliente nuevo por voto mayoritario de sus vecinos.

Replica lo que Rudy hace a mano: filtrar la maestra por la ciudad y el barrio
del cliente nuevo y asignarle la zona que tienen los vecinos. El servicio es
puro: recibe la lista de clientes existentes por parámetro y la indexa una vez;
``sugerir`` es solo consulta.
"""

from collections import Counter
from collections.abc import Sequence

from planeacion.domain.modelo import Cliente, Zona
from planeacion.domain.modelo.sugerencia import ConfianzaSugerencia, SugerenciaDeZona
from planeacion.domain.servicios.normalizacion_ubicacion import normalizar_ubicacion


class SugeridorDeZona:
    def __init__(self, clientes_existentes: Sequence[Cliente]) -> None:
        self._por_ciudad_barrio: dict[tuple[str, str], Counter[Zona]] = {}
        self._por_ciudad: dict[str, Counter[Zona]] = {}
        for cliente in clientes_existentes:
            if cliente.zona is None:
                continue
            ciudad = normalizar_ubicacion(cliente.ciudad)
            barrio = normalizar_ubicacion(cliente.barrio)
            if not ciudad:
                continue
            self._por_ciudad.setdefault(ciudad, Counter())[cliente.zona] += 1
            if barrio:
                self._por_ciudad_barrio.setdefault((ciudad, barrio), Counter())[cliente.zona] += 1

    def sugerir(
        self, ciudad: str | None, barrio: str | None, max_alternativas: int = 3
    ) -> SugerenciaDeZona | None:
        """Match exacto por (ciudad, barrio) normalizados; sin vecinos ahí, solo por
        ciudad (confianza menor); sin nada → None (asignación manual sin ayuda)."""
        ciudad_normalizada = normalizar_ubicacion(ciudad)
        barrio_normalizado = normalizar_ubicacion(barrio)

        votos = (
            self._por_ciudad_barrio.get((ciudad_normalizada, barrio_normalizado))
            if barrio_normalizado
            else None
        )
        confianza = ConfianzaSugerencia.BARRIO
        if not votos:
            votos = self._por_ciudad.get(ciudad_normalizada)
            confianza = ConfianzaSugerencia.CIUDAD
        if not votos:
            return None

        # Más vecinos primero; el empate se rompe por nombre para ser determinista.
        ordenadas = sorted(votos.items(), key=lambda par: (-par[1], par[0].nombre))
        zona_ganadora, conteo = ordenadas[0]
        return SugerenciaDeZona(
            zona_sugerida=zona_ganadora,
            vecinos_en_zona=conteo,
            total_vecinos=sum(votos.values()),
            confianza=confianza,
            alternativas=tuple(ordenadas[1 : 1 + max_alternativas]),
        )
