"""Municipio: el pool geográfico al que pertenecen zonas y carros."""

from dataclasses import dataclass

# Municipio especial para las zonas sin prefijo "(XXX):" (rutas viajeras/sueltas).
MUNICIPIO_OTROS = "OTROS"


@dataclass(frozen=True)
class Municipio:
    nombre: str
