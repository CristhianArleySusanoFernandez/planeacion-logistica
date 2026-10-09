"""Comando que corrige el municipio de las zonas mal clasificadas.

Uso:
    uv run planeacion-municipios-zona "datos/*.xlsm"            # solo reporta
    uv run planeacion-municipios-zona "datos/*.xlsm" --aplicar

Por qué existe: medido sobre los 16 archivos de septiembre y octubre de 2026,
**130 de 1.304 asignaciones zona→ruta (10 %) cruzaban de pool** —una zona de un
municipio repartida por una ruta de otro—, y casi ninguna era un cruce real. Dos
causas distintas, que este comando arregla por separado y reporta aparte:

1. **El nombre lo dice y nadie lo leía.** `Y (TUNJA): RUTA OCCIDENTE` o
   `PARAISO (TUNJA)` tienen el municipio escrito, solo que no al principio. El
   parseo ya los entiende; lo que falta es actualizar la fila guardada.
2. **El nombre no lo dice, pero la operación sí.** `VENTAQUEMADA - VUELTA AL
   MUNDO` o `RUTA MANANTIAL` no llevan prefijo y quedaron en `OTROS`, pero las
   atienden siempre rutas de Tunja. Acá el municipio se deduce de la **evidencia
   de los archivos**: quién la repartió y cuántas veces.

Nada de esto cambia el balanceador. La mayoría de estas zonas **ya se balancea**
en el pool de su carro elegible (ver `_municipio_de_balanceo`); lo que se corrige
es la etiqueta, para que las métricas por municipio y los reportes digan la
verdad. Las que sí cambian de pool se marcan en el reporte.
"""

import argparse
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from planeacion.config.contenedor import Contenedor, crear_contenedor
from planeacion.config.settings import Settings
from planeacion.domain.modelo import MUNICIPIO_OTROS, Municipio, Zona
from planeacion.domain.servicios.parseo_zonas import (
    detectar_regla_chiquinquira,
    normalizar_nombre_zona,
    parsear_municipio,
)
from planeacion.infraestructura.adaptadores.salida.excel.lector_referencia import (
    HOJA_PLANEACION,
    LectorReferenciaExcel,
)

# RAQUIRA se queda en OTROS por decisión del negocio: es la zona viajera de
# manual —la reparten las rutas 3 y 4 de Chiquinquirá— y el caso está documentado
# como limitación conocida en docs/dominio.md. Cambiarla escondería el ejemplo.
ZONAS_QUE_SE_QUEDAN_VIAJERAS = ("RAQUIRA",)


@dataclass(frozen=True)
class PropuestaZona:
    """Un cambio de municipio propuesto, con la evidencia que lo sostiene."""

    nombre: str
    municipio_actual: str
    municipio_propuesto: str
    por_el_nombre: bool  # False = deducido de quién la repartió
    clientes: int
    rutas: tuple[tuple[str, int], ...] = ()  # (número de ruta, veces observada)
    pools_observados: tuple[tuple[str, int], ...] = ()

    @property
    def asignaciones(self) -> int:
        return sum(veces for _, veces in self.rutas)

    @property
    def unanime(self) -> bool:
        """¿Todas las rutas que la atendieron son del mismo pool?"""
        return len(self.pools_observados) <= 1

    @property
    def evidencia(self) -> str:
        detalle = ", ".join(f"ruta {numero} ×{veces}" for numero, veces in self.rutas)
        if self.por_el_nombre:
            return "el municipio está en el nombre"
        reparto = dict(self.pools_observados)
        sufijo = "" if self.unanime else f" — NO unánime: {reparto}"
        return f"{detalle}{sufijo}"


def proponer_por_el_nombre(zonas: list[Zona]) -> list[PropuestaZona]:
    """Zonas cuyo municipio guardado no coincide con lo que dice su propio nombre."""
    propuestas = []
    for zona in zonas:
        segun_nombre = parsear_municipio(zona.nombre)
        if segun_nombre != zona.municipio.nombre:
            propuestas.append(
                PropuestaZona(
                    nombre=zona.nombre,
                    municipio_actual=zona.municipio.nombre,
                    municipio_propuesto=segun_nombre,
                    por_el_nombre=True,
                    clientes=0,
                )
            )
    return sorted(propuestas, key=lambda p: p.nombre)


