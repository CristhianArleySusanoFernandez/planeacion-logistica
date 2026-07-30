"""DTOs del asistente de clientes nuevos (lo que consumen el CLI y la UI)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SugerenciaDTO:
    zona: str
    municipio: str
    vecinos_en_zona: int
    total_vecinos: int
    confianza: str  # valor de ConfianzaSugerencia: "barrio" | "ciudad"
    alternativas: tuple[tuple[str, int], ...]  # (nombre de zona, vecinos)


@dataclass(frozen=True)
class ClientePendiente:
    codigo: str
    motivo: str  # valor de MotivoNoResuelto
    nombre: str | None
    documento: str | None
    direccion: str | None
    ciudad: str | None  # ya con la corrección de ubicación aplicada, si existía
    barrio: str | None
    sugerencia: SugerenciaDTO | None  # None = Rudy asigna a mano sin ayuda
