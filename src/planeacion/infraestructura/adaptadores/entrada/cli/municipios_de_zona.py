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
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from planeacion.config.contenedor import Contenedor, crear_contenedor
from planeacion.config.settings import Settings
from planeacion.domain.modelo import MUNICIPIO_OTROS, Cliente, Municipio, Zona
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

# Piso de evidencia para mover una zona de pool. Un solo cliente visto una o dos
# veces no alcanza: siete zonas quedaban así (COMFABOY, IMPACTA, SANTO TOMAS,
# MM BRILLITH...) y moverlas seria decidir con casi nada. Se quedan en OTROS y se
# vuelven a mirar cuando haya mas histórico; mientras tanto no cambia nada,
# porque igual se balancean en el pool de su única ruta elegible.
MINIMO_CLIENTES = 2
MINIMO_ASIGNACIONES = 3
# Cuántos clientes de una ciudad hacen falta, en zonas normales, para aceptar que
# esa ciudad "pertenece" a un pool. Con menos, la ciudad no tiene geografía
# establecida en la base y no sirve para decidir.
MINIMO_CLIENTES_DE_LA_CIUDAD = 5


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
    """Zonas cuyo municipio guardado contradice lo que dice su propio nombre.

    Un nombre que no menciona ningún municipio no contradice nada: no se puede
    usar para devolver a ``OTROS`` una zona que se clasificó por evidencia. Sin
    esta guarda, correr el comando dos veces revertía los cambios de la primera
    corrida (``VENTAQUEMADA - VUELTA AL MUNDO`` volvía de TUNJA a OTROS).
    """
    propuestas = []
    for zona in zonas:
        segun_nombre = parsear_municipio(zona.nombre)
        if segun_nombre == MUNICIPIO_OTROS:
            continue
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


def normalizar_ciudad(ciudad: str) -> str:
    """La ciudad del cliente, sin el código DANE que ECOM a veces le pega delante.

    En la maestra la misma ciudad llega como ``TUNJA`` y como ``15001 - TUNJA``.
    Solo se quita el prefijo si es **numérico**: hay ciudades cuyo nombre lleva un
    guion de verdad (``BARBOSA - PUENTE NACIONAL``) y cortarlas perdería la mitad.
    """
    texto = (ciudad or "").strip().upper()
    prefijo, separador, resto = texto.partition(" - ")
    if separador and resto and prefijo.strip().isdigit():
        return resto.strip()
    return texto


def pools_por_ciudad(zonas: Sequence[Zona], clientes: Sequence[Cliente]) -> dict[str, tuple[str, int]]:
    """Ciudad → (pool que la atiende, cuántos clientes lo sostienen).

    Se calcula con la geografía de la **propia base**: en qué pool están las zonas
    normales de los clientes de esa ciudad. No hay una tabla de municipios de
    Boyacá en el código, y no hace falta: la operación ya dijo, con 294 clientes,
    que Moniquirá la atiende Barbosa.

    Las zonas especiales no votan: son justo las que se quieren decidir.
    """
    municipio_de_zona = {zona.nombre: zona.municipio.nombre for zona in zonas if not zona.especial}
    por_ciudad: dict[str, Counter[str]] = {}
    for cliente in clientes:
        if cliente.zona is None or cliente.zona.nombre not in municipio_de_zona:
            continue
        ciudad = normalizar_ciudad(cliente.ciudad or "")
        if not ciudad:
            continue
        por_ciudad.setdefault(ciudad, Counter())[municipio_de_zona[cliente.zona.nombre]] += 1
    resultado: dict[str, tuple[str, int]] = {}
    for ciudad, pools in por_ciudad.items():
        pool, cuantos = pools.most_common(1)[0]
        if cuantos >= MINIMO_CLIENTES_DE_LA_CIUDAD:
            resultado[ciudad] = (pool, cuantos)
    return resultado


@dataclass(frozen=True)
class PropuestaPorCiudad:
    """El municipio de una zona de UN cliente, decidido por su dirección."""

    nombre: str
    municipio_actual: str
    ciudad_del_cliente: str
    municipio_propuesto: str | None  # None = no hay con qué decidirlo
    clientes_que_lo_sostienen: int
    motivo: str


