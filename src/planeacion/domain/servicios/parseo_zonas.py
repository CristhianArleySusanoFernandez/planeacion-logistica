"""Parseo de nombres de zona (RUTA) hacia municipio y regla de Chiquinquirá.

Los nombres vienen del Excel con espacios inconsistentes y al menos un caso
malformado ("(CHIQUINQUIRA:   CHIQUIN NORTE RUTA 3", sin cerrar el paréntesis),
por eso los regex son tolerantes y todo match se hace sobre el nombre normalizado.
"""

import re

from planeacion.domain.errores import ZonaInvalida
from planeacion.domain.modelo.municipio import MUNICIPIO_OTROS, Municipio
from planeacion.domain.modelo.zona import ReglaChiquinquira, Zona

MUNICIPIO_CHIQUINQUIRA = "CHIQUINQUIRA"

# El prefijo normal es "(MUNICIPIO):"; se corta en ")" o ":" (lo primero que
# aparezca) para aguantar el caso malformado sin paréntesis de cierre.
_PREFIJO_MUNICIPIO = re.compile(r"^\(\s*([^):]+?)\s*[):]")
_PALABRA_SUR = re.compile(r"\bSUR\b")
_PALABRA_NORTE = re.compile(r"\bNORTE\b")


def normalizar_nombre_zona(crudo: str) -> str:
    """Colapsa espacios múltiples y recorta extremos: es la clave de match entre hojas."""
    return " ".join(crudo.split())


def parsear_municipio(nombre_zona: str) -> str:
    """Extrae el municipio del prefijo "(XXX):"; sin prefijo → OTROS."""
    coincidencia = _PREFIJO_MUNICIPIO.match(nombre_zona.strip())
    if coincidencia is None:
        return MUNICIPIO_OTROS
    return coincidencia.group(1).strip().upper()


def detectar_regla_chiquinquira(nombre_zona: str, municipio: str) -> ReglaChiquinquira | None:
    """SUR/NORTE como palabra completa (así "SURINEMA" no cuenta). Ambiguo → None."""
    if municipio != MUNICIPIO_CHIQUINQUIRA:
        return None
    texto = nombre_zona.upper()
    es_sur = _PALABRA_SUR.search(texto) is not None
    es_norte = _PALABRA_NORTE.search(texto) is not None
    if es_sur == es_norte:
        return None
    return ReglaChiquinquira.SUR if es_sur else ReglaChiquinquira.NORTE


def crear_zona(nombre_crudo: str, activa: bool = True) -> Zona:
    """Construye una Zona desde el texto crudo de RUTA."""
    nombre = normalizar_nombre_zona(nombre_crudo)
    if not nombre:
        raise ZonaInvalida("el nombre de la zona está vacío")
    municipio = parsear_municipio(nombre)
    regla = detectar_regla_chiquinquira(nombre, municipio)
    return Zona(
        nombre=nombre,
        municipio=Municipio(nombre=municipio),
        regla_chiquinquira=regla,
        activa=activa,
    )