def proponer_por_evidencia(
    zonas: list[Zona],
    pool_de_ruta: dict[str, str],
    observaciones: dict[str, Counter[str]],
    clientes_por_zona: Counter[str],
) -> list[PropuestaZona]:
    """Zonas sin prefijo que atiende siempre un municipio concreto.

    Solo se proponen las que hoy están en ``OTROS`` **y** cuyo nombre no dice nada
    (esas ya las resuelve ``proponer_por_el_nombre``). El municipio propuesto es el
    del pool que más veces la repartió; si hubo varios, se reporta y la decisión
    la toma quien lee.
    """
    propuestas = []
    for zona in zonas:
        if zona.municipio.nombre != MUNICIPIO_OTROS:
            continue
        if parsear_municipio(zona.nombre) != MUNICIPIO_OTROS:
            continue
        if zona.nombre in ZONAS_QUE_SE_QUEDAN_VIAJERAS:
            continue
        vistas = observaciones.get(zona.nombre)
        if not vistas:
            continue
        pools: Counter[str] = Counter()
        for ruta, veces in vistas.items():
            pools[pool_de_ruta[ruta]] += veces
        propuesto, _ = pools.most_common(1)[0]
        if propuesto == MUNICIPIO_OTROS:
            continue  # es una viajera de verdad: se queda como está
        propuestas.append(
            PropuestaZona(
                nombre=zona.nombre,
                municipio_actual=zona.municipio.nombre,
                municipio_propuesto=propuesto,
                por_el_nombre=False,
                clientes=clientes_por_zona[zona.nombre],
                rutas=tuple(vistas.most_common()),
                pools_observados=tuple(pools.most_common()),
            )
        )
    return sorted(propuestas, key=lambda p: (-p.asignaciones, p.nombre))


def _observaciones(rutas_xlsm: list[Path], numeros_de_flota: set[str]) -> dict[str, Counter[str]]:
    """Zona → cuántas veces la repartió cada ruta, en los archivos dados."""
    observaciones: dict[str, Counter[str]] = defaultdict(Counter)
    for ruta_archivo in rutas_xlsm:
        with LectorReferenciaExcel(ruta_archivo) as lector:
            if not lector.tiene_hoja(HOJA_PLANEACION):
                print(f"AVISO: {ruta_archivo.name} no tiene {HOJA_PLANEACION}; se salta.", file=sys.stderr)
                continue
            for fila in lector.leer_asignaciones_planeacion():
                if fila.carro in numeros_de_flota:
                    observaciones[normalizar_nombre_zona(fila.zona)][fila.carro] += 1
    return observaciones


def _expandir(patrones: list[str]) -> list[Path]:
    rutas: list[Path] = []
    for patron in patrones:
        if "*" in patron or "?" in patron:
            rutas.extend(sorted(Path().glob(patron)))
        else:
            rutas.append(Path(patron))
    return list(dict.fromkeys(rutas))


def _lineas_del_reporte(por_nombre: list[PropuestaZona], por_evidencia: list[PropuestaZona]) -> list[str]:
    lineas = [f"# Municipio de las zonas — {date.today()}", ""]
    lineas.append(
        "Criterio: el municipio de una zona define el pool con el que se balancea. "
        "Nada de esto toca el balanceador."
    )
    lineas.append("")
    lineas.append(f"## Por el nombre ({len(por_nombre)})")
    lineas.append("")
    lineas.append("El municipio está escrito en el nombre y la fila guardada no lo refleja.")
    for propuesta in por_nombre:
        lineas.append(
            f"- `{propuesta.nombre}`: {propuesta.municipio_actual} → **{propuesta.municipio_propuesto}**"
        )
    lineas.append("")
    lineas.append(f"## Por la evidencia de los archivos ({len(por_evidencia)})")
    lineas.append("")
    lineas.append("Sin prefijo en el nombre, pero siempre las reparte el mismo municipio.")
    for propuesta in por_evidencia:
        marca = "" if propuesta.unanime else "  ⚠"
        lineas.append(
            f"- `{propuesta.nombre}`: {propuesta.municipio_actual} → "
            f"**{propuesta.municipio_propuesto}** — {propuesta.clientes} cliente(s), "
            f"{propuesta.asignaciones} asignación(es): {propuesta.evidencia}{marca}"
        )
    if ZONAS_QUE_SE_QUEDAN_VIAJERAS:
        lineas.append("")
        lineas.append("## Excluidas a propósito")
        lineas.append("")
        for nombre in ZONAS_QUE_SE_QUEDAN_VIAJERAS:
            lineas.append(f"- `{nombre}`: se queda en OTROS; es la zona viajera documentada.")
    return lineas


