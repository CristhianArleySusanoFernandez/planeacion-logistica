"""Normalización de ciudad y barrio para comparar ubicaciones entre fuentes.

La maestra guarda la ciudad como "TUNJA" pero el ECOM la trae como
"15001 - TUNJA" (código DANE + nombre), con acentos y espacios inconsistentes.
Toda comparación de ubicación se hace sobre el texto normalizado.
"""

import re
import unicodedata

_PREFIJO_DANE = re.compile(r"^\d+\s*-\s*")


def normalizar_ubicacion(texto: str | None) -> str:
    """MAYÚSCULAS, sin acentos, espacios colapsados y sin el prefijo DANE "NNNNN - "."""
    if texto is None:
        return ""
    sin_prefijo = _PREFIJO_DANE.sub("", texto.strip())
    descompuesto = unicodedata.normalize("NFKD", sin_prefijo)
    sin_acentos = "".join(letra for letra in descompuesto if not unicodedata.combining(letra))
    return " ".join(sin_acentos.upper().split())
