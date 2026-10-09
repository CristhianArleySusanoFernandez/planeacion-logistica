"""Parseo de nombres de zona (RUTA) hacia municipio y regla de Chiquinquirá.

Los nombres vienen del Excel con espacios inconsistentes y al menos un caso
malformado ("(CHIQUINQUIRA:   CHIQUIN NORTE RUTA 3", sin cerrar el paréntesis),
por eso los regex son tolerantes y todo match se hace sobre el nombre normalizado.
"""

import re

from planeacion.domain.errores import ZonaInvalida
from planeacion.domain.modelo.municipio import MUNICIPIO_OTROS, MUNICIPIOS_PROPIOS, Municipio
from planeacion.domain.modelo.zona import ReglaChiquinquira, Zona

MUNICIPIO_CHIQUINQUIRA = "CHIQUINQUIRA"

# El prefijo normal es "(MUNICIPIO):"; se corta en ")" o ":" (lo primero que
# aparezca) para aguantar el caso malformado sin paréntesis de cierre.
_PREFIJO_MUNICIPIO = re.compile(r"^\(\s*([^):]+?)\s*[):]")
# El mismo paréntesis, pero en cualquier posición: hay nombres que lo traen
# corrido ("Y (TUNJA): RUTA OCCIDENTE", "W (TUNJA): ...") o al final
# ("PARAISO (TUNJA)"), y con el ancla al inicio quedaban todos en OTROS.
_MUNICIPIO_EN_CUALQUIER_LUGAR = re.compile(r"\(\s*([^():]+?)\s*[):]")
_PALABRA_SUR = re.compile(r"\bSUR\b")
_PALABRA_NORTE = re.compile(r"\bNORTE\b")


def normalizar_nombre_zona(crudo: str) -> str:
    """Colapsa espacios múltiples y recorta extremos: es la clave de match entre hojas."""
    return " ".join(crudo.split())


def parsear_municipio(nombre_zona: str) -> str:
    """Extrae el municipio del paréntesis "(XXX)" del nombre; sin él → OTROS.

    Dos niveles de confianza, y la diferencia es deliberada:

    - **Al inicio** del nombre se acepta lo que diga, aunque sea un municipio que
      la base todavía no conoce: ese es el formato oficial y una cabecera nueva
      tiene que poder entrar sola.
    - **En cualquier otra posición** solo se acepta si es uno de los municipios
      propios. Si no, hay nombres que crearían un pool fantasma sin carros:
      ``VIAJERA 1 (RAMIRIQUI)``, ``... BOYACA ALTO Y BAJO (CHIQUI) RUTA SUR 4``.

    Esto existe porque 34 de las 130 asignaciones que cruzaban de pool en los 16
    archivos de septiembre-octubre de 2026 eran nombres como
    ``Y (TUNJA): RUTA OCCIDENTE`` o ``PARAISO (TUNJA)``: el municipio estaba
    escrito, solo que no al principio.
    """
    texto = nombre_zona.strip()
    al_inicio = _PREFIJO_MUNICIPIO.match(texto)
    if al_inicio is not None:
        return al_inicio.group(1).strip().upper()
    for coincidencia in _MUNICIPIO_EN_CUALQUIER_LUGAR.finditer(texto):
        candidato = coincidencia.group(1).strip().upper()
        if candidato in MUNICIPIOS_PROPIOS:
            return candidato
    return MUNICIPIO_OTROS


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