def _aplicar(contenedor: Contenedor, propuestas: list[PropuestaZona], activas: dict[str, bool]) -> int:
    """Upsert por nombre del municipio nuevo, recalculando la regla de Chiquinquirá."""
    aplicados = 0
    for propuesta in propuestas:
        municipio = Municipio(nombre=propuesta.municipio_propuesto)
        contenedor.zonas.actualizar_zona(
            Zona(
                nombre=propuesta.nombre,
                municipio=municipio,
                regla_chiquinquira=detectar_regla_chiquinquira(propuesta.nombre, municipio.nombre),
                activa=activas.get(propuesta.nombre, True),
            )
        )
        print(f"  {propuesta.nombre}: {propuesta.municipio_actual} -> {propuesta.municipio_propuesto}")
        aplicados += 1
    return aplicados


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Corrige el municipio de las zonas mal clasificadas (por nombre y por evidencia)."
    )
    parser.add_argument("rutas", nargs="+", help="los .xlsm de planeación (acepta globs)")
    parser.add_argument(
        "--aplicar", action="store_true", help="escribe los cambios (por defecto solo reporta)"
    )
    parser.add_argument("--salidas", type=Path, default=Path("salidas"), help="carpeta del reporte .md")
    args = parser.parse_args()

    archivos = [ruta for ruta in _expandir(args.rutas) if ruta.exists()]
    if not archivos:
        print("ERROR: ninguno de los archivos indicados existe.", file=sys.stderr)
        return 1
    try:
        contenedor = crear_contenedor(Settings())
    except ValidationError as error:
        print(f"Faltan credenciales de Supabase: {error}", file=sys.stderr)
        return 1

    zonas = contenedor.zonas.listar()
    carros = contenedor.carros.listar()
    pool_de_ruta = {c.numero: (c.municipio.nombre if c.municipio else MUNICIPIO_OTROS) for c in carros}
    clientes_por_zona: Counter[str] = Counter()
    for cliente in contenedor.clientes.listar():
        if cliente.zona is not None:
            clientes_por_zona[cliente.zona.nombre] += 1

    print(f"Leyendo {len(archivos)} archivo(s) para la evidencia...")
    observaciones = _observaciones(archivos, set(pool_de_ruta))

    por_nombre = proponer_por_el_nombre(zonas)
    por_evidencia = proponer_por_evidencia(zonas, pool_de_ruta, observaciones, clientes_por_zona)
    reporte = "\n".join(_lineas_del_reporte(por_nombre, por_evidencia))
    print()
    print(reporte)

    args.salidas.mkdir(parents=True, exist_ok=True)
    destino = args.salidas / f"municipios_zona_{date.today().isoformat()}.md"
    destino.write_text(reporte, encoding="utf-8")
    print(f"\nReporte guardado en {destino}")

    if not args.aplicar:
        print("\nModo reporte: no se escribió nada. Para aplicar: --aplicar")
        return 0

    print("\n" + "=" * 78)
    print("APLICANDO")
    print("=" * 78)
    activas = {zona.nombre: zona.activa for zona in zonas}
    aplicados = _aplicar(contenedor, por_nombre + por_evidencia, activas)
    print(f"\n{aplicados} zona(s) actualizada(s).")

    pendientes = proponer_por_el_nombre(contenedor.zonas.listar())
    print(f"Verificación: quedan {len(pendientes)} zona(s) con el municipio distinto a su nombre.")
    return 0