def proponer_por_la_ciudad_del_cliente(
    zonas: Sequence[Zona],
    clientes: Sequence[Cliente],
    candidatas: Collection[str],
) -> list[PropuestaPorCiudad]:
    """El municipio de una zona de un solo cliente, según DÓNDE ESTÁ el cliente.

    ``proponer_por_evidencia`` no sirve para estas zonas: exige 2 clientes y 3
    asignaciones, y una zona de un cliente que pide de vez en cuando nunca los
    junta. Pero tampoco habría que usarla, porque mide **quién la repartió** y eso
    puede ser circunstancial: a COMFABOY la llevó una ruta de Tunja, y su cliente
    está en Moniquirá, que en esta base la atiende Barbosa con 294 clientes.

    La dirección es el dato estable: el camión cambia, la puerta no.
    """
    geografia = pools_por_ciudad(zonas, clientes)
    por_zona: dict[str, list[Cliente]] = {}
    for cliente in clientes:
        if cliente.zona is not None and cliente.zona.nombre in candidatas:
            por_zona.setdefault(cliente.zona.nombre, []).append(cliente)

    propuestas: list[PropuestaPorCiudad] = []
    for zona in sorted(zonas, key=lambda z: z.nombre):
        if zona.nombre not in candidatas:
            continue
        suyos = por_zona.get(zona.nombre, [])
        ciudades = {normalizar_ciudad(cliente.ciudad or "") for cliente in suyos} - {""}
        if not ciudades:
            propuestas.append(
                PropuestaPorCiudad(
                    nombre=zona.nombre,
                    municipio_actual=zona.municipio.nombre,
                    ciudad_del_cliente="",
                    municipio_propuesto=None,
                    clientes_que_lo_sostienen=0,
                    motivo="sus clientes no tienen ciudad en la maestra",
                )
            )
            continue
        if len(ciudades) > 1:
            propuestas.append(
                PropuestaPorCiudad(
                    nombre=zona.nombre,
                    municipio_actual=zona.municipio.nombre,
                    ciudad_del_cliente=", ".join(sorted(ciudades)),
                    municipio_propuesto=None,
                    clientes_que_lo_sostienen=0,
                    motivo="sus clientes están en ciudades distintas",
                )
            )
            continue
        ciudad = ciudades.pop()
        encontrado = geografia.get(ciudad)
        if encontrado is None:
            propuestas.append(
                PropuestaPorCiudad(
                    nombre=zona.nombre,
                    municipio_actual=zona.municipio.nombre,
                    ciudad_del_cliente=ciudad,
                    municipio_propuesto=None,
                    clientes_que_lo_sostienen=0,
                    motivo=f"ninguna zona normal atiende {ciudad}: es una ciudad de verdad aparte",
                )
            )
            continue
        pool, cuantos = encontrado
        propuestas.append(
            PropuestaPorCiudad(
                nombre=zona.nombre,
                municipio_actual=zona.municipio.nombre,
                ciudad_del_cliente=ciudad,
                municipio_propuesto=pool if pool != zona.municipio.nombre else None,
                clientes_que_lo_sostienen=cuantos,
                motivo=(
                    f"{cuantos} cliente(s) de {ciudad} están en zonas del pool {pool}"
                    if pool != zona.municipio.nombre
                    else f"ya está en {pool}, que es el pool de {ciudad}"
                ),
            )
        )
    return propuestas


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
        asignaciones = sum(vistas.values())
        if clientes_por_zona[zona.nombre] < MINIMO_CLIENTES or asignaciones < MINIMO_ASIGNACIONES:
            continue  # evidencia demasiado flaca para mover el pool
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


