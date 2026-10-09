"""Municipio: el pool geográfico al que pertenecen zonas y carros."""

from dataclasses import dataclass

# Municipio especial para las zonas sin prefijo "(XXX):" (rutas viajeras/sueltas).
MUNICIPIO_OTROS = "OTROS"

# Los municipios con cabecera y flota propia. Se usan para decidir si un "(XXX)"
# que aparece en medio de un nombre de zona es de verdad un municipio o es otra
# cosa: hay zonas con paréntesis decorativos —"VIAJERA 1 (RAMIRIQUI)",
# "... BOYACA ALTO Y BAJO (CHIQUI) RUTA SUR 4"— que no deben crear un pool.
MUNICIPIOS_PROPIOS = ("BARBOSA", "CHIQUINQUIRA", "TUNJA")


@dataclass(frozen=True)
class Municipio:
    nombre: str