def _lineas_de_ciudad(propuestas: Sequence[PropuestaPorCiudad]) -> list[str]:
    """La tabla de las zonas de un cliente: zona → ciudad → municipio propuesto."""
    if not propuestas:
        return []
    lineas = [
        "",
        "## Zonas de un solo cliente (se deciden por la dirección, no por el camión)",
        "",
        "La evidencia por rutas no las alcanza: exige 2 clientes y 3 asignaciones. Y tampoco habría "
        "que usarla, porque mide quién la repartió y eso puede ser circunstancial; la dirección es "
        "el dato estable. El pool de cada ciudad sale de la propia base: en qué pool están las "
        "zonas normales de los clientes de esa ciudad.",
        "",
        "| zona | pool hoy | ciudad del cliente | propuesto | evidencia |",
        "|---|---|---|---|---|",
    ]
    for p in propuestas:
        propuesto = p.municipio_propuesto or "— se queda"
        lineas.append(
            f"| `{p.nombre}` | {p.municipio_actual} | {p.ciudad_del_cliente or '—'} | "
            f"**{propuesto}** | {p.motivo} |"
        )
    return lineas


def _lineas_del_reporte(
    por_nombre: list[PropuestaZona],
    por_evidencia: list[PropuestaZona],
    por_ciudad: Sequence[PropuestaPorCiudad] = (),
) -> list[str]:
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
    lineas.append(
        "Sin prefijo en el nombre, pero siempre las reparte el mismo municipio. Se exigen al menos "
        f"{MINIMO_CLIENTES} cliente(s) y {MINIMO_ASIGNACIONES} asignación(es): con menos, la zona se "
        "queda en OTROS."
    )
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
    lineas.extend(_lineas_de_ciudad(por_ciudad))
    return lineas


def _aplicar(
    contenedor: Contenedor,
    cambios: Sequence[tuple[str, str, str]],
    actuales: Mapping[str, Zona],
) -> int:
    """Upsert por nombre del municipio nuevo, recalculando la regla de Chiquinquirá.

    ``cambios`` son tríos (zona, municipio actual, municipio propuesto). Todo lo
    demás de la zona se conserva leyéndolo de ``actuales``: cambiar el municipio no
    puede apagar una zona ni desmarcar un cliente especial de rebote.
    """
    aplicados = 0
    for nombre, antes, propuesto in cambios:
        municipio = Municipio(nombre=propuesto)
        actual = actuales.get(nombre)
        contenedor.zonas.actualizar_zona(
            Zona(
                nombre=nombre,
                municipio=municipio,
                regla_chiquinquira=detectar_regla_chiquinquira(nombre, municipio.nombre),
                activa=actual.activa if actual else True,
                especial=actual.especial if actual else False,
            )
        )
        print(f"  {nombre}: {antes} -> {propuesto}")
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
    todos_los_clientes = contenedor.clientes.listar()
    clientes_por_zona: Counter[str] = Counter()
    for cliente in todos_los_clientes:
        if cliente.zona is not None:
            clientes_por_zona[cliente.zona.nombre] += 1

    print(f"Leyendo {len(archivos)} archivo(s) para la evidencia...")
    observaciones = _observaciones(archivos, set(pool_de_ruta))

    por_nombre = proponer_por_el_nombre(zonas)
    por_evidencia = proponer_por_evidencia(zonas, pool_de_ruta, observaciones, clientes_por_zona)
    # Las zonas de UN cliente no las alcanza la evidencia por rutas (exige 2
    # clientes y 3 asignaciones), así que se deciden por la dirección del cliente.
    de_un_cliente = {zona.nombre for zona in zonas if clientes_por_zona[zona.nombre] == 1 and zona.activa}
    por_ciudad = proponer_por_la_ciudad_del_cliente(zonas, todos_los_clientes, de_un_cliente)
    reporte = "\n".join(_lineas_del_reporte(por_nombre, por_evidencia, por_ciudad))
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
    actuales = {zona.nombre: zona for zona in zonas}
    cambios = [(p.nombre, p.municipio_actual, p.municipio_propuesto) for p in por_nombre + por_evidencia]
    cambios += [
        (p.nombre, p.municipio_actual, p.municipio_propuesto)
        for p in por_ciudad
        if p.municipio_propuesto is not None
    ]
    aplicados = _aplicar(contenedor, cambios, actuales)
    print(f"\n{aplicados} zona(s) actualizada(s).")

    pendientes = proponer_por_el_nombre(contenedor.zonas.listar())
    print(f"Verificación: quedan {len(pendientes)} zona(s) con el municipio distinto a su nombre.")
    return 0
